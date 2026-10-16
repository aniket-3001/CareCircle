"""Erasing an entry for good is the owner's call; any carer can mark an entry as entered by mistake, which keeps it in the history and can be undone."""
import pytest

from conftest import tid
from graphmem.policy import PermissionDenied


async def circle(gm):
    t = tid(gm, "mk")
    await gm.grant("owner-mk", t, ("read", "write", "admin"))
    for c in ("carer-a", "carer-b"):
        await gm.grant(c, t, ("read", "write"))
    return t, gm.open("owner-mk", t), gm.open("carer-a", t), gm.open("carer-b", t)


async def regimen(m):
    return {r["drug"]: r["dose_text"] for r in await m.care_regimen("asha")}


async def test_only_the_owner_can_erase_an_entry_for_good(gm):
    t, owner, a, b = await circle(gm)
    e = await a.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed")
    with pytest.raises(PermissionDenied):
        await b.care_forget(e["id"], reason="not mine")
    with pytest.raises(PermissionDenied):
        await b.care_forget_person("asha", confirm="asha")
    assert (await regimen(b)) == {"warfarin": "5 mg"}                       # nothing was erased
    out = await owner.care_forget(e["id"], reason="entered twice")
    assert out["forgotten"] and await regimen(owner) == {}


async def test_a_carer_marks_an_entry_as_a_mistake_and_the_history_keeps_it(gm):
    t, owner, a, b = await circle(gm)
    first = await a.care_record("asha", "warfarin", dose_text="4 mg", freq_text="bedtime", source_type="typed", at=1_000_000)
    typo = await a.care_record("asha", "warfarin", dose_text="40 mg", freq_text="bedtime", source_type="typed", at=2_000_000)
    assert await regimen(b) == {"warfarin": "40 mg"}
    out = await b.care_mark_mistake(typo["id"], reason="should have been 4")             # a carer who did not write it
    assert out["status"] == "mistake"
    assert await regimen(b) == {"warfarin": "4 mg"}                                    # the earlier entry stands again
    tl = " | ".join(e["text"] for e in await b.care_timeline("asha"))
    assert "40 mg" in tl and "marked as entered by mistake" in tl and "should have been 4" in tl      # nothing is hidden or rewritten
    assert first["id"] != typo["id"]
    with pytest.raises(KeyError):
        await b.care_mark_mistake(typo["id"])                                              # already marked
    with pytest.raises(KeyError):
        await b.care_mark_mistake("dose_nope")


async def test_a_mark_can_be_undone_by_whoever_made_it_or_the_owner_but_not_by_another_carer(gm):
    t, owner, a, b = await circle(gm)
    e = await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily", source_type="typed")
    await a.care_mark_mistake(e["id"])
    assert await regimen(a) == {}
    with pytest.raises(PermissionDenied):
        await b.care_restore_entry(e["id"])                                                # a third carer cannot override
    await a.care_restore_entry(e["id"])                                                   # the one who marked it can
    assert await regimen(a) == {"metformin": "500 mg"}
    await b.care_mark_mistake(e["id"])
    await owner.care_restore_entry(e["id"])                                               # the owner can undo anyone's mark
    assert await regimen(a) == {"metformin": "500 mg"}
    assert "mistake" not in " ".join(x["text"] for x in await a.care_timeline("asha"))     # restored: the history no longer calls it one
