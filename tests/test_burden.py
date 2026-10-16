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


async def test_reading_stats_count_corrections_without_keeping_text(gm):
    t = tid(gm, "rs")
    await gm.grant("ravi", t, ("read", "write"))
    m = gm.open("ravi", t)
    src = "Warfarin 4 mg every evening"
    await m.care_record("asha", "warfarin", dose_text="4 mg", source_type="photo", quote="Warfarin 4 mg", source_ref=await m.care_store_source("image", src))
    await m.care_record("asha", "metformin", dose_text="500 mg", source_type="voice", quote="metformin 500 mg", source_ref=await m.care_store_source("voice", "metformin 500 mg"), edited="dose")
    await m.care_record("asha", "vitamin d", dose_text="1000 iu")                      # typed: not a reading
    s = await m.care_reading_stats("asha")
    assert (s["saved"], s["unchanged"]) == (2, 1) and "1 were saved exactly as read" in s["statement"] and set(s["by_source"]) == {"photo", "voice"}
    assert (await m.care_summary_counts("asha"))["reading"]["saved"] == 2
