"""Readings over time: stored as typed, never judged, linked to the dates a medicine's entry changed."""
import time

import pytest

from conftest import tid

D = 86_400_000


async def _m(gm, name="tr"):
    t = tid(gm, name)
    await gm.grant("ravi", t, ("read", "write", "admin"))
    return gm.open("ravi", t)


async def test_slips_are_refused_values_are_not_judged(gm):
    m = await _m(gm)
    for kind, v, unit in (("bp_systolic", 1200, ""), ("bp_systolic", 5, ""), ("glucose", -3, ""), ("temperature", 400, "C"), ("inr", "abc", "")):
        with pytest.raises(ValueError):
            await m.care_measure("asha", kind, v, unit)
    with pytest.raises(ValueError):
        await m.care_measure("asha", "inr", 2.5, "mg")                             # wrong unit for the kind
    with pytest.raises(ValueError):
        await m.care_measure("asha", "inr", 2.5, at=int(time.time() * 1000) + 5 * D)   # from the future
    with pytest.raises(ValueError):
        await m.care_measure("asha", "mood", 3)
    r = await m.care_measure("asha", "bp_systolic", 190)                           # very high but possible: stored, not judged
    assert r["value"] == 190 and r["unit"] == "mmHg"
    assert (await m.care_measure("asha", "glucose", 6.1, "mmol/L"))["unit"] == "mmol/L"


async def test_trend_lines_readings_up_with_the_medicine_changes(gm):
    m = await _m(gm, "tr2")
    now = int(time.time() * 1000)
    await m.care_record("asha", "warfarin", dose_text="3 mg", at=now - 40 * D)
    await m.care_record("asha", "warfarin", dose_text="4 mg", at=now - 20 * D)
    for days, v in ((38, 1.8), (30, 1.9), (25, 2.0), (18, 2.3), (12, 2.6), (5, 2.5)):
        await m.care_measure("asha", "inr", v, at=now - int(days * D))
    out = await m.care_trend("asha", "inr", "warfarin", 14, now)
    assert [r["value"] for r in out["series"]] == [1.8, 1.9, 2.0, 2.3, 2.6, 2.5] and out["units"] == ["ratio"]
    first, second = out["changes"]
    assert first["before"]["n"] == 0 and first["after"] == {"n": 2, "mean": 1.85}         # 38 and 30 days ago are within 14 days after the change 40 days ago; 25 is not
    assert second["before"] == {"n": 2, "mean": 1.95} and second["after"] == {"n": 2, "mean": 2.45}
    assert "does not judge" in out["note"]


async def test_measurements_appear_in_history_and_go_with_the_person(gm):
    m = await _m(gm, "tr3")
    r = await m.care_measure("asha", "weight", 61.5)
    assert any(e["kind"] == "measure" and "61.5 kg" in e["text"] for e in await m.care_timeline("asha"))
    await m.care_forget_measure(r["id"])
    assert await m.care_measures("asha") == []
    await m.care_measure("asha", "weight", 62)
    await m.care_forget_person("asha", confirm="asha")
    assert await m.care_measures("asha") == []
