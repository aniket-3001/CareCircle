"""One molecule, one node. A brand's ingredient, a class member and the (:Drug) the interactions hang on are linked, so questions that used to need three queries
stitched together by name strings are one traversal, and the path is the explanation (round 3, FalkorDB usage)."""
from conftest import tid
from carecircle.checks import Checker


def ch():
    return Checker()


def test_every_class_member_and_ingredient_that_the_interaction_data_knows_is_linked_to_its_drug():
    c = ch()
    known = {r[0] for r in c.g.ro_query("MATCH (d:Drug) RETURN d.name").result_set}
    for label in ("Member", "Ingredient"):
        names = {r[0] for r in c.g.ro_query(f"MATCH (n:{label}) RETURN n.name").result_set}
        linked = {r[0] for r in c.g.ro_query(f"MATCH (n:{label})-[:IS]->(:Drug) RETURN n.name").result_set}
        assert names & known == linked, (label, sorted((names & known) - linked)[:5])           # exactly the ones the data knows are linked
    assert c.g.ro_query("MATCH (:Member)-[:IS]->(d:Drug) RETURN count(DISTINCT d)").result_set[0][0] > 300


def test_which_packs_contain_a_medicine_in_a_class_is_one_traversal_with_its_path():
    packs = ch().class_packs("penicillin")
    by = {p["brand"]: p for p in packs}
    assert "Moxikind-CV" in by and by["Moxikind-CV"]["ingredient"] == "amoxicillin"
    assert by["Moxikind-CV"]["path"] == "Moxikind-CV contains amoxicillin -> amoxicillin is in the penicillin class (WHO ATC via NLM RxClass)"
    assert ch().class_packs("a class that does not exist") == []


def test_what_the_medicines_in_a_class_interact_with_is_one_traversal():
    got = ch().class_interactions("penicillin", ["warfarin", "methotrexate", "metformin"])
    assert {(g["member"], g["with"]) for g in got} >= {("amoxicillin", "warfarin"), ("amoxicillin", "methotrexate")}
    assert all(g["source"] == "DDInter 2.0" and g["level"] for g in got)
    assert all(g["with"] in ("warfarin", "methotrexate", "metformin") for g in got)


async def test_the_allergy_check_names_the_pack_on_record_that_holds_a_medicine_in_the_class(gm):
    t = tid(gm, "mol")
    await gm.grant("mol-a", t, ("read", "write", "admin"))
    a = gm.open("mol-a", t)
    await a.care_record("asha", "amoxicillin", freq_text="twice daily", product="Moxikind-CV", product_strength="500/125 mg")
    await a.care_record("asha", "clavulanic acid", freq_text="twice daily", product="Moxikind-CV", product_strength="500/125 mg")
    await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily")
    await a.care_allergy_add("asha", "penicillin")
    got = await a.care_allergy_check("asha")
    assert {h["drug"] for h in got["hits"]} == {"amoxicillin"}
    assert [(p["product"], p["ingredient"], p["class"]) for p in got["packs"]] == [("Moxikind-CV", "amoxicillin", "penicillin")]
    assert got["packs"][0]["path"].startswith("Moxikind-CV contains amoxicillin -> amoxicillin is in the penicillin class")
    assert "ask the prescriber" in got["note"] or "prescriber" in got["note"]
