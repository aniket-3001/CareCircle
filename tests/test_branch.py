import asyncio

import pytest

from graphmem import PermissionDenied, branch
from conftest import tid


async def world(gm):
    t = tid(gm)
    await gm.grant("tt-a", t)
    await gm.grant("tt-b", t)
    return t, gm.open("tt-a", t), gm.open("tt-b", t)


async def cleanup(gm, *fork_ids):
    for f in fork_ids:
        try:
            await branch.discard(gm, "tt-a", f)
        except Exception:
            pass
    await (await gm._ctl()).query("MATCH (f:Fork) WHERE f.tenant STARTS WITH 'tt-' DETACH DELETE f")


async def test_fork_isolated_and_clean_merge(gm):
    t, a, _ = await world(gm)
    await a.assert_fact("base", "fact", "one")
    f = await branch.fork(gm, "tt-a", t, "try-things")
    try:
        fm = await branch.open_fork(gm, "tt-a", f["id"])
        await fm.add_episode("s", "agent", "explored in the fork")
        await fm.assert_fact("fork", "finding", "interesting")
        assert await a.recall("fork") == []                       # tenant graph untouched
        assert (await fm.recall("base"))[0]["object"] == "one"       # fork sees the snapshot
        dry = await branch.merge(gm, "tt-a", f["id"])
        assert dry["applied"] is False and dry["would_apply"]["episodes"] == 1 and dry["would_apply"]["facts"] == 1
        assert dry["conflicts"] == [] and await a.recall("fork") == []   # dry run changed nothing
        out = await branch.merge(gm, "tt-a", f["id"], apply=True)
        assert out["applied"]["facts"] == 1 and out["applied"]["episodes"] == 1
        assert (await a.recall("fork"))[0]["object"] == "interesting"
        assert (await a.history("s"))[0]["content"] == "explored in the fork"
        with pytest.raises(branch.ForkError):                         # merged forks cannot be merged again
            await branch.merge(gm, "tt-a", f["id"], apply=True)
    finally:
        await cleanup(gm, f["id"])


async def test_conflict_detected_skip_and_overwrite(gm):
    t, a, b = await world(gm)
    await a.assert_fact("deadline", "is", "friday", exclusive=True)
    f1, f2 = await branch.fork(gm, "tt-a", t), await branch.fork(gm, "tt-a", t)
    try:
        for f in (f1, f2):
            fm = await branch.open_fork(gm, "tt-a", f["id"])
            await fm.assert_fact("deadline", "is", "thursday", exclusive=True)
        await asyncio.sleep(0.01)
        await b.assert_fact("deadline", "is", "wednesday", exclusive=True)        # tenant changes after the snapshot
        dry = await branch.merge(gm, "tt-a", f1["id"])
        assert len(dry["conflicts"]) == 1 and dry["conflicts"][0]["fork_value"] == "thursday" and dry["conflicts"][0]["tenant_value"] == "wednesday"
        out = await branch.merge(gm, "tt-a", f1["id"], apply=True)                 # default: skip, tenant value wins
        assert out["applied"]["facts"] == 0
        assert [x["object"] for x in await a.recall("deadline")] == ["wednesday"]
        out2 = await branch.merge(gm, "tt-a", f2["id"], apply=True, on_conflict="overwrite")
        assert out2["applied"]["facts"] == 1
        assert [x["object"] for x in await a.recall("deadline")] == ["thursday"]
        h = [x["value"] for x in await a.fact_history("deadline", "is")]
        assert h == ["friday", "wednesday", "thursday"]                           # nothing was silently lost
    finally:
        await cleanup(gm, f1["id"], f2["id"])


async def test_stale_plan_reported_at_merge(gm):
    t, a, b = await world(gm)
    base = await a.assert_fact("api", "limit", "100", exclusive=True)
    f = await branch.fork(gm, "tt-a", t)
    try:
        fm = await branch.open_fork(gm, "tt-a", f["id"])
        task = await fm.create_task("tune")
        await fm.create_plan(task, ["use limit"], derived_from=[base["id"]])
        await asyncio.sleep(0.01)
        await b.assert_fact("api", "limit", "20", exclusive=True)                 # input changes after the fork was taken
        dry = await branch.merge(gm, "tt-a", f["id"])
        assert len(dry["needs_rebase"]) == 1 and "100" in dry["needs_rebase"][0]["outdated_inputs"][0]["text"]
        out = await branch.merge(gm, "tt-a", f["id"], apply=True)
        assert out["applied"]["plans"] == 1 and len(out["plans_stale_after_merge"]) == 1   # merged but flagged, then rebase fixes it
        pid = (await a._q("MATCH (p:Plan) RETURN p.id", scope="read"))[0][0]
        rb = await a.rebase_plan(pid)
        assert (await a.check_plan(rb["plan"]))["stale"] is False
    finally:
        await cleanup(gm, f["id"])


async def test_permissions_limits_discard(gm, monkeypatch):
    t, a, _ = await world(gm)
    await gm.grant("tt-ro", t, ("read",))
    f = await branch.fork(gm, "tt-ro", t)                                          # read scope may fork
    try:
        with pytest.raises(PermissionDenied):
            await branch.merge(gm, "tt-ro", f["id"], apply=True)                   # but not merge
        with pytest.raises(PermissionDenied):
            await branch.fork(gm, "tt-nobody", t)
        monkeypatch.setattr(branch, "MAX_OPEN_FORKS", 1)
        with pytest.raises(branch.ForkError):
            await branch.fork(gm, "tt-a", t)
        await branch.discard(gm, "tt-a", f["id"])
        with pytest.raises(branch.ForkError):
            await branch.open_fork(gm, "tt-a", f["id"])
        assert f["graph"] not in await gm.db.client.list_graphs()
        monkeypatch.setattr(branch, "MAX_FORK_NODES", 0)
        await a.assert_fact("x1y", "is", "z1y")
        with pytest.raises(branch.ForkError):
            await branch.fork(gm, "tt-a", t)
    finally:
        await cleanup(gm, f["id"])
