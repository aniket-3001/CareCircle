"""B3: adversarial isolation suite. Secrets are planted in tenant A; agents without a grant on A try everything we can think of.
Every attempt must fail (never HTTP 200) and no response body may contain a planted secret."""
import pytest

from conftest import tid
from test_api import ADMIN, client, make_agent  # noqa: F401  (fixtures)

SECRET = "TOPSECRET-7f3a"


async def plant(client, gm):
    ta = tid(gm, "a")
    alice = await make_agent(client, gm, "tt-alice", ta)
    await client.post(f"/v1/tenants/{ta}/add_episode", json={"session": "s", "role": "user", "content": f"launch code {SECRET}"}, headers=alice)
    f = (await client.post(f"/v1/tenants/{ta}/assert_fact", json={"subject": "vault", "predicate": "holds", "obj": SECRET}, headers=alice)).json()["result"]
    await client.post(f"/v1/tenants/{ta}/care_record", json={"person": "mum", "drug": "metformin", "dose_text": SECRET}, headers=alice)
    fk = (await client.post(f"/v1/tenants/{ta}/forks", json={"label": "a-fork"}, headers=alice)).json()["result"]
    return ta, alice, f["id"], fk["id"]


async def test_no_op_leaks_to_agent_without_grant(client, gm):
    ta, alice, fact_id, fork_id = await plant(client, gm)
    tb = tid(gm, "b")
    bob = await make_agent(client, gm, "tt-bob", tb)
    attempts = [
        ("POST", f"/v1/tenants/{ta}/recall", {"query": "vault"}), ("POST", f"/v1/tenants/{ta}/history", {"session": "s"}),
        ("POST", f"/v1/tenants/{ta}/search_episodes", {"query": "launch code"}), ("POST", f"/v1/tenants/{ta}/graph_view", {}),
        ("POST", f"/v1/tenants/{ta}/fact_history", {"subject": "vault", "predicate": "holds"}),
        ("POST", f"/v1/tenants/{ta}/explain", {"decision_id": "dec_x"}), ("POST", f"/v1/tenants/{ta}/care_regimen", {"person": "mum"}),
        ("POST", f"/v1/tenants/{ta}/care_check", {"person": "mum"}), ("POST", f"/v1/tenants/{ta}/care_divergence", {"person": "mum"}),
        ("POST", f"/v1/tenants/{ta}/care_people", {}), ("POST", f"/v1/tenants/{ta}/care_give", {"person": "mum", "drug": "metformin", "slot": "s"}),
        ("POST", f"/v1/tenants/{ta}/intake", {}),
        ("POST", f"/v1/tenants/{ta}/forget_fact", {"fact_id": fact_id, "reason": "x"}),
        ("POST", f"/v1/tenants/{ta}/forks", {}), ("GET", f"/v1/tenants/{ta}/forks", None),
        ("POST", f"/v1/forks/{fork_id}/recall", {"query": "vault"}), ("POST", f"/v1/forks/{fork_id}/graph_view", {}),
        ("POST", f"/v1/forks/{fork_id}/merge", {"apply": True}), ("DELETE", f"/v1/forks/{fork_id}", None),
        ("POST", f"/v1/spaces/{ta}/recall", {"query": "vault"}), ("POST", "/v1/spaces/nospace/recall", {"query": "vault"}),
        ("POST", "/v1/spaces/open/publish", {"tenant": ta, "fact_ids": [fact_id]}),
    ]
    for method, url, body in attempts:
        r = await client.request(method, url, json=body, headers=bob)
        assert r.status_code != 200, (url, r.text)
        assert SECRET not in r.text, (url, r.text)
    # the data is intact for its owner
    assert (await client.post(f"/v1/tenants/{ta}/recall", json={"query": "vault"}, headers=alice)).json()["result"][0]["object"] == SECRET


async def test_forged_and_malformed_credentials(client, gm):
    ta, alice, *_ = await plant(client, gm)
    for h in ({}, {"Authorization": ""}, {"Authorization": "Bearer "}, {"Authorization": "Bearer gm_"}, {"Authorization": "Basic Zm9vOmJhcg=="},
              {"Authorization": "Bearer " + "gm_" + "0" * 40}, {"Authorization": "Bearer ' OR 1=1 --"},
              {"Authorization": alice["Authorization"].replace("Bearer ", "bearer x")}, {"X-Agent": "tt-alice"}):
        r = await client.post(f"/v1/tenants/{ta}/recall", json={"query": "vault"}, headers=h)
        assert r.status_code in (401, 429) and SECRET not in r.text
    r = await client.post("/admin/grants", json={"agent": "tt-alice", "tenant": "x"}, headers=alice)   # an agent key is not an admin key
    assert r.status_code == 401


async def test_hostile_tenant_ids_never_reach_the_database(client, gm):
    ta, alice, *_ = await plant(client, gm)
    for bad in ("..", "mem__" + ta, "ctl", "shared__x", "a b", "A" * 60, "x`;MATCH(n)DETACH DELETE n//", "%2e%2e", ta + "%2F..%2F" + ta):
        r = await client.post(f"/v1/tenants/{bad}/recall", json={"query": "vault"}, headers=alice)
        assert r.status_code in (403, 404, 405, 422), (bad, r.status_code)
        assert SECRET not in r.text
    # ctl exists as a graph but is never addressable through the API
    ctl_nodes = (await gm.db.client.select_graph("ctl").query("MATCH (n) RETURN count(n)")).result_set[0][0]
    assert ctl_nodes > 0


async def test_injection_strings_are_data_not_cypher(client, gm):
    ta, alice, *_ = await plant(client, gm)
    evil = "x' }) MATCH (n) DETACH DELETE n //"
    r = await client.post(f"/v1/tenants/{ta}/assert_fact", json={"subject": evil, "predicate": "is", "obj": '" OR 1=1 //'}, headers=alice)
    assert r.status_code == 200
    r = await client.post(f"/v1/tenants/{ta}/add_episode", json={"session": evil, "role": "user", "content": "}) DETACH DELETE (n"}, headers=alice)
    assert r.status_code == 200
    assert (await client.post(f"/v1/tenants/{ta}/recall", json={"query": "vault"}, headers=alice)).json()["result"][0]["object"] == SECRET


async def test_revocation_is_immediate_and_forks_do_not_outlive_it(client, gm):
    ta, alice, fact_id, fork_id = await plant(client, gm)
    carol = await make_agent(client, gm, "tt-carol", ta)
    assert (await client.post(f"/v1/forks/{fork_id}/recall", json={"query": "vault"}, headers=carol)).status_code == 200
    assert (await client.delete(f"/admin/grants/tt-carol/{ta}", headers=ADMIN)).status_code == 200
    for url, body in ((f"/v1/tenants/{ta}/recall", {"query": "vault"}), (f"/v1/forks/{fork_id}/recall", {"query": "vault"})):
        r = await client.post(url, json=body, headers=carol)
        assert r.status_code == 403 and SECRET not in r.text


async def test_space_publish_cannot_move_foreign_facts(client, gm):
    ta, alice, fact_id, _ = await plant(client, gm)
    tb = tid(gm, "b")
    bob = await make_agent(client, gm, "tt-bob", tb)
    sp = tid(gm, "sp")
    await client.post("/admin/spaces/members", json={"agent": "tt-bob", "space": sp, "scopes": ["read", "write"]}, headers=ADMIN)
    r = await client.post(f"/v1/spaces/{sp}/publish", json={"tenant": tb, "fact_ids": [fact_id]}, headers=bob)   # A's fact id, B's own tenant
    assert r.status_code == 200 and SECRET not in r.text
    got = await client.post(f"/v1/spaces/{sp}/recall", json={"query": "vault"}, headers=bob)
    assert SECRET not in got.text
    await gm.db.client.select_graph(gm.db.space_graph_name(sp)).delete()
