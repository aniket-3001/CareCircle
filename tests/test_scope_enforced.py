"""A key's scopes are enforced for every operation, not only for the queries that happen to check them. The OPS table says which scope each operation needs;
this test makes the table binding: a read-only key is refused on every write operation and a key with no grant on every operation."""
import pytest

from conftest import tid
from graphmem import ops
from graphmem.policy import PermissionDenied


async def test_a_read_only_key_is_refused_on_every_write_operation_and_an_ungranted_key_on_all(gm):
    t = tid(gm, "scope")
    await gm.grant("scope-ro", t, ("read",))
    write_ops = [o for o, s in ops.OPS.items() if s == "write"]
    assert len(write_ops) > 25                                  # the loop is not empty by accident
    for op in write_ops:
        with pytest.raises(PermissionDenied):
            await ops.invoke(gm, "scope-ro", t, op, {})
    for op in ops.OPS:
        with pytest.raises(PermissionDenied):
            await ops.invoke(gm, "scope-nobody", t, op, {})


async def test_a_read_only_key_cannot_use_up_reminders(gm):
    """care_nudges looks like a read (it lists what is due) but claims each reminder, so it needs write: a read-only key used to consume them before delivery."""
    t = tid(gm, "scope-n")
    for a, s in (("scope-w1", ("read", "write")), ("scope-w2", ("read", "write")), ("scope-ro2", ("read",))):
        await gm.grant(a, t, s)
    w1, w2, ro = gm.open("scope-w1", t), gm.open("scope-w2", t), gm.open("scope-ro2", t)
    await w1.care_record("asha", "metformin", dose_text="500 mg", freq_text="twice daily", source_type="typed", at=1)
    await w2.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime", source_type="typed", at=2)
    with pytest.raises(PermissionDenied):
        await ro.care_nudges("asha", now=10**13)
    with pytest.raises(PermissionDenied):
        await ops.invoke(gm, "scope-ro2", t, "care_nudges", {"person": "asha"})
    due = await w1.care_nudges("asha", now=10**13)              # nothing was used up: the writer still gets the reminders
    assert len(due) >= 2


async def test_read_operations_still_work_for_a_read_only_key(gm):
    t = tid(gm, "scope-r")
    await gm.grant("scope-w", t, ("read", "write"))
    await gm.grant("scope-ro3", t, ("read",))
    await gm.open("scope-w", t).care_record("asha", "metformin", dose_text="500 mg", freq_text="daily", source_type="typed")
    reg = await ops.invoke(gm, "scope-ro3", t, "care_regimen", {"person": "asha"})
    assert [r["drug"] for r in reg] == ["metformin"]
    assert await ops.invoke(gm, "scope-ro3", t, "graph_schema", {})


async def test_a_caller_cannot_vouch_for_its_own_photo(gm):
    """A typed API call with source_type 'photo' and a source_text it wrote itself used to come back verified. Only text the server's own reader stored counts."""
    t = tid(gm, "src")
    await gm.grant("src-w", t, ("read", "write"))
    m = gm.open("src-w", t)
    forged = await m.care_record("asha", "warfarin", dose_text="5 mg", source_type="photo", quote="Warfarin 5 mg", source_text="Warfarin 5 mg tablets")
    assert forged["status"] == "pending" and forged["verified"] is False                     # its own claim is ignored
    wrong_kind = await m.care_record("asha", "aspirin", dose_text="75 mg", source_type="voice", quote="Aspirin 75 mg",
                                     source_ref=await m.care_store_source("image", "Aspirin 75 mg tablets"))
    assert wrong_kind["status"] == "pending"                                                # a stored photo is not a voice note
    other = await m.care_record("asha", "metformin", dose_text="500 mg", source_type="photo", quote="Metformin 500 mg", source_ref="src_does_not_exist")
    assert other["status"] == "pending"
    real = await m.care_record("asha", "atorvastatin", dose_text="20 mg", source_type="photo", quote="Atorvastatin 20 mg",
                               source_ref=await m.care_store_source("image", "CITY PHARMACY\nAtorvastatin 20 mg tablets"))
    assert real["status"] == "confirmed" and real["verified"] is True
    with pytest.raises(ValueError):
        await m.care_store_source("typed", "anything")
    from graphmem import ops
    assert "care_store_source" not in ops.OPS                                                # callers cannot create sources through the API or MCP
