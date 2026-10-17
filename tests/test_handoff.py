"""A handover note is a handoff: addressed to a named carer, attached to the entry it is about, accepted by that carer and no one else, and shown as stale when the
entry changes afterwards (round 3: the product did not use the engine's handoff)."""
import pytest

from conftest import tid
from graphmem import ops
from graphmem.policy import PermissionDenied


async def circle(gm):
    t = tid(gm, "ho")
    for a in ("ho-ravi", "ho-meena", "ho-ro"):
        await gm.grant(a, t, ("read", "write") if a != "ho-ro" else ("read",))
    return t, gm.open("ho-ravi", t), gm.open("ho-meena", t)


async def test_a_note_addressed_to_a_carer_is_accepted_only_by_that_carer_and_once(gm):
    t, ravi, meena = await circle(gm)
    e = (await ravi.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime"))["id"]
    h = await ravi.care_handover("asha", "the warfarin dose went down tonight", about=e, to="ho-meena")
    assert h["to"] == "ho-meena" and h["status"] == "open" and h["about"] == e
    mine = [x for x in await meena.care_handovers("asha") if x["id"] == h["id"]][0]
    assert mine["status"] == "open" and mine["to"] == "ho-meena" and mine["stale"] is False and mine["about_drug"] == "warfarin"
    with pytest.raises(ValueError):
        await ravi.care_handover_accept(h["id"])                                                  # the sender cannot accept for her
    ok = await meena.care_handover_accept(h["id"])
    assert ok["status"] == "accepted" and ok["accepted_by"] == "ho-meena" and ok["stale"] is False
    again = await meena.care_handover_accept(h["id"])                                           # accepting twice changes nothing
    assert again["status"] == "accepted"
    row = [x for x in await ravi.care_handovers("asha") if x["id"] == h["id"]][0]
    assert row["status"] == "accepted" and row["accepted_by"] == "ho-meena" and row["accepted_at"]
    assert [(n["kind"], n["status"]) for n in (await meena.care_entry_notes(e))["notes"]] == [("handover", "accepted")]


async def test_a_note_goes_stale_when_the_entry_it_is_about_changes(gm):
    t, ravi, meena = await circle(gm)
    e = (await ravi.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime", at=1_000))["id"]
    h = await ravi.care_handover("asha", "check the dose with the clinic", about=e, to="ho-meena")
    await ravi.care_record("asha", "warfarin", dose_text="3 mg", freq_text="at bedtime", at=2_000)           # the entry is replaced after the note was written
    row = [x for x in await meena.care_handovers("asha") if x["id"] == h["id"]][0]
    assert row["stale"] is True
    ok = await meena.care_handover_accept(h["id"])
    assert ok["stale"] is True and "has changed since it was written" in ok["warning"]


async def test_a_note_cannot_be_addressed_to_oneself_or_a_stranger_or_accepted_when_it_has_no_addressee(gm):
    t, ravi, meena = await circle(gm)
    with pytest.raises(ValueError):
        await ravi.care_handover("asha", "to myself", to="ho-ravi")
    with pytest.raises(ValueError):
        await ravi.care_handover("asha", "to a stranger", to="somebody-with-no-access")
    plain = await ravi.care_handover("asha", "for whoever is next")
    assert "to" not in plain and (await ravi.care_handovers("asha"))[0]["status"] == "note"
    with pytest.raises(ValueError):
        await meena.care_handover_accept(plain["id"])
    with pytest.raises(KeyError):
        await meena.care_handover_accept("hand_missing")


async def test_a_read_only_key_cannot_accept_and_the_operation_is_in_the_catalogue(gm):
    t, ravi, meena = await circle(gm)
    h = await ravi.care_handover("asha", "for Meena", to="ho-meena")
    with pytest.raises(PermissionDenied):
        await ops.invoke(gm, "ho-ro", t, "care_handover_accept", {"handover_id": h["id"]})
    assert ops.OPS["care_handover_accept"] == "write"
    assert (await ops.invoke(gm, "ho-meena", t, "care_handover_accept", {"handover_id": h["id"]}))["status"] == "accepted"
