"""Ticking one tablet of a combination is one claim: every ingredient or none, and exactly one winner. These reproduce the review's B3 and B4 (found on the live
site): a refusal that still wrote half the tablet, and two carers ticking at once splitting a tablet between them or both being refused."""
import asyncio
from datetime import date

import pytest

from conftest import tid
from carecircle import schedule as s
from carecircle.safety import scan_advice

IST = "Asia/Kolkata"
DAY = date(2026, 9, 20)


def at(hhmm):
    return s.slot_moment_ms(DAY, hhmm, IST)


async def circle(gm):
    t = tid(gm, "tk")
    for a in ("tk-a", "tk-b"):
        await gm.grant(a, t, ("read", "write", "admin"))
    a = gm.open("tk-a", t)
    await a.care_set_timezone(IST)
    return t, a, gm.open("tk-b", t)


async def glycomet_and_metformin(a, times=("08:00",)):
    plain = (await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="once daily", at=at("00:00") - 86_400_000))["id"]
    ids = [(await a.care_record("asha", i, freq_text="once daily", product="Glycomet-GP", product_strength="500/1 mg", at=at("00:00") - 86_400_000))["id"] for i in ("glimepiride", "metformin")]
    await a.care_schedule_set(plain, list(times))
    await a.care_schedule_set(ids[0], list(times))
    return plain, ids


async def gives(a):
    return sorted((g["drug"], g["by"], g["slot"][11:]) for g in await a.care_gives("asha"))


async def test_a_refused_tablet_writes_nothing_not_even_the_ingredient_that_was_free(gm):
    """B3: Meena ticks plain metformin; Ravi ticks Glycomet-GP and is told it was already given, but glimepiride was recorded as given by Ravi."""
    t, a, b = await circle(gm)
    plain, combo = await glycomet_and_metformin(a)
    now = at("08:10")
    assert (await b.care_give_slot("asha", plain, "08:00", now))["given"] is True
    r = await a.care_give_slot("asha", combo[0], "08:00", now)
    assert r["given"] is False and r["reason"] == "shared_ingredient" and r["already"] == ["metformin"] and r["already_given_by"] == "tk-b"
    assert await gives(a) == [("metformin", "tk-b", "08:00")]                                       # no glimepiride, nothing half-recorded
    states = {(i.get("label") or i["drug"]): i["state"] for i in (await a.care_today("asha", now))["items"]}
    assert states["glycomet-gp"] != "given"                                                           # the checklist does not say the tablet was given
    assert "Nothing was recorded for this tablet" in r["note"] and not scan_advice(r["note"])


async def test_the_same_refusal_the_other_way_round(gm):
    t, a, b = await circle(gm)
    plain, combo = await glycomet_and_metformin(a)
    now = at("08:10")
    assert (await a.care_give_slot("asha", combo[0], "08:00", now))["given"] is True
    r = await b.care_give_slot("asha", plain, "08:00", now)
    assert r["given"] is False
    assert {g[0] for g in await gives(a)} == {"glimepiride", "metformin"} and {g[1] for g in await gives(a)} == {"tk-a"}


async def test_a_second_carer_ticking_the_same_tablet_is_told_it_is_the_same_tablet(gm):
    t, a, b = await circle(gm)
    ids = [(await a.care_record("asha", i, freq_text="once daily", product="Telma-AM", at=at("00:00") - 86_400_000))["id"] for i in ("telmisartan", "amlodipine")]
    await a.care_schedule_set(ids[0], ["21:00"])
    now = at("21:05")
    first = await a.care_give_slot("asha", ids[0], "21:00", now)
    second = await b.care_give_slot("asha", ids[1], "21:00", now)
    assert first["given"] is True and set(first["ingredients"]) == {"telmisartan", "amlodipine"}
    assert second["given"] is False and second["reason"] == "same_tablet" and second["already_given_by"] == "tk-a" and "this tablet" in second["note"]
    assert {g[1] for g in await gives(a)} == {"tk-a"}                                                   # both ingredients credited to the one carer


async def test_two_carers_ticking_one_tablet_at_once_have_exactly_one_winner_and_never_split_it(gm):
    """B4: in 12 concurrent double-ticks on the live site, nobody won 6 times and two carers split the ingredients 6 times."""
    t, a, b = await circle(gm)
    ids = [(await a.care_record("asha", i, freq_text="once daily", product="Telma-AM", at=at("00:00") - 86_400_000))["id"] for i in ("telmisartan", "amlodipine")]
    times = ["16:30", "17:30", "18:30", "19:30", "20:30", "21:30"]
    await a.care_schedule_set(ids[0], times)
    for rnd in range(3):                                                                                # repeat: a race shows up in some rounds, not all
        if rnd:
            await a._q("MATCH (g:Give) DETACH DELETE g")
        for hh in times:
            now = at(hh)
            ra, rb = await asyncio.gather(a.care_give_slot("asha", ids[0], hh, now), b.care_give_slot("asha", ids[1], hh, now))
            assert sorted([ra["given"], rb["given"]]) == [False, True], (hh, ra, rb)                  # exactly one winner
        by_slot = {}
        for d, by, slot in await gives(a):
            by_slot.setdefault(slot, set()).add(by)
        assert len(by_slot) == len(times) and all(len(v) == 1 for v in by_slot.values()), by_slot       # both ingredients of a tablet went to the same carer


async def test_the_double_dose_guard_still_refuses_an_ingredient_given_at_the_same_time_by_hand(gm):
    t, a, b = await circle(gm)
    plain, combo = await glycomet_and_metformin(a)
    await b.care_give("asha", "metformin", "2026-09-20 08:00")                                         # recorded by hand (the plain operation)
    r = await a.care_give_slot("asha", combo[0], "08:00", at("08:10"))
    assert r["given"] is False and r["reason"] == "shared_ingredient"
    assert await gives(a) == [("metformin", "tk-b", "08:00")]


async def test_b5_both_were_prescribed_records_the_second_source_only_after_a_refusal_and_says_so(gm):
    """Round 3, B5: the guard treats the same molecule as the same dose, so a second source that really was prescribed could never be recorded."""
    t, a, b = await circle(gm)
    plain, combo = await glycomet_and_metformin(a)
    now = at("08:10")
    assert (await b.care_give_slot("asha", plain, "08:00", now))["given"] is True                              # Meena gives the plain metformin
    refused = await a.care_give_slot("asha", combo[0], "08:00", now)
    assert refused["given"] is False and refused["reason"] == "shared_ingredient"                                # the default is still a refusal that writes nothing
    assert await gives(a) == [("metformin", "tk-b", "08:00")]
    ok = await a.care_give_slot("asha", combo[0], "08:00", now, both_prescribed=True)                           # Ravi says both were prescribed
    assert ok["given"] is True and ok["override"] is True and "second source" in ok["note"] and set(ok["ingredients"]) == {"glimepiride", "metformin"}
    g = await a.care_gives("asha")
    assert sorted((x["drug"], x["by"], x["second_source"]) for x in g) == [("glimepiride", "tk-a", True), ("metformin", "tk-a", True), ("metformin", "tk-b", False)]
    rows = {(i.get("label") or i["drug"]): i for i in (await a.care_today("asha", now))["items"]}
    assert rows["glycomet-gp"]["state"] == "given" and rows["glycomet-gp"]["given_by"] == "tk-a" and rows["metformin"]["given_by"] == "tk-b"
    text = [e["text"] for e in await a.care_timeline("asha", limit=50, now=now) if e["kind"] == "give"]
    assert any("second source (both were prescribed)" in x or "one tablet" in x for x in text) and any("second source" in x for x in text), text
    again = await b.care_give_slot("asha", combo[0], "08:00", now, both_prescribed=True)                        # the second source can be claimed once
    assert again["given"] is False and again["reason"] == "same_tablet" or again["given"] is False


async def test_both_prescribed_changes_nothing_when_there_is_no_clash_and_works_for_a_plain_give_too(gm):
    t, a, b = await circle(gm)
    plain, combo = await glycomet_and_metformin(a)
    free = await a.care_give_slot("asha", combo[0], "08:00", at("08:10"), both_prescribed=True)                  # nothing to override: an ordinary give
    assert free["given"] is True and "override" not in free
    assert {x["second_source"] for x in await a.care_gives("asha")} == {False}
    second = await b.care_give_slot("asha", plain, "08:00", at("08:10"), both_prescribed=True)                  # now the plain metformin clashes with the tablet's: the override applies
    assert second["given"] is True and second["override"] is True
    dup = await a.care_give("asha", "metformin", "2026-09-20 08:00", True)
    assert dup["given"] is False and dup["reason"] == "same_second_source"                                      # once per drug and slot


async def test_the_override_is_in_the_operation_and_a_read_only_key_cannot_use_it(gm):
    import pytest
    from graphmem import ops
    from graphmem.policy import PermissionDenied
    t, a, b = await circle(gm)
    await gm.grant("tk-ro", t, ("read",))
    plain, combo = await glycomet_and_metformin(a)
    with pytest.raises(PermissionDenied):
        await ops.invoke(gm, "tk-ro", t, "care_give_slot", {"person": "asha", "dose_id": combo[0], "time": "08:00", "both_prescribed": True})
    assert "both_prescribed" in [x["name"] for x in ops.describe()["care_give_slot"]["args"]]
