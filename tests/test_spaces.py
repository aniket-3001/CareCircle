import pytest

from graphmem import PermissionDenied
from graphmem import spaces
from conftest import tid


async def test_publish_read_and_boundaries(gm):
    ta, tb = tid(gm, "a"), tid(gm, "b")
    sp = "tt-space-" + ta[-6:]
    await gm.grant("tt-alice", ta, ("read", "write"))
    await gm.grant("tt-bob", tb, ("read", "write"))
    await spaces.add_member(gm, "tt-alice", sp, ("read", "write"))
    await spaces.add_member(gm, "tt-bob", sp, ("read",))
    try:
        a = gm.open("tt-alice", ta)
        ep = await a.add_episode("s", "user", "private chat: the vendor price is 40")
        pub = await a.assert_fact("vendor", "price", "40", sources=[ep["id"]])
        priv = await a.assert_fact("alice", "salary", "999")
        res = await spaces.publish(gm, "tt-alice", ta, sp, [pub["id"]])
        assert res["published"] == [pub["id"]]

        view = spaces.open_space(gm, "tt-bob", sp)
        got = await view.recall("vendor")
        assert got[0]["object"] == "40" and got[0]["provenance"] == []     # no source episode text crosses over
        assert await view.recall("salary") == []                           # unpublished fact stays private
        # bob, a space member, still has no access to alice's tenant
        with pytest.raises(PermissionDenied):
            await gm.open("tt-bob", ta).recall("vendor")
        # read-only member cannot publish; non-member cannot read
        await gm.grant("tt-bob", tb, ("read", "write"))
        bf = await gm.open("tt-bob", tb).assert_fact("x1", "is", "y1")
        with pytest.raises(PermissionDenied):
            await spaces.publish(gm, "tt-bob", tb, sp, [bf["id"]])
        with pytest.raises(PermissionDenied):
            await spaces.open_space(gm, "tt-nobody", sp).recall("vendor")
        # cannot publish from a tenant you cannot read
        with pytest.raises(PermissionDenied):
            await spaces.publish(gm, "tt-alice", tb, sp, [bf["id"]])
    finally:
        await gm.db.drop_tenant(sp.replace("shared__", ""))   # no-op; space graph removed below
        try:
            await gm.db.client.select_graph(gm.db.space_graph_name(sp)).delete()
        except Exception:
            pass
        await (await gm._ctl()).query("MATCH (n) WHERE n.id STARTS WITH 'tt-' DETACH DELETE n")


async def test_supersede_and_forget_propagate_to_space(gm):
    ta = tid(gm, "a")
    sp = "tt-space-" + ta[-6:]
    await gm.grant("tt-alice", ta, ("read", "write"))
    await spaces.add_member(gm, "tt-alice", sp, ("read", "write"))
    try:
        a = gm.open("tt-alice", ta)
        f1 = await a.assert_fact("deadline", "is", "friday", exclusive=True, at=1_000)
        await spaces.publish(gm, "tt-alice", ta, sp, [f1["id"]])
        f2 = await a.assert_fact("deadline", "is", "wednesday", exclusive=True, at=2_000)
        await spaces.publish(gm, "tt-alice", ta, sp, [f1["id"], f2["id"]])      # re-publish refreshes validity
        view = spaces.open_space(gm, "tt-alice", sp)
        assert [r["object"] for r in await view.recall("deadline")] == ["wednesday"]
        assert [h["value"] for h in await view.fact_history("deadline", "is")] == ["friday", "wednesday"]
        # forgetting in the tenant removes the shared copy too
        out = await spaces.forget_fact(gm, "tt-alice", ta, f2["id"], "requested")
        assert out["space_copies_removed"] == 1
        assert [r["object"] for r in await view.recall("deadline")] == []
        sg = await gm.db.graph(gm.db.space_graph_name(sp))
        raw = (await sg.query("MATCH (n) WHERE any(k IN keys(n) WHERE toString(n[k]) CONTAINS 'wednesday') "
                              "RETURN count(n)")).result_set
        assert raw[0][0] == 0
    finally:
        try:
            await gm.db.client.select_graph(gm.db.space_graph_name(sp)).delete()
        except Exception:
            pass
        await (await gm._ctl()).query("MATCH (n) WHERE n.id STARTS WITH 'tt-' DETACH DELETE n")
