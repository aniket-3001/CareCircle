"""The brand a medicine was printed as is kept on the record, as its product. The review (B1, B2, B6) found, on the live site, that a second brand of one molecule
silently overwrote the first, that a 'possible combination' was saved over the plain medicine, and that two spellings produced no warning at all."""
import pytest

from conftest import tid
from carecircle import intake
from carecircle.checks import Checker


@pytest.fixture(scope="module")
def ch():
    return Checker()


async def circle(gm):
    t = tid(gm, "bp")
    await gm.grant("bp-a", t, ("read", "write", "admin"))
    return t, gm.open("bp-a", t)


async def save(a, text, ch):
    """What the web app does with the first proposal of a typed line: save it under its brand."""
    p = intake.propose(text, ch)[0]
    return p, await a.care_record("asha", p["drug_candidates"][0]["name"], dose_text=p["dose_text"], freq_text=p["freq_text"], source_type="typed",
                                  product=p.get("combination") or p.get("brand") or "")


async def test_b1_two_brands_of_one_molecule_are_two_entries_and_a_possible_duplicate(gm, ch):
    t, a = await circle(gm)
    p1, _ = await save(a, "Storvas 10 mg at night", ch)
    p2, _ = await save(a, "Atorva 20 mg at night", ch)
    assert p1["brand"] == "storvas" and p2["brand"] == "atorva"
    reg = {(r["drug"], r["product"]): r["dose_text"] for r in await a.care_regimen("asha")}
    assert reg == {("atorvastatin", "storvas"): "10 mg", ("atorvastatin", "atorva"): "20 mg"}            # not one entry at 20 mg
    dups = await a.care_duplicates("asha")
    assert [d["ingredient"] for d in dups] == ["atorvastatin"] and "Storvas" in dups[0]["meaning"] and "Atorva" in dups[0]["meaning"]
    assert (await a.care_check("asha"))["judgement"]["state"] == "flags"
    assert (await a.care_chain_verify())["ok"] is True


async def test_the_same_brand_again_is_a_change_of_dose_not_a_duplicate(gm, ch):
    t, a = await circle(gm)
    await save(a, "Storvas 10 mg at night", ch)
    await save(a, "Storvas 20 mg at night", ch)
    assert [(r["product"], r["dose_text"]) for r in await a.care_regimen("asha")] == [("storvas", "20 mg")]
    assert await a.care_duplicates("asha") == []


async def test_b2_a_possible_combination_saved_next_to_the_plain_medicine_does_not_overwrite_it(gm, ch):
    t, a = await circle(gm)
    await a.care_record("asha", "amlodipine", dose_text="5 mg", freq_text="once daily", source_type="typed")
    p, _ = await save(a, "Stamlo Beta once daily", ch)
    assert p["possible_combination"] == "Stamlo Beta" and p["brand"] == "Stamlo Beta"
    reg = {(r["drug"], r["product"]): r["dose_text"] for r in await a.care_regimen("asha")}
    assert reg == {("amlodipine", ""): "5 mg", ("amlodipine", "stamlo beta"): ""}                       # the 5 mg entry is still there
    assert [d["ingredient"] for d in await a.care_duplicates("asha")] == ["amlodipine"]
    assert (await a.care_check("asha"))["judgement"]["state"] == "flags"


@pytest.mark.parametrize("text", ["Stamlo-T 5", "Stamlo Beta once daily", "StamloBeta once daily", "Stamlo-5 Beta once daily", "Stamlo 5 Beta", "Storvas-EZ 10", "Pantocid-D"])
def test_b6_every_spelling_of_an_unlisted_suffix_is_kept_and_flagged(text, ch):
    got = intake.propose(text, ch)
    assert len(got) == 1 and got[0].get("possible_combination") and got[0]["brand"] == got[0]["possible_combination"], (text, got)


@pytest.mark.parametrize("text", ["Stamlo 5 mg", "Stamlo 5 once daily", "Stamlo 5 BD", "Dolo 650 SR", "Glycomet 500 XR", "Telma 40", "Crocin od", "Atorva 20 mg at night"])
def test_a_plain_brand_with_a_strength_or_a_formulation_word_is_not_a_possible_combination(text, ch):
    got = intake.propose(text, ch)
    assert got and not any(p.get("possible_combination") for p in got), (text, [(p["drug_candidates"][0]["name"], p.get("possible_combination")) for p in got])


def test_a_generic_synonym_is_not_a_brand_and_a_typed_generic_has_no_brand(ch):
    assert not intake.propose("paracetamol 500 mg twice daily", ch)[0].get("brand")
    assert not intake.propose("atorvastatin 20 mg at night", ch)[0].get("brand")
    assert intake.propose("Storvas 10 mg at night", ch)[0]["brand"] == "storvas"


async def test_a_one_ingredient_brand_keeps_its_brand_on_today_and_does_not_become_a_combination_row(gm, ch):
    from datetime import date
    from carecircle import schedule as s
    t, a = await circle(gm)
    await a.care_set_timezone("Asia/Kolkata")
    _, r = await save(a, "Storvas 10 mg at night", ch)
    await a.care_schedule_set(r["id"], ["21:00"])
    day = date(2026, 9, 20)
    await a.care_record("asha", "atorvastatin", dose_text="10 mg", freq_text="at night", source_type="typed", product="storvas", at=s.slot_moment_ms(day, "00:00", "Asia/Kolkata"))
    row = (await a.care_today("asha", s.slot_moment_ms(day, "20:00", "Asia/Kolkata")))["items"][0]
    assert row["drug"] == "atorvastatin" and row.get("brand") == "storvas" and "label" not in row and "ingredients" not in row and row["dose_text"] == "10 mg"


async def test_the_brand_is_hashed_into_the_log_like_any_product(gm, ch):
    t, a = await circle(gm)
    await save(a, "Storvas 10 mg at night", ch)
    v = await a.care_chain_verify()
    assert v["ok"] is True and v["entries_logged"] == 1
