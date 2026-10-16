"""The MCP server over HTTP (POST /mcp): who may call it, that callers can never see each other, that scopes and limits hold, and that a real MCP client
can use it over a real socket."""
import asyncio
import contextlib
import functools
import json
import socket
import threading
import time

import httpx
import pytest
import pytest_asyncio

from conftest import tid
from graphmem.api import create_app

ADMIN = {"Authorization": "Bearer admin-secret"}
ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, **({"params": params} if params is not None else {})}


@contextlib.asynccontextmanager
async def running(gm, **kw):
    """The app with its startup and shutdown run, and a client for it. Entered and left in one task (the MCP session manager requires that)."""
    app = create_app(gm, admin_key="admin-secret", **{"rate_per_minute": 100000, **kw})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield app, c


def with_stack(fn):
    @functools.wraps(fn, assigned=("__name__", "__qualname__", "__doc__", "__module__"))
    async def wrapper(gm):
        async with running(gm) as (app, c):
            await fn((app, c), gm)
    del wrapper.__wrapped__                # pytest must see the wrapper's own signature (gm), not the test's
    return wrapper


async def agent(c, name, tenant=None, scopes=("read", "write")):
    r = await c.post("/admin/agents", json={"agent": name}, headers=ADMIN)
    assert r.status_code == 200
    if tenant:
        assert (await c.post("/admin/grants", json={"agent": name, "tenant": tenant, "scopes": list(scopes)}, headers=ADMIN)).status_code == 200
    return {"Authorization": "Bearer " + r.json()["api_key"], **ACCEPT}


async def tool(c, h, name, args, id=1):
    r = await c.post("/mcp", headers=h, json=rpc("tools/call", {"name": name, "arguments": args}, id))
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return json.loads(res["content"][0]["text"]), res.get("isError")


@with_stack
async def test_a_key_is_required_and_a_wrong_one_is_refused(stack, gm):
    app, c = stack
    none = await c.post("/mcp", headers=ACCEPT, json=rpc("tools/list"))
    assert none.status_code == 401 and none.headers["www-authenticate"].startswith("Bearer")
    wrong = await c.post("/mcp", headers={**ACCEPT, "Authorization": "Bearer gm_wrong"}, json=rpc("tools/list"))
    assert wrong.status_code == 401 and "invalid api key" in wrong.text
    notbearer = await c.post("/mcp", headers={**ACCEPT, "Authorization": "Basic abc"}, json=rpc("tools/list"))
    assert notbearer.status_code == 401
    assert (await c.get("/healthz")).status_code == 200                           # the rest of the server is untouched


@with_stack
async def test_the_tools_are_listed_and_whoami_names_the_key_holder(stack, gm):
    app, c = stack
    t = tid(gm, "mh")
    h = await agent(c, "tt-mh-a", t, ("read",))
    r = await c.post("/mcp", headers=h, json=rpc("tools/list"))
    names = {x["name"] for x in r.json()["result"]["tools"]}
    assert {"whoami", "call", "list_ops", "recall", "remember", "fork_memory"} <= names
    me, err = await tool(c, h, "whoami", {})
    assert me == {"agent": "tt-mh-a", "tenants": {t: ["read"]}} and not err
    ops, _ = await tool(c, h, "list_ops", {})
    assert "graph_path" in ops and "graph_influence" in ops


@with_stack
async def test_two_callers_at_once_never_see_each_other(stack, gm):
    """The caller is held per request. Forty interleaved calls from two keys: every answer is about the caller's own tenant, and the other's is refused."""
    app, c = stack
    ta, tb = tid(gm, "mh-a"), tid(gm, "mh-b")
    ha, hb = await agent(c, "tt-mh-ann", ta), await agent(c, "tt-mh-bob", tb)
    await tool(c, ha, "remember", {"tenant": ta, "session": "s", "role": "user", "content": "only ann knows the vault code"})
    await tool(c, hb, "remember", {"tenant": tb, "session": "s", "role": "user", "content": "only bob knows the garage code"})

    async def one(i):
        h, own, other = (ha, ta, tb) if i % 2 == 0 else (hb, tb, ta)
        who, _ = await tool(c, h, "whoami", {}, id=i)
        hist, _ = await tool(c, h, "call", {"tenant": own, "op": "history", "args_json": '{"session": "s"}'}, id=i)
        denied, _ = await tool(c, h, "call", {"tenant": other, "op": "history", "args_json": '{"session": "s"}'}, id=i)
        return i % 2, who["agent"], json.dumps(hist), json.dumps(denied)

    for kind, who, hist, denied in await asyncio.gather(*[one(i) for i in range(40)]):
        assert who == ("tt-mh-ann" if kind == 0 else "tt-mh-bob")
        assert ("vault" in hist) == (kind == 0) and ("garage" in hist) == (kind == 1)
        assert "error" in denied and "vault" not in denied and "garage" not in denied


@with_stack
async def test_scopes_hold_a_read_only_key_cannot_write_and_graph_ops_work(stack, gm):
    app, c = stack
    t = tid(gm, "mh-scope")
    w = await agent(c, "tt-mh-w", t)
    r = await agent(c, "tt-mh-r", t, ("read",))
    await tool(c, w, "call", {"tenant": t, "op": "assert_fact", "args_json": json.dumps({"subject": "ann", "predicate": "likes", "obj": "tea"})})
    refused, _ = await tool(c, r, "call", {"tenant": t, "op": "assert_fact", "args_json": json.dumps({"subject": "ann", "predicate": "likes", "obj": "coffee"})})
    assert "error" in refused and "PermissionDenied" in refused["error"]
    net, _ = await tool(c, r, "call", {"tenant": t, "op": "graph_schema", "args_json": "{}"})
    assert any(n["label"] == "Fact" for n in net["nodes"])
    infl, _ = await tool(c, r, "call", {"tenant": t, "op": "graph_influence", "args_json": '{"top": 3}'})
    assert infl["rows"] and "algo.pageRank" in infl["cypher"]
    assert (await tool(c, w, "call", {"tenant": t, "op": "recall", "args_json": '{"query": "tea"}'}))[0][0]["object"] == "tea"


@with_stack
async def test_bad_arguments_come_back_as_a_tool_error_not_a_crash(stack, gm):
    app, c = stack
    t = tid(gm, "mh-bad")
    h = await agent(c, "tt-mh-bad", t)
    out, _ = await tool(c, h, "call", {"tenant": t, "op": "graph_influence", "args_json": '{"metric": "degree"}'})
    assert "pagerank" in out["error"]
    out, _ = await tool(c, h, "call", {"tenant": t, "op": "no_such_op", "args_json": "{}"})
    assert "unknown operation" in out["error"]
    out, _ = await tool(c, h, "call", {"tenant": t, "op": "history", "args_json": "{not json"})
    assert "error" in out
    junk = await c.post("/mcp", headers=h, content=b"{this is not json")
    assert junk.status_code in (400, 422) or junk.json().get("error")


async def test_the_same_limits_as_the_rest_api_apply(gm):
    async with running(gm, rate_per_minute=3) as (app, c):
        if True:
            h = await agent(c, "tt-mh-rate")
            codes = [(await c.post("/mcp", headers=h, json=rpc("tools/list", id=i))).status_code for i in range(6)]
            assert codes[:3] == [200, 200, 200] and 429 in codes[3:]
            for i in range(35):                                                     # a flood of wrong keys from one address is slowed too
                await c.post("/mcp", headers={**ACCEPT, "Authorization": "Bearer gm_bad"}, json=rpc("tools/list"))
            assert (await c.post("/mcp", headers={**ACCEPT, "Authorization": "Bearer gm_bad"}, json=rpc("tools/list"))).status_code == 429


@with_stack
async def test_a_request_for_some_other_host_is_refused(stack, gm):
    app, c = stack
    h = await agent(c, "tt-mh-host")
    r = await c.post("/mcp", headers={**h, "Host": "evil.example"}, json=rpc("tools/list"))
    assert r.status_code in (400, 403, 421) and "result" not in r.text


async def test_it_can_be_switched_off(gm, monkeypatch):
    monkeypatch.setenv("CC_MCP_HTTP", "0")
    app = create_app(gm, admin_key="admin-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        h = await agent(c, "tt-mh-off")
        r = await c.post("/mcp", headers=h, json=rpc("tools/list"))
        assert r.status_code != 200 and "tools" not in r.text


async def test_no_caller_no_tools():
    """A tool that somehow runs outside an authenticated request refuses instead of guessing who is asking."""
    from graphmem import mcp_http
    with pytest.raises(PermissionError):
        mcp_http._who()


# ------------------------------------------------------------------ a real MCP client over a real socket
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_a_real_mcp_client_connects_over_a_real_socket(gm):
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    t = tid(gm, "mh-real")
    app = create_app(None, admin_key="admin-secret", rate_per_minute=100000)         # its own database client, made in the server's own event loop
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.1)
        assert server.started
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as admin:
            key = (await admin.post("/admin/agents", json={"agent": "tt-mh-real"}, headers=ADMIN)).json()["api_key"]
            await admin.post("/admin/grants", json={"agent": "tt-mh-real", "tenant": t, "scopes": ["read", "write"]}, headers=ADMIN)
        http = create_mcp_http_client(headers={"Authorization": "Bearer " + key})
        async with streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert {"whoami", "call", "recall", "remember"} <= {x.name for x in listed.tools}
                who = await session.call_tool("whoami", {})
                assert json.loads(who.content[0].text)["agent"] == "tt-mh-real"
                await session.call_tool("remember", {"tenant": t, "session": "s", "role": "user", "content": "the ferry leaves at nine"})
                got = await session.call_tool("recall", {"tenant": t, "query": "ferry"})
                assert "ferry" in got.content[0].text or got.content[0].text == "[]"
                hist = await session.call_tool("call", {"tenant": t, "op": "history", "args_json": '{"session": "s"}'})
                assert "ferry leaves at nine" in hist.content[0].text
                path = await session.call_tool("call", {"tenant": t, "op": "graph_schema", "args_json": "{}"})
                assert "Episode" in path.content[0].text
        bad = create_mcp_http_client(headers={"Authorization": "Bearer gm_wrong"})
        with pytest.raises(BaseException):
            async with streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=bad) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await asyncio.wait_for(session.initialize(), 10)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@with_stack
async def test_a_signed_in_persons_session_works_as_the_key_and_reaches_only_their_circles(stack, gm):
    app, c = stack
    PW = "correct-horse1"
    toks = {}
    for who in ("olive", "omar"):
        r = await c.post("/v1/auth/signup", json={"email": f"{who}-mcp@tt.test", "password": PW, "name": who.title()})
        assert r.status_code == 200, r.text
        toks[who] = r.json()["token"]
    mine = (await c.post("/v1/account/circles", json={"name": "Olive's family", "person": "Asha"}, headers={"Authorization": "Bearer " + toks["olive"]})).json()["id"]
    theirs = (await c.post("/v1/account/circles", json={"name": "Omar's family", "person": "Bela"}, headers={"Authorization": "Bearer " + toks["omar"]})).json()["id"]
    h = {"Authorization": "Bearer " + toks["olive"], **ACCEPT}
    me, _ = await tool(c, h, "whoami", {})
    assert list(me["tenants"]) == [mine]
    people, _ = await tool(c, h, "call", {"tenant": mine, "op": "care_people", "args_json": "{}"})
    assert people["patients"] == ["asha"]
    net, _ = await tool(c, h, "call", {"tenant": mine, "op": "graph_schema", "args_json": "{}"})
    assert any(n["label"] == "Person" for n in net["nodes"])
    other, _ = await tool(c, h, "call", {"tenant": theirs, "op": "care_people", "args_json": "{}"})
    assert list(other) == ["error"] and other["error"].startswith("PermissionDenied")          # a refusal that echoes the id the caller typed, and nothing else
