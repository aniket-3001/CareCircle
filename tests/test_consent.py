"""A note of what the person said about the record, and a plain view of it for them. Not legal consent, and the text says so."""
import pytest

from conftest import tid
from graphmem.policy import PermissionDenied


async def make(gm):
    t = tid(gm, "cn")
    await gm.grant("ravi", t, ("read", "write"))
    await gm.grant("ro", t, ("read",))
    return gm.open("ravi", t), gm.open("ro", t)


async def test_consent_is_a_note_newest_wins_and_history_stays(gm):
    m, ro = await make(gm)
    await m.care_record("asha", "metformin", dose_text="500 mg", freq_text="twice daily")
    assert (await m.care_consent("asha"))["status"] == "not_asked"
    await m.care_consent_set("asha", "declined", note="Said she wants to think")
    await m.care_consent_set("asha", "agreed", who="a guardian or family member on their behalf")
    got = await m.care_consent("asha")
    assert got["status"] == "agreed" and [h["status"] for h in got["history"]] == ["agreed", "declined"] and "not legal consent" in got["note"]
    with pytest.raises(ValueError):
        await m.care_consent_set("asha", "maybe")
    with pytest.raises(ValueError):
        await m.care_consent_set("asha", "agreed", who="the neighbour")
    with pytest.raises(PermissionDenied):
        await ro.care_consent_set("asha", "agreed")
    with pytest.raises(ValueError):
        await m.care_consent_set("ashaa", "agreed")                                      # a near-miss name is not a second patient


async def test_the_patient_view_lists_what_is_kept_who_sees_it_and_makes_no_promise_of_safety(gm):
    m, ro = await make(gm)
    await m.care_record("asha", "metformin", dose_text="500 mg", freq_text="twice daily")
    v = await ro.care_patient_view("asha")
    assert v["medicines"][0]["drug"] == "metformin" and "ravi" in v["who_can_see"] and v["consent"] is None
    text = " ".join(v["what_is_kept"] + v["what_is_not"] + [v["your_rights"]]).lower()
    assert "does not give advice" in text and "safe" in text and "remove" in text
