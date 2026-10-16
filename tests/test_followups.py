"""Follow-ups: suggested from the record, written only when a person approves, and marked stale when the entry they rest on changes."""
import pytest

from conftest import tid


async def _two(gm, name):
    t = tid(gm, name)
    for c in ("ravi", "meena"):
        await gm.grant(c, t, ("read", "write", "admin"))
    return gm.open("ravi", t), gm.open("meena", t)


async def test_suggest_then_approve_then_done(gm):
    ravi, meena = await _two(gm, "fu")
    first = await ravi.care_record("asha", "clarithromycin", dose_text="500 mg", freq_text="twice daily")
    await meena.care_ack(first["id"])                                           # meena is now in the circle, and has seen only this one
    await ravi.care_record("asha", "atorvastatin", dose_text="20 mg", freq_text="at night")
    sug = await ravi.care_followup_suggest("asha")
    kinds = {s["key"].split("|")[0] for s in sug}
    assert {"pair", "new", "unseen"} <= kinds                                   # a flagged pair, a recent change, a carer who has not seen it
    assert all(s["text"].split()[0] in ("Ask", "Tell", "Make") for s in sug)     # asks and tells, never what to take
    assert await ravi.care_followups("asha") == []                               # suggesting wrote nothing

    pick = [s for s in sug if s["key"].startswith(("pair|", "new|clarithromycin"))]
    r = await ravi.care_followup_add("asha", pick)
    assert len(r["added"]) == len(pick) and r["skipped"] == 0
    assert (await ravi.care_followup_add("asha", pick))["added"] == []           # the same key is not added twice
    assert {s["key"] for s in await ravi.care_followup_suggest("asha")}.isdisjoint({p["key"] for p in pick})

    lst = await meena.care_followups("asha")                                     # the other carer sees it
    assert len(lst) == len(pick) and not any(x["stale"] for x in lst) and all(x["status"] == "open" for x in lst)
    await meena.care_followup_done(lst[0]["id"])
    after = await ravi.care_followups("asha")
    assert after[-1]["status"] == "done" and after[-1]["done_by"] == "meena"
    with pytest.raises(KeyError):
        await ravi.care_followup_done(lst[0]["id"])                              # already done


async def test_follow_up_goes_stale_when_its_entry_changes(gm):
    ravi, _ = await _two(gm, "fs")
    await ravi.care_record("asha", "clarithromycin", dose_text="500 mg", freq_text="twice daily")
    await ravi.care_record("asha", "atorvastatin", dose_text="20 mg", freq_text="at night")
    pair = next(s for s in await ravi.care_followup_suggest("asha") if s["key"].startswith("pair|"))
    await ravi.care_followup_add("asha", [pair])
    assert not (await ravi.care_followups("asha"))[0]["stale"]
    await ravi.care_record("asha", "clarithromycin", action="stop")              # the entry it was written from is closed
    assert (await ravi.care_followups("asha"))[0]["stale"]


async def test_followups_are_erased_with_the_person_and_validated(gm):
    ravi, _ = await _two(gm, "fe")
    await ravi.care_record("asha", "warfarin", dose_text="4 mg")
    with pytest.raises(ValueError):
        await ravi.care_followup_add("asha", [{"key": "x", "text": "  "}])
    with pytest.raises(ValueError):
        await ravi.care_followup_add("asha", [])
    await ravi.care_followup_add("asha", [{"key": "own|1", "text": "Ask the GP about the INR", "kind": "prescriber"}])
    assert len(await ravi.care_followups("asha")) == 1
    await ravi.care_forget_person("asha", confirm="asha")
    assert await ravi.care_followups("asha") == []
