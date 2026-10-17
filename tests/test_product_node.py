"""A tablet is a node. Every entry points at one (:Product) with VIA, the times it is taken at live on that node, and a combination is one node under which its
ingredients' entries sit. These tests hold the rules that used to depend on comparing a `product` string in a dozen queries."""
from datetime import date

import pytest

from conftest import tid
from carecircle import schedule as s

IST = "Asia/Kolkata"


def at(day, hhmm):
    return s.slot_moment_ms(day, hhmm, IST)


async def circle(gm):
    t = tid(gm, "pn")
    await gm.grant("pn-a", t, ("read", "write", "admin"))
    await gm.grant("pn-b", t, ("read", "write"))
    a = gm.open("pn-a", t)
    await a.care_set_timezone(IST)
    return t, a, gm.open("pn-b", t)


async def products(a):
    rows = (await a._q("MATCH (pr:Product) RETURN pr.key, pr.kind, pr.combo, pr.slots, pr.strength ORDER BY pr.key", scope="read"))
    return {r[0]: r for r in rows}


async def assert_invariants(a):
    """Every entry has exactly one product; no product is empty; the copy kept for a rolled-back server equals the node."""
    assert (await a._q("MATCH (x:Dose) OPTIONAL MATCH (x)-[v:VIA]->(:Product) WITH x, count(v) AS n WHERE n <> 1 RETURN count(x)", scope="read"))[0][0] == 0
    assert (await a._q("MATCH (pr:Product) WHERE NOT (pr)<-[:VIA]-(:Dose) RETURN count(pr)", scope="read"))[0][0] == 0
    drift = await a._q("MATCH (x:Dose {cur:true})-[:VIA]->(pr:Product) WHERE x.slots IS NOT NULL AND pr.slots IS NOT NULL AND x.slots <> pr.slots RETURN x.id", scope="read")
    assert drift == []


async def test_a_plain_medicine_and_a_combination_are_distinct_products_and_ingredients_share_one(gm):
    t, a, b = await circle(gm)
    await a.care_record("asha", "amlodipine", dose_text="5 mg", freq_text="once daily", at=1_000)
    for ing in ("telmisartan", "amlodipine"):
        await a.care_record("asha", ing, freq_text="once daily", product="Telma-AM", product_strength="40/5 mg", at=2_000)
    got = await products(a)
    assert set(got) == {"asha|medicine|amlodipine", "asha|combination|telma-am"}, got
    assert got["asha|combination|telma-am"][2] == "telma-am" and got["asha|combination|telma-am"][4] == "40/5 mg" and got["asha|medicine|amlodipine"][2] == ""
    n = await a._q("MATCH (:Product {key:'asha|combination|telma-am'})<-[:VIA]-(x:Dose) RETURN count(x)", scope="read")
    assert n == [[2]]                                                                                    # both ingredients' entries sit under the one node
    await assert_invariants(a)


async def test_the_times_belong_to_the_tablet_so_two_products_of_one_ingredient_are_independent(gm):
    """N2 by construction: the plain amlodipine and the one inside Telma-AM each have their own times, and a change to one never touches the other."""
    t, a, b = await circle(gm)
    day = date(2026, 9, 20)
    plain = (await a.care_record("asha", "amlodipine", dose_text="5 mg", freq_text="once daily", at=1_000))["id"]
    combo = [(await a.care_record("asha", i, freq_text="once daily", product="Telma-AM", at=1_000))["id"] for i in ("telmisartan", "amlodipine")]
    await a.care_schedule_set(plain, ["08:00"])
    await a.care_schedule_set(combo[0], ["20:00"])
    reg = {(r["drug"], r["product"]): r["slots"] for r in await a.care_regimen("asha", at(day, "07:00"))}
    assert reg == {("amlodipine", ""): ["08:00"], ("amlodipine", "telma-am"): ["20:00"], ("telmisartan", "telma-am"): ["20:00"]}
    await a.care_record("asha", "amlodipine", dose_text="10 mg", freq_text="once daily", at=2_000)               # the plain one's dose changes
    reg = {(r["drug"], r["product"]): (r["dose_text"], r["slots"]) for r in await a.care_regimen("asha", at(day, "07:00"))}
    assert reg[("amlodipine", "")] == ("10 mg", ["08:00"]) and reg[("amlodipine", "telma-am")][1] == ["20:00"]      # times kept through a change of dose; the other product untouched
    await assert_invariants(a)


async def test_a_new_written_frequency_clears_the_times_and_a_stop_ends_them_and_a_restart_starts_clean(gm):
    t, a, b = await circle(gm)
    day = date(2026, 9, 20)
    e = (await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="twice daily", at=1_000))["id"]
    await a.care_schedule_set(e, ["08:00", "20:00"])
    await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="three times daily", at=2_000)
    assert [r["slots"] for r in await a.care_regimen("asha", at(day, "07:00"))] == [[]]                       # the confirmed times no longer fit the new frequency
    e2 = (await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="three times daily", at=2_001, action="set"))
    await a.care_schedule_set((await a.care_regimen("asha", at(day, "07:00")))[0]["id"], ["07:00", "13:00", "21:00"])
    await a.care_record("asha", "metformin", action="stop", at=3_000)
    assert (await products(a))["asha|medicine|metformin"][3] is None                                          # stopped: the tablet keeps no times
    await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="once daily", at=4_000)
    assert [r["slots"] for r in await a.care_regimen("asha", at(day, "07:00"))] == [[]]                       # restarted: nothing is resurrected
    await assert_invariants(a)


async def test_a_new_ingredient_joining_a_scheduled_product_keeps_its_times(gm):
    t, a, b = await circle(gm)
    day = date(2026, 9, 20)
    first = (await a.care_record("asha", "telmisartan", freq_text="once daily", product="Telma-AM", at=1_000))["id"]
    await a.care_schedule_set(first, ["09:00"])
    await a.care_record("asha", "amlodipine", freq_text="once daily", product="Telma-AM", at=1_500)             # the second ingredient is added later
    assert {r["drug"]: r["slots"] for r in await a.care_regimen("asha", at(day, "08:00"))} == {"telmisartan": ["09:00"], "amlodipine": ["09:00"]}
    assert len((await a.care_today("asha", at(day, "08:30")))["items"]) == 1                                  # still one row


async def test_an_older_entry_typed_late_does_not_clear_the_current_times(gm):
    t, a, b = await circle(gm)
    day = date(2026, 9, 20)
    e = (await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="twice daily", at=5_000))["id"]
    await a.care_schedule_set(e, ["08:00", "20:00"])
    await a.care_record("asha", "metformin", dose_text="250 mg", freq_text="once daily", at=1_000)              # a past prescription typed in late slots into history
    assert [r["slots"] for r in await a.care_regimen("asha", at(day, "07:00"))] == [["08:00", "20:00"]]


async def test_erasing_the_last_entry_removes_its_product_and_erasing_the_person_removes_every_product(gm):
    t, a, b = await circle(gm)
    e = (await a.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily", at=1_000))["id"]
    f = (await a.care_record("asha", "amlodipine", freq_text="daily", product="Telma-AM", at=1_000))["id"]
    await a.care_forget(e, reason="entered twice")
    assert set(await products(a)) == {"asha|combination|telma-am"}                                             # warfarin's tablet went with its only entry
    await assert_invariants(a)
    await a.care_forget_person("asha", confirm="asha")
    assert await products(a) == {}


async def test_marking_a_mistake_and_restoring_it_keeps_one_product_and_the_chain_still_verifies(gm):
    t, a, b = await circle(gm)
    e = (await a.care_record("asha", "telmisartan", freq_text="daily", product="Telma-AM", at=1_000))["id"]
    await a.care_mark_mistake(e, "wrong brand")
    await a.care_restore_entry(e)
    assert set(await products(a)) == {"asha|combination|telma-am"}
    v = await a.care_chain_verify()
    assert v["ok"] is True and v["entries_logged"] == 1
    await assert_invariants(a)


async def test_the_history_fingerprint_and_the_chain_do_not_change_when_products_became_nodes(gm):
    """An entry's hash includes the product's name exactly as before, so a log written by the previous version still verifies."""
    from graphmem.care_chain import entry_body
    t, a, b = await circle(gm)
    e = (await a.care_record("asha", "telmisartan", dose_text="", freq_text="daily", product="Telma-AM", at=1_000))["id"]
    ev = (await a._q("MATCH (e:Event {ref:$r}) RETURN e.body, coalesce(e.kdf, 'graph')", {"r": e}, scope="read"))[0]
    key = await a._receipt_key(ev[1])
    assert ev[0] == entry_body(key, "telmisartan", "telma-am", "", "daily", "set", 1_000, "pn-a", "")       # the old formula, with the product's name as a string
    assert (await a.care_chain_verify())["ok"] is True


async def test_the_invariant_check_can_fail(gm):
    """A check that cannot fail proves nothing: remove an edge, add an orphan, and let the copy drift, and each is caught."""
    t, a, b = await circle(gm)
    e = (await a.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily", at=1_000))["id"]
    await a.care_schedule_set(e, ["08:00"])
    await assert_invariants(a)
    await a._q("MATCH (x:Dose {id:$i}) SET x.slots = ['09:00']", {"i": e})
    with pytest.raises(AssertionError):
        await assert_invariants(a)                                                                       # the copy drifted from the node
    await a._q("MATCH (x:Dose {id:$i}) SET x.slots = ['08:00']", {"i": e})
    await a._q("CREATE (:Product {key:'orphan'})")
    with pytest.raises(AssertionError):
        await assert_invariants(a)                                                                       # a product nobody points at
    await a._q("MATCH (pr:Product {key:'orphan'}) DELETE pr")
    await a._q("MATCH (:Dose {id:$i})-[v:VIA]->(:Product) DELETE v", {"i": e})
    with pytest.raises(AssertionError):
        await assert_invariants(a)                                                                       # an entry with no product
