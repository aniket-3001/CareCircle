"""The same ingredient reaching a person through two products: the review's story. 'Telma-AM and amlodipine 5 mg were prescribed by two doctors; the graph sees
amlodipine twice.' Entries are kept apart per product so a second source is a second entry, not a silent replacement of the first."""
import pytest

from carecircle import intake
from carecircle.checks import Checker
from carecircle.safety import scan_advice
from conftest import tid


async def circle(gm):
    t = tid(gm, "dup")
    for a in ("dup-a", "dup-b"):
        await gm.grant(a, t, ("read", "write", "admin"))
    return t, gm.open("dup-a", t), gm.open("dup-b", t)


async def test_the_same_ingredient_from_two_products_is_two_entries_and_a_flag(gm):
    t, a, b = await circle(gm)
    await a.care_record("asha", "amlodipine", dose_text="5 mg", freq_text="once daily", source_type="typed", at=1_000)                    # one doctor: plain amlodipine
    await b.care_record("asha", "telmisartan", dose_text="40 mg", freq_text="once daily", product="Telma-AM", at=2_000)
    await b.care_record("asha", "amlodipine", dose_text="5 mg", freq_text="once daily", product="Telma-AM", at=2_000)                  # another doctor: the combination
    reg = await a.care_regimen("asha")
    assert [(r["drug"], r["product"]) for r in reg] == [("amlodipine", ""), ("amlodipine", "telma-am"), ("telmisartan", "telma-am")]        # not silently replaced
    dups = await a.care_duplicates("asha")
    assert [d["ingredient"] for d in dups] == ["amlodipine"] and {e["product"] for e in dups[0]["entries"]} == {"", "telma-am"}
    assert "may be the same medicine from two sources" in dups[0]["meaning"] and not scan_advice(dups[0]["meaning"])
    chk = await a.care_check("asha")
    assert chk["duplicates"] == dups and chk["judgement"]["state"] == "flags" and "duplicate" in chk["judgement"]["statement"]
    assert any("amlodipine" in r for r in chk["judgement"]["reasons"])


async def test_a_change_to_one_product_does_not_touch_the_other_and_a_stop_ends_only_its_own(gm):
    t, a, b = await circle(gm)
    plain = await a.care_record("asha", "amlodipine", dose_text="5 mg", freq_text="daily", at=1_000)
    combo = await a.care_record("asha", "amlodipine", dose_text="5 mg", freq_text="daily", product="Telma-AM", at=1_500)
    await a.care_record("asha", "amlodipine", dose_text="10 mg", freq_text="daily", at=2_000)                                              # the plain one changes
    now = {(r["product"], r["dose_text"]) for r in await a.care_regimen("asha")}
    assert now == {("", "10 mg"), ("telma-am", "5 mg")}
    await a.care_record("asha", "amlodipine", action="stop", product="Telma-AM", at=3_000)
    assert {(r["product"], r["dose_text"]) for r in await a.care_regimen("asha")} == {("", "10 mg")}
    assert await a.care_duplicates("asha") == [] and plain["id"] != combo["id"]
    with pytest.raises(KeyError):
        await a.care_record("asha", "amlodipine", action="stop", product="Other-Brand")                                                    # nothing of that product to stop


async def test_unseen_changes_are_tracked_per_product_so_one_cannot_hide_the_other(gm):
    t, a, b = await circle(gm)
    await a.care_record("asha", "amlodipine", dose_text="5 mg", freq_text="daily", at=1_000)
    await a.care_record("asha", "amlodipine", dose_text="5 mg", freq_text="daily", product="Telma-AM", at=2_000)
    await b.care_ack((await b.care_regimen("asha"))[0]["id"])
    d = await b.care_divergence("asha", now=2_000 + 10 * 3_600_000)
    assert [u["drug"] for u in d["carers"]["dup-b"]["unacknowledged"]] == ["amlodipine"]                                                   # the Telma-AM entry is still unseen by b


async def test_intake_marks_the_product_a_combination_ingredient_came_from():
    props = intake.rule_proposals("Telma-AM 40 mg once daily", Checker())
    assert {p["combination"] for p in props} == {"Telma-AM"} and [p["drug_candidates"][0]["name"] for p in props] == ["telmisartan", "amlodipine"]
