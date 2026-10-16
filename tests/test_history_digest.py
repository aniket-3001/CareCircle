"""The history fingerprint: later work does not disturb it, an after-the-fact change to an earlier entry does."""
from conftest import tid


async def make(gm):
    t = tid(gm, "dg")
    await gm.grant("o-dg", t, ("read", "write", "admin"))
    return gm.open("o-dg", t)


async def test_a_digest_is_stable_under_later_entries_mistakes_and_stops_but_not_under_a_rewrite(gm):
    m = await make(gm)
    a = await m.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed")
    b = await m.care_record("asha", "metformin", dose_text="500 mg", freq_text="twice daily", source_type="typed")
    d2 = await m.care_history_digest("asha")
    assert d2["entries"] == 2 and len(d2["head"]) == 64 and d2["checkpoints"][0]["n"] == 1

    await m.care_record("asha", "amlodipine", dose_text="5 mg", freq_text="once daily", source_type="typed")      # a later entry
    await m.care_mark_mistake(b["id"], "typed twice")                                                             # a mistake mark
    await m.care_record("asha", "warfarin", dose_text="", freq_text="", action="stop", source_type="typed")      # a stop
    again = await m.care_history_digest("asha", upto=2)
    assert again["head"] == d2["head"] and again["of"] >= 4                                                     # the first two entries read the same

    await m._q("MATCH (x:Dose {id:$id}) SET x.dose_text = '50 mg'", {"id": a["id"]}, scope="admin")             # someone rewrites the first entry
    changed = await m.care_history_digest("asha", upto=2)
    assert changed["head"] != d2["head"]
    assert (await m.care_history_digest("asha", upto=1))["head"] != d2["checkpoints"][0]["hash"]


async def test_a_circle_with_no_entries_has_an_empty_digest(gm):
    m = await make(gm)
    d = await m.care_history_digest("nobody")
    assert d["entries"] == 0 and d["head"] == ""
