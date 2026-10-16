"""Second-carer confirmation (the family's rule) and append-only handover notes."""
import asyncio

import time

import pytest

from conftest import day, tid


async def _two(gm, name):
    t = tid(gm, name)
    for c in ("ravi", "meena"):
        await gm.grant(c, t, ("read", "write", "admin"))
    return gm.open("ravi", t), gm.open("meena", t)


async def test_watched_dose_needs_a_different_carer(gm):
    ravi, meena = await _two(gm, "cu")
    await ravi.care_record("asha", "warfarin", dose_text="4 mg", at=int(time.time() * 1000) - 3 * 24 * 3_600_000)
    await ravi.care_record("asha", "metformin", dose_text="500 mg", at=int(time.time() * 1000) - 3 * 24 * 3_600_000)
    assert (await ravi.care_give("asha", "metformin", f"{day(-1)} 08:00")).get("needs_second_carer") is None      # not watched: nothing extra
    await ravi.care_watch("asha", "warfarin")
    assert await ravi.care_watched("asha") == ["warfarin"]
    r = await ravi.care_give("asha", "warfarin", f"{day(-1)} 18:00")
    assert r["given"] and r["needs_second_carer"]
    assert [g["needs_second_carer"] for g in await ravi.care_gives("asha") if g["drug"] == "warfarin"] == [True]
    with pytest.raises(ValueError):
        await ravi.care_witness("asha", "warfarin", f"{day(-1)} 18:00")                     # not your own dose
    with pytest.raises(KeyError):
        await meena.care_witness("asha", "warfarin", f"{day(0)} 18:00")                    # nothing recorded for that slot
    assert (await meena.care_witness("asha", "warfarin", f"{day(-1)} 18:00"))["by"] == "meena"
    g = next(g for g in await ravi.care_gives("asha") if g["drug"] == "warfarin")
    assert g["witness"] == "meena" and g["needs_second_carer"] is False
    await ravi.care_watch("asha", "warfarin", False)
    assert await ravi.care_watched("asha") == []


async def test_handover_notes_are_append_only_and_erased_with_the_person(gm):
    ravi, meena = await _two(gm, "ho")
    await ravi.care_handover("asha", "INR was 2.4 on Tuesday. Next check Monday.")
    await asyncio.sleep(0.01)                                                   # two notes in the same millisecond have no order; real ones never do
    await meena.care_handover("asha", "Gave the evening warfarin. She slept early.")
    notes = await meena.care_handovers("asha")
    assert [n["by"] for n in notes] == ["meena", "ravi"] and "2.4" in notes[1]["text"]
    with pytest.raises(ValueError):
        await ravi.care_handover("asha", "   ")
    assert not hasattr(ravi, "care_handover_edit") and not hasattr(ravi, "care_handover_delete")
    await ravi.care_forget_person("asha", confirm="asha")
    assert await ravi.care_handovers("asha") == []
