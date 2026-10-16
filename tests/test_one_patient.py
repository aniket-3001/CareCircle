"""A typing slip in the person's name must not start a second patient with an empty record (the real one would then look as if nothing had been entered)."""
import time

import pytest

from conftest import tid


async def test_a_near_miss_of_a_person_already_in_the_circle_is_refused_everywhere_a_person_can_be_created(gm):
    t = tid(gm, "pp")
    await gm.grant("pp-w", t, ("read", "write", "admin"))
    m = gm.open("pp-w", t)
    await m.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily", source_type="typed")
    calls = {
        "record": lambda p: m.care_record(p, "warfarin", dose_text="5 mg", freq_text="daily", source_type="typed"),
        "reading": lambda p: m.care_measure(p, "heart_rate", 70),
        "appointment": lambda p: m.care_appoint(p, "Check-up", int(time.time() * 1000) + 7 * 86_400_000),
        "condition": lambda p: m.care_condition_add(p, "asthma"),
        "followup": lambda p: m.care_followup_add(p, [{"key": "k1", "text": "Ask about the dose", "kind": "ask", "basis": []}]),
        "allergy": lambda p: m.care_allergy_add(p, "penicillin"),
    }
    for name, call in calls.items():
        with pytest.raises(ValueError, match="looks like 'asha'"):
            await call("ashaa")
    people = await m.care_people()
    assert people["patients"] == ["asha"], people


async def test_a_genuinely_different_person_is_fine_and_a_close_name_can_be_added_on_purpose(gm):
    t = tid(gm, "pp2")
    await gm.grant("pp-w2", t, ("read", "write", "admin"))
    m = gm.open("pp-w2", t)
    await m.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily", source_type="typed")
    await m.care_record("ravi", "aspirin", dose_text="75 mg", freq_text="daily", source_type="typed")          # a different name: allowed
    await m.care_add_person("ashaa")                                                                          # on purpose: now it exists
    await m.care_record("ashaa", "warfarin", dose_text="5 mg", freq_text="daily", source_type="typed")
    assert set((await m.care_people())["patients"]) == {"asha", "ravi", "ashaa"}


async def test_the_first_person_in_an_empty_circle_is_accepted_and_a_read_only_key_cannot_add_people(gm):
    t = tid(gm, "pp3")
    await gm.grant("pp-w3", t, ("read", "write"))
    await gm.grant("pp-r3", t, ("read",))
    from graphmem import ops
    await gm.open("pp-w3", t).care_record("mum", "metformin", dose_text="500 mg", freq_text="daily", source_type="typed")
    from graphmem.policy import PermissionDenied
    with pytest.raises(PermissionDenied):
        await ops.invoke(gm, "pp-r3", t, "care_add_person", {"person": "dad"})
