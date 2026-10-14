import json

import httpx
import pytest
import pytest_asyncio

from graphmem.api import create_app
from graphmem.mcp_server import build
from conftest import tid

ADMIN = {"Authorization": "Bearer admin-secret"}


@pytest_asyncio.fixture
async def client(gm):
    app = create_app(gm, admin_key="admin-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def make_agent(client, gm, name, tenant=None, scopes=("read", "write")):
    r = await client.post("/admin/agents", json={"agent": name}, headers=ADMIN)
    assert r.status_code == 200
    if tenant:
        r2 = await client.post("/admin/grants", json={"agent": name, "tenant": tenant, "scopes": list(scopes)}, headers=ADMIN)
        assert r2.status_code == 200
    return {"Authorization": "Bearer " + r.json()["api_key"]}


async def test_auth_required_and_keys_hashed(client, gm):
    assert (await client.get("/v1/me")).status_code == 401
    assert (await client.get("/v1/me", headers={"Authorization": "Bearer gm_nope"})).status_code == 401
    t = tid(gm)
    h = await make_agent(client, gm, "tt-alice", t)
    me = (await client.get("/v1/me", headers=h)).json()
    assert me["agent"] == "tt-alice" and set(me["tenants"][t]) == {"read", "write"}
    token = h["Authorization"][7:]
    ctl = gm.db.client.select_graph("ctl")
    stored = (await ctl.query("MATCH (k:ApiKey) RETURN k.hash")).result_set
    assert token not in [r[0] for r in stored]                      # plaintext never stored
    await gm.revoke_keys("tt-alice")
    assert (await client.get("/v1/me", headers=h)).status_code == 401


async def test_admin_plane_protected(client):
    assert (await client.post("/admin/agents", json={"agent": "x"})).status_code == 401
    assert (await client.post("/admin/agents", json={"agent": "x"}, headers={"Authorization": "Bearer wrong"})).status_code == 401


async def test_http_roundtrip_and_isolation(client, gm):
    ta, tb = tid(gm, "a"), tid(gm, "b")
    alice = await make_agent(client, gm, "tt-alice", ta)
    bob = await make_agent(client, gm, "tt-bob", tb)
    r = await client.post(f"/v1/tenants/{ta}/add_episode", json={"session": "s", "role": "user", "content": "hello"}, headers=alice)
    assert r.status_code == 200 and r.json()["result"]["seq"] == 1
    await client.post(f"/v1/tenants/{ta}/assert_fact", json={"subject": "apollo", "predicate": "is", "obj": "bright"}, headers=alice)
    got = (await client.post(f"/v1/tenants/{ta}/recall", json={"query": "apollo"}, headers=alice)).json()["result"]
    assert got[0]["object"] == "bright"
    # bob has no grant on tenant A
    for op, body in (("recall", {"query": "apollo"}), ("history", {"session": "s"}), ("add_episode", {"session": "s", "role": "u", "content": "x"})):
        assert (await client.post(f"/v1/tenants/{ta}/{op}", json=body, headers=bob)).status_code == 403


async def test_read_only_scope_enforced_over_http(client, gm):
    t = tid(gm)
    ro = await make_agent(client, gm, "tt-ro", t, scopes=("read",))
    assert (await client.post(f"/v1/tenants/{t}/history", json={"session": "s"}, headers=ro)).status_code == 200
    assert (await client.post(f"/v1/tenants/{t}/add_episode", json={"session": "s", "role": "u", "content": "x"}, headers=ro)).status_code == 403


async def test_bad_requests_rejected(client, gm):
    t = tid(gm)
    h = await make_agent(client, gm, "tt-a", t)
    assert (await client.post(f"/v1/tenants/{t}/drop_database", json={}, headers=h)).status_code == 404
    assert (await client.post(f"/v1/tenants/{t}/_q", json={}, headers=h)).status_code == 404            # private methods not exposed
    assert (await client.post(f"/v1/tenants/{t}/add_episode", json={"session": "s"}, headers=h)).status_code == 422
    assert (await client.post(f"/v1/tenants/{t}/history", json={"session": "s", "evil": 1}, headers=h)).status_code == 422
    assert (await client.post(f"/v1/tenants/{t}/history", content=b"{not json", headers=h)).status_code == 422
    assert (await client.post("/v1/tenants/BAD TENANT/history", json={"session": "s"}, headers=h)).status_code in (403, 404, 422)
    assert (await client.post(f"/v1/tenants/{t}/resume", json={"task_id": "tsk_missing"}, headers=h)).status_code == 404


async def test_mcp_tools_use_same_authorization(gm):
    t, other = tid(gm, "a"), tid(gm, "b")
    await gm.grant("tt-mcp", t, ("read", "write"))
    await gm.create_tenant(other)
    server = build(gm, "tt-mcp")
    tools = {x.name for x in await server.list_tools()}
    assert {"remember", "recall", "call", "whoami", "list_ops"} <= tools

    async def run(name, **args):
        res = await server.call_tool(name, args)
        text = res.content[0].text if hasattr(res, "content") else res[0].text
        return json.loads(text)

    assert (await run("remember", tenant=t, session="s", role="user", content="mcp works"))["seq"] == 1
    await run("call", tenant=t, op="assert_fact", args_json=json.dumps({"subject": "mcp", "predicate": "is", "obj": "ok"}))
    assert (await run("recall", tenant=t, query="mcp"))[0]["object"] == "ok"
    denied = await run("call", tenant=other, op="history", args_json=json.dumps({"session": "s"}))
    assert "PermissionDenied" in denied["error"]


async def test_spaces_over_http_and_forget_propagates(client, gm):
    ta = tid(gm, "a")
    sp = "tt-sp-" + ta[-6:]
    alice = await make_agent(client, gm, "tt-alice", ta)
    bob = await make_agent(client, gm, "tt-bob")                    # bob has no tenant at all
    for name, scopes in (("tt-alice", ["read", "write"]), ("tt-bob", ["read"])):
        assert (await client.post("/admin/spaces/members", json={"agent": name, "space": sp, "scopes": scopes}, headers=ADMIN)).status_code == 200
    try:
        f = (await client.post(f"/v1/tenants/{ta}/assert_fact", json={"subject": "vendor", "predicate": "price", "obj": "40"}, headers=alice)).json()["result"]
        assert (await client.post(f"/v1/spaces/{sp}/publish", json={"tenant": ta, "fact_ids": [f["id"]]}, headers=alice)).status_code == 200
        got = (await client.post(f"/v1/spaces/{sp}/recall", json={"query": "vendor"}, headers=bob)).json()["result"]
        assert got[0]["object"] == "40"
        assert sp in (await client.get("/v1/me", headers=bob)).json()["spaces"]
        # bob (read-only member) cannot publish, cannot touch the tenant, cannot call tenant-only ops on a space
        assert (await client.post(f"/v1/spaces/{sp}/publish", json={"tenant": ta, "fact_ids": [f["id"]]}, headers=bob)).status_code == 403
        assert (await client.post(f"/v1/tenants/{ta}/recall", json={"query": "vendor"}, headers=bob)).status_code == 403
        assert (await client.post(f"/v1/spaces/{sp}/add_episode", json={}, headers=bob)).status_code == 404
        # forgetting through the generic HTTP op must remove the published copy too
        r = await client.post(f"/v1/tenants/{ta}/forget_fact", json={"fact_id": f["id"], "reason": "gdpr"}, headers=alice)
        assert r.status_code == 200 and r.json()["result"]["space_copies_removed"] == 1
        assert (await client.post(f"/v1/spaces/{sp}/recall", json={"query": "vendor"}, headers=bob)).json()["result"] == []
    finally:
        try:
            await gm.db.client.select_graph(gm.db.space_graph_name(sp)).delete()
        except Exception:
            pass
        await (await gm._ctl()).query("MATCH (n) WHERE n.id STARTS WITH 'tt-' DETACH DELETE n")


async def test_rate_limits(gm):
    app = create_app(gm, admin_key="admin-secret", rate_per_minute=5)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/admin/agents", json={"agent": "tt-rl"}, headers=ADMIN)
        h = {"Authorization": "Bearer " + r.json()["api_key"]}
        codes = [(await c.get("/v1/me", headers=h)).status_code for _ in range(8)]
        assert codes[:5] == [200] * 5 and set(codes[5:]) == {429}
        bad = [(await c.get("/v1/me", headers={"Authorization": "Bearer gm_wrong"})).status_code for _ in range(35)]
        assert bad[0] == 401 and bad[-1] == 429


async def test_branching_over_http(client, gm):
    t = tid(gm)
    h = await make_agent(client, gm, "tt-br", t)
    await client.post(f"/v1/tenants/{t}/assert_fact", json={"subject": "alpha", "predicate": "is", "obj": "one"}, headers=h)
    f = (await client.post(f"/v1/tenants/{t}/forks", json={"label": "x"}, headers=h)).json()["result"]
    try:
        r = await client.post(f"/v1/forks/{f['id']}/assert_fact", json={"subject": "beta", "predicate": "is", "obj": "two"}, headers=h)
        assert r.status_code == 200
        assert (await client.post(f"/v1/tenants/{t}/recall", json={"query": "beta"}, headers=h)).json()["result"] == []
        dry = (await client.post(f"/v1/forks/{f['id']}/merge", json={}, headers=h)).json()["result"]
        assert dry["applied"] is False and dry["would_apply"]["facts"] == 1
        out = (await client.post(f"/v1/forks/{f['id']}/merge", json={"apply": True}, headers=h)).json()["result"]
        assert out["applied"]["facts"] == 1
        assert (await client.post(f"/v1/forks/{f['id']}/merge", json={"apply": True}, headers=h)).status_code == 409
        other = await make_agent(client, gm, "tt-other")                      # no grant on the tenant
        assert (await client.post(f"/v1/tenants/{t}/forks", json={}, headers=other)).status_code == 403
    finally:
        await (await gm._ctl()).query("MATCH (f:Fork) WHERE f.tenant STARTS WITH 'tt-' DETACH DELETE f")
