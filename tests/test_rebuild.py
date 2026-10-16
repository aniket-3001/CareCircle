"""The medicine record is a log of dated entries; what is "current", when each entry ended and which entry replaced which are *derived*
from it. These tests wipe every derived value and rebuild from the entries alone, and require the very same record back: nothing the
app shows depends on state that cannot be recomputed."""
import json
import time

from conftest import tid

H = 3_600_000
NOW = int(time.time() * 1000)                              # one fixed "now" for the whole run, so everything shown is reproducible


async def circle(gm):
    t = tid(gm, "rb")
    for c in ("amma", "ravi", "meena"):
        await gm.grant(c, t, ("read", "write", "admin"))
    return t, gm.open("ravi", t), gm.open("meena", t)


async def messy_history(ravi, meena):
    """Everything that makes the timeline hard: back-dating, a forgotten typo, stop and restart, an unconfirmed entry, a second person."""
    a = await ravi.care_record("mum", "warfarin", dose_text="5 mg", freq_text="at bedtime", at=NOW - 40 * H)
    b = await ravi.care_record("mum", "warfarin", dose_text="7 mg", freq_text="at bedtime", at=NOW - 30 * H)
    await ravi.care_record("mum", "warfarin", dose_text="4 mg", freq_text="at bedtime", at=NOW - 60 * H)         # typed in late, older
    typo = await ravi.care_record("mum", "warfarin", dose_text="70 mg", freq_text="at bedtime", at=NOW - 10 * H)
    await ravi.care_forget(typo["id"], reason="typo")
    await ravi.care_record("mum", "metformin", dose_text="500 mg", freq_text="twice daily", at=NOW - 50 * H)
    await ravi.care_record("mum", "metformin", action="stop", at=NOW - 20 * H)
    await ravi.care_record("mum", "metformin", dose_text="850 mg", freq_text="twice daily", at=NOW - 5 * H)     # restarted
    await ravi.care_record("mum", "atorvastatin", dose_text="20 mg", freq_text="at night", source_type="photo",
                           quote="Atorvastatin 20mg", source_text="no such words here")                       # pending: not on the record
    await ravi.care_record("dad", "amlodipine", dose_text="5 mg", freq_text="daily", at=NOW - 12 * H)         # a second person
    await meena.care_ack(a["id"])
    await meena.care_ack(b["id"])
    await ravi.care_give("mum", "metformin", time.strftime("%Y-%m-%d %H:%M", time.gmtime(NOW / 1000 - 2 * 3600)))


async def state(m):
    """Everything a person can see that comes from the entries, with a fixed clock."""
    out = {"regimen_now": {p: await m.care_regimen(p, as_of=NOW) for p in ("mum", "dad")},
           "regimen_back": {f"{h}h": {p: await m.care_regimen(p, as_of=NOW - h * H) for p in ("mum", "dad")} for h in (1, 8, 15, 25, 35, 45, 55, 65)},
           "divergence": {p: await m.care_divergence(p, now=NOW) for p in ("mum", "dad")},
           "timeline": {p: await m.care_timeline(p, limit=100, now=NOW) for p in ("mum", "dad")},
           "graph": {p: await m.care_graph(p, include_history=True, now=NOW) for p in ("mum", "dad")}}
    out["raw"] = await m._q("MATCH (x:Dose)-[:FOR]->(:Person) RETURN x.id, x.cur, x.valid_to, x.status ORDER BY x.id", scope="read")
    out["chain"] = await m._q("MATCH (n:Dose)-[:SUPERSEDES]->(o:Dose) RETURN n.id, o.id ORDER BY n.id, o.id", scope="read")
    return json.loads(json.dumps(out, default=str, sort_keys=True))


async def wipe_derived(m):
    await m._q("MATCH (x:Dose {status:'confirmed'}) SET x.cur = null, x.valid_to = null")           # an unconfirmed entry has no place in the timeline yet
    await m._q("MATCH ()-[r:SUPERSEDES]->() DELETE r")


async def rebuild(m):
    pairs = await m._q("MATCH (x:Dose)-[:FOR]->(p:Person) RETURN DISTINCT p.id, x.drug ORDER BY p.id, x.drug", scope="read")
    for person, drug in pairs:
        await m._care_rechain(person, drug)
    return pairs


async def test_wiping_what_is_derived_and_rebuilding_gives_back_the_same_record(gm):
    t, ravi, meena = await circle(gm)
    await messy_history(ravi, meena)
    before = await state(ravi)
    assert before["chain"] and any(r[1] for r in before["raw"])                  # there is something derived to lose

    await wipe_derived(ravi)
    broken = await state(ravi)
    assert broken["chain"] == [] and broken != before                           # and wiping really did lose it

    pairs = await rebuild(ravi)
    assert ("mum", "warfarin") in [tuple(p) for p in pairs] and len(pairs) == 4  # warfarin, metformin and atorvastatin (mum), amlodipine (dad)
    assert await state(ravi) == before                                           # everything shown is back, to the last field


async def test_rebuilding_twice_changes_nothing(gm):
    t, ravi, meena = await circle(gm)
    await messy_history(ravi, meena)
    before = await state(ravi)
    await rebuild(ravi)
    await rebuild(ravi)
    assert await state(ravi) == before


async def test_the_answers_the_history_implies_are_the_ones_given(gm):
    """Rebuilding must not just reproduce *a* state: the back-dated and forgotten entries must land where their dates say."""
    t, ravi, meena = await circle(gm)
    await messy_history(ravi, meena)
    await wipe_derived(ravi)
    await rebuild(ravi)
    now = {r["drug"]: r["dose_text"] for r in await ravi.care_regimen("mum", as_of=NOW)}
    assert now == {"warfarin": "7 mg", "metformin": "850 mg"}                    # the typo is gone, atorvastatin was never confirmed
    assert {r["dose_text"] for r in await ravi.care_regimen("mum", as_of=NOW - 65 * H) if r["drug"] == "warfarin"} == set()   # before the first entry
    assert {r["dose_text"] for r in await ravi.care_regimen("mum", as_of=NOW - 55 * H) if r["drug"] == "warfarin"} == {"4 mg"}   # the back-dated entry
    assert {r["drug"] for r in await ravi.care_regimen("mum", as_of=NOW - 10 * H)} == {"warfarin"}              # metformin was stopped then
