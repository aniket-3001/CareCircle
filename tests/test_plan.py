"""Appointments, conditions, allergies and the 'what to bring' page: stored as typed, cross-checked, never advising."""
import time

import pytest

from conftest import tid

D = 86_400_000


async def _m(gm, name):
    t = tid(gm, name)
    await gm.grant("ravi", t, ("read", "write", "admin"))
    return gm.open("ravi", t)


async def test_appointments_expire_lazily_and_stay_in_history(gm):
    m = await _m(gm, "ap")
    now = int(time.time() * 1000)
    a = await m.care_appoint("asha", "Clinic: INR review", now + 3 * D, "Riverside", "meena", "INR diary, all pill boxes")
    await m.care_appoint("asha", "Eye check", now - 5 * D)
    b = await m.care_appoint("asha", "Dentist", now + 9 * D)
    await m.care_appointment_cancel(b["id"])
    got = await m.care_appointments("asha", now)
    assert [(x["title"], x["status"]) for x in got] == [("Clinic: INR review", "upcoming"), ("Dentist", "cancelled"), ("Eye check", "done")]
    later = await m.care_appointments("asha", now + 4 * D)
    assert {x["title"]: x["status"] for x in later}["Clinic: INR review"] == "done"       # read as done once its date passed, nothing rewritten
    with pytest.raises(ValueError):
        await m.care_appoint("asha", "  ", now)
    with pytest.raises(ValueError):
        await m.care_appoint("asha", "x", now + 99 * 366 * D)
    assert a["id"]


async def test_allergy_hits_ask_never_advise(gm):
    m = await _m(gm, "al")
    await m.care_record("asha", "clarithromycin", dose_text="500 mg")
    await m.care_record("asha", "ibuprofen", dose_text="400 mg")
    await m.care_record("asha", "metformin", dose_text="500 mg")
    r = await m.care_allergy_add("asha", "Penicillin")
    await m.care_allergy_add("asha", "NSAIDs")
    await m.care_allergy_add("asha", "Warfarin")                                     # not on record: no hit
    out = await m.care_allergy_check("asha")
    assert {h["drug"] for h in out["hits"]} == {"ibuprofen"} and "No hit does not mean" in out["note"]
    await m.care_record("asha", "amoxicillin", dose_text="500 mg")
    assert {h["drug"] for h in (await m.care_allergy_check("asha"))["hits"]} == {"ibuprofen", "amoxicillin"}
    assert r["id"]


async def test_allergy_groups_are_matched_by_the_words_a_family_uses_and_only_as_whole_words(gm):
    from carecircle.classes import group_of
    assert group_of("Sulpha drugs")[0] == "sulfa" and group_of("allergic to cephalosporins")[0] == "cephalosporin"
    assert group_of("Telmisartan rash")[0] == "" and group_of("ace")[0] == "ace inhibitor"
    assert group_of("grace")[0] == "" and group_of("peanuts")[0] == ""                        # a word inside another word is not a class
    m = await _m(gm, "alc")
    await m.care_record("asha", "ciprofloxacin", dose_text="500 mg")
    await m.care_record("asha", "telmisartan", dose_text="40 mg")
    await m.care_record("asha", "metformin", dose_text="500 mg")
    await m.care_allergy_add("asha", "Quinolones")
    await m.care_allergy_add("asha", "ARBs")
    out = await m.care_allergy_check("asha")
    assert {h["drug"] for h in out["hits"]} == {"ciprofloxacin", "telmisartan"}
    assert all("not verified" in h["why"] for h in out["hits"])


async def test_what_to_bring_is_assembled_from_the_record(gm):
    m = await _m(gm, "wb")
    now = int(time.time() * 1000)
    await m.care_record("asha", "metformin", dose_text="500 mg", at=now - 60 * D)
    await m.care_record("asha", "warfarin", dose_text="4 mg", at=now - 3 * D)
    await m.care_measure("asha", "inr", 2.4, at=now - 2 * D)
    await m.care_appoint("asha", "Last visit", now - 20 * D)
    await m.care_appoint("asha", "Next visit", now + 2 * D)
    out = await m.care_since_visit("asha", now=now)
    assert out["appointment"]["title"] == "Next visit" and out["since"] == now - 20 * D
    assert [c["drug"] for c in out["changes"]] == ["warfarin"] and [r["kind"] for r in out["readings"]] == ["inr"]
    assert "not advice" in out["note"]


async def test_conditions_profile_and_erase(gm):
    m = await _m(gm, "pf")
    c = await m.care_condition_add("asha", "Type 2 diabetes")
    await m.care_allergy_add("asha", "Sulfa")
    await m.care_appoint("asha", "x", int(time.time() * 1000) + D)
    prof = await m.care_profile("asha")
    assert [x["name"] for x in prof["conditions"]] == ["Type 2 diabetes"] and len(prof["allergies"]) == 1
    await m.care_profile_remove(c["id"])
    assert (await m.care_profile("asha"))["conditions"] == []
    await m.care_forget_person("asha", confirm="asha")
    assert (await m.care_profile("asha"))["allergies"] == [] and await m.care_appointments("asha") == []


async def test_edit_an_appointment_and_reword_conditions_and_allergies(gm):
    m = await _m(gm, "ed")
    now = int(time.time() * 1000)
    a = (await m.care_appoint("asha", "Clinic", now + 3 * D, "Riverside", "meena", "diary"))["id"]
    await m.care_appointment_edit(a, at=now + 6 * D, place="North clinic")
    got = next(x for x in await m.care_appointments("asha", now) if x["id"] == a)
    assert got["place"] == "North clinic" and got["at"] == now + 6 * D and got["title"] == "Clinic" and got["bring"] == "diary"      # only what was sent changed
    with pytest.raises(ValueError):
        await m.care_appointment_edit(a, at=now + 99 * 366 * D)
    with pytest.raises(KeyError):
        await m.care_appointment_edit("nope", title="x")
    c = (await m.care_condition_add("asha", "high bp"))["id"]
    await m.care_profile_edit(c, "high blood pressure")
    al = (await m.care_allergy_add("asha", "something"))["id"]
    assert (await m.care_profile_edit(al, "penicillin"))["resolved_to"] in ("penicillin v", "penicillin g", "penicillin", "")
    prof = await m.care_profile("asha")
    assert prof["conditions"][0]["name"] == "high blood pressure" and prof["allergies"][0]["text"] == "penicillin"
    with pytest.raises(ValueError):
        await m.care_profile_edit(c, "  ")
