from carecircle import burden
from conftest import tid


def R(drug, freq=""):
    return {"drug": drug, "freq_text": freq}


def test_anticholinergic_count_is_a_sum_of_listed_scores_and_says_it_is_a_subset():
    out = burden.anticholinergic_count([R("cetirizine"), R("warfarin"), R("metformin"), R("oxybutynin")])
    assert out["total"] == 5 and {m["drug"] for m in out["medicines"]} == {"cetirizine", "warfarin", "oxybutynin"} and "subset" in out["statement"]
    none = burden.anticholinergic_count([R("metformin")])
    assert none["total"] == 0 and "does not mean the burden is zero" in none["statement"]


def test_regimen_load_counts_what_is_written():
    out = burden.regimen_load([R("metformin", "twice daily with food"), R("levothyroxine", "each morning on an empty stomach"), R("atorvastatin", "at bedtime"), R("vitamin d", "")])
    assert out["medicines"] == 4 and out["special_directions"] == 3 and out["times_of_day"] == 2 and "not the validated" in out["statement"]


async def test_check_reports_how_much_the_sources_cover(gm):
    t = tid(gm, "cov")
    await gm.grant("ravi", t, ("read", "write"))
    m = gm.open("ravi", t)
    for d in ("warfarin", "metformin", "ibuprofen", "paracetamolx"):
        await m.care_record("asha", d, dose_text="1 mg")
    c = (await m.care_check("asha"))["coverage"]
    assert c["in_reference"] == 3 and c["pairs_possible"] == 3 and c["pairs_listed"] + c["not_listed"] == 3 and "not been rated as safe" in c["statement"]
