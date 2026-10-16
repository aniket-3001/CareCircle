"""The anonymous demo circles are capped (CC_DEMO_MAX, the oldest goes). Removing one must remove all of it (graph, tenant record, its two carers and their keys),
and the cap must survive a restart, when the in-memory list of circles is gone."""
import asyncio
import time

import httpx
import pytest

from carecircle import demo
from graphmem.api import create_app

ADMIN = {"Authorization": "Bearer admin-secret"}


async def exists(gm, circle):
    ctl = await gm._ctl()
    graph = f"mem__{circle}" in await gm.db.client.list_graphs()
    tenant = (await ctl.query("MATCH (t:Tenant {id:$c}) RETURN count(t)", {"c": circle})).result_set[0][0]
    agents = (await ctl.query("MATCH (a:Agent) WHERE a.id ENDS WITH $s AND (a.id STARTS WITH 'ravi-' OR a.id STARTS WITH 'meena-') RETURN count(a)", {"s": circle[-8:]})).result_set[0][0]
    keys = (await ctl.query("MATCH (a:Agent)-[:HAS_KEY]->(k) WHERE a.id ENDS WITH $s RETURN count(k)", {"s": circle[-8:]})).result_set[0][0]
    return graph, tenant, agents, keys


async def test_forget_removes_a_demo_circle_completely_and_nothing_else(gm):
    a, b = await demo.start(gm), await demo.start(gm)
    outsider = "tt-demo-outsider"
    await gm.grant(outsider, a["circle"], ("read",))                    # an agent of someone else, with a grant of its own on another circle
    await gm.grant(outsider, b["circle"], ("read",))
    try:
        assert await exists(gm, a["circle"]) == (True, 1, 2, 2)
        await demo.forget(gm, a["circle"])
        assert await exists(gm, a["circle"]) == (False, 0, 0, 0)         # graph, tenant, both carers and both keys
        assert await exists(gm, b["circle"]) == (True, 1, 2, 2)          # the other circle untouched
        assert await gm.authenticate(a["keys"]["ravi"]) is None and await gm.authenticate(b["keys"]["ravi"]) is not None
        ctl = await gm._ctl()
        assert (await ctl.query("MATCH (x:Agent {id:$a}) RETURN count(x)", {"a": outsider})).result_set[0][0] == 1       # an agent that is not the demo's own survives
    finally:
        await demo.forget(gm, b["circle"])
        await (await gm._ctl()).query("MATCH (x:Agent {id:$a}) DETACH DELETE x", {"a": outsider})


@pytest.mark.parametrize("name", ["demo-shared", "c-asha-123456", "demo-", "", "demo-short"])
async def test_forget_refuses_anything_that_is_not_an_anonymous_demo_circle(gm, name):
    with pytest.raises(ValueError, match="not an anonymous demo circle"):
        await demo.forget(gm, name)


async def test_the_cap_holds_through_the_api_and_the_dropped_keys_stop_working(gm, monkeypatch):
    monkeypatch.setenv("CC_DEMO_MAX", "2")
    monkeypatch.setenv("CC_DEMO_KEEP_MIN", "0")                         # no protection for recent circles: this test is about the cap itself
    monkeypatch.setenv("CC_DEMO_PER_HOUR", "0")
    app = create_app(gm, admin_key="admin-secret")
    made = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            for _ in range(4):
                made.append((await c.post("/demo/start")).json())
                await asyncio.sleep(0.01)
            gone, kept = made[:2], made[2:]
            for d in gone:
                assert await exists(gm, d["circle"]) == (False, 0, 0, 0)
                assert (await c.post(f"/v1/tenants/{d['circle']}/care_people", json={}, headers={"Authorization": "Bearer " + d["keys"]["ravi"]})).status_code == 401
            for d in kept:
                assert await exists(gm, d["circle"]) == (True, 1, 2, 2)
                assert (await c.post(f"/v1/tenants/{d['circle']}/care_people", json={}, headers={"Authorization": "Bearer " + d["keys"]["ravi"]})).status_code == 200
    finally:
        for d in made:
            if (await exists(gm, d["circle"]))[1]:
                await demo.forget(gm, d["circle"])


async def test_the_cap_survives_a_restart(gm, monkeypatch):
    """Three circles made by an earlier process; a new process (an empty in-memory list) starts with a cap of one: only the newest remains."""
    older = []
    for _ in range(3):
        older.append(await demo.start(gm))
        await asyncio.sleep(0.01)
    monkeypatch.setenv("CC_DEMO_MAX", "1")
    app = create_app(gm, admin_key="admin-secret")
    try:
        async with app.router.lifespan_context(app):                    # the new process starting
            states = [await exists(gm, d["circle"]) for d in older]
            assert states[0] == (False, 0, 0, 0) and states[1] == (False, 0, 0, 0) and states[2] == (True, 1, 2, 2)
            from carecircle.accounts import SHARED_CIRCLE
            assert SHARED_CIRCLE not in await demo.known(gm)            # the shared demo circle is never in the list that gets trimmed
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
                new = (await c.post("/demo/start")).json()              # and the next one pushes the old survivor out in turn
                older.append(new)
                assert await exists(gm, older[2]["circle"]) == (False, 0, 0, 0) and await exists(gm, new["circle"]) == (True, 1, 2, 2)
    finally:
        for d in older:
            if (await exists(gm, d["circle"]))[1]:
                await demo.forget(gm, d["circle"])


async def _start(c, **headers):
    return await c.post("/demo/start", headers=headers)


async def test_one_caller_cannot_flood_the_demo_and_others_are_not_affected(gm, monkeypatch):
    monkeypatch.setenv("CC_DEMO_MAX", "50")
    monkeypatch.setenv("CC_DEMO_PER_HOUR", "2")
    app = create_app(gm, admin_key="admin-secret")
    made = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            for _ in range(2):
                r = await _start(c, **{"x-forwarded-for": "203.0.113.7"})
                assert r.status_code == 200
                made.append(r.json())
            assert (await _start(c, **{"x-forwarded-for": "203.0.113.7"})).status_code == 429       # the third in an hour from the same address
            other = await _start(c, **{"x-forwarded-for": "198.51.100.9"})
            assert other.status_code == 200                                                         # a different caller is fine
            made.append(other.json())
    finally:
        for d in made:
            if (await exists(gm, d["circle"]))[1]:
                await demo.forget(gm, d["circle"])


async def test_a_circle_someone_just_started_is_not_pushed_out_by_the_cap(gm, monkeypatch):
    """Starting demos in a loop used to rotate every other visitor's circle out mid-session. Recent circles are kept; past twice the cap the demo says it is busy."""
    monkeypatch.setenv("CC_DEMO_MAX", "1")
    monkeypatch.setenv("CC_DEMO_KEEP_MIN", "60")
    monkeypatch.setenv("CC_DEMO_PER_HOUR", "0")
    app = create_app(gm, admin_key="admin-secret")
    made = []
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
                for _ in range(2):
                    r = await _start(c)
                    assert r.status_code == 200
                    made.append(r.json())
                for d in made:
                    assert await exists(gm, d["circle"]) == (True, 1, 2, 2)                          # both survive, although the cap is 1
                assert (await _start(c)).status_code == 503                                         # twice the cap, nothing old enough to remove: busy
                for d in made:
                    assert await exists(gm, d["circle"]) == (True, 1, 2, 2)
    finally:
        for d in made:
            if (await exists(gm, d["circle"]))[1]:
                await demo.forget(gm, d["circle"])


def test_the_forwarded_address_is_believed_only_from_a_private_peer():
    from graphmem.api import client_ip

    class Req:
        def __init__(self, peer, fwd=None):
            self.client = type("C", (), {"host": peer})()
            self.headers = {"x-forwarded-for": fwd} if fwd else {}
    assert client_ip(Req("172.18.0.5", "203.0.113.7, 10.0.0.1")) == "203.0.113.7"          # our proxy, on the private network
    assert client_ip(Req("127.0.0.1", "203.0.113.7")) == "203.0.113.7"
    assert client_ip(Req("8.8.8.8", "198.51.100.1")) == "8.8.8.8"                  # a direct caller cannot choose its address
    assert client_ip(Req("8.8.8.8")) == "8.8.8.8"
