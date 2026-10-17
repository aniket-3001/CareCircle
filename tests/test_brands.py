"""A combination brand must never be reduced to one ingredient, and nothing that looks like a medicine may be silently dropped.

The review typed three ordinary Indian prescriptions into the live app: Telma-AM became telmisartan only, Glycomet GP became metformin only, and Shelcal
was swallowed into the line above it. Each lost ingredient left every interaction check while the card showed a "quote verified" badge."""
import pytest

from conftest import tid

from carecircle import brands, intake
from carecircle.checks import Checker


@pytest.fixture(scope="module")
def ch():
    return Checker()


def names(props):
    return [p["drug_candidates"][0]["name"] for p in props]


@pytest.mark.parametrize("text,expected", [
    ("Telma-AM 40 mg once daily", ["telmisartan", "amlodipine"]),
    ("TELMA AM 40", ["telmisartan", "amlodipine"]),
    ("telmaam", ["telmisartan", "amlodipine"]),
    ("Glycomet GP 2 twice daily", ["metformin", "glimepiride"]),
    ("Glycomet-GP 1", ["metformin", "glimepiride"]),
    ("Ecosprin AV 75 once daily", ["acetylsalicylic acid", "atorvastatin"]),
    ("Ecosprin Gold 10", ["acetylsalicylic acid", "atorvastatin", "clopidogrel"]),
    ("Shelcal 500 once daily", ["calcium carbonate", "cholecalciferol"]),
    ("Augmentin 625 twice daily", ["amoxicillin", "clavulanic acid"]),
    ("Combiflam when needed", ["ibuprofen", "acetaminophen"]),
])
def test_a_combination_brand_gives_every_one_of_its_ingredients(ch, text, expected):
    got = names(intake.rule_proposals(text, ch))
    assert got == expected, (text, got)


def test_the_reviews_three_prescriptions_typed_together_lose_nothing(ch):
    text = "Telma-AM 40 mg once daily\nGlycomet GP 2 twice daily\nShelcal 500 once daily"
    props = intake.rule_proposals(text, ch)
    assert names(props) == ["telmisartan", "amlodipine", "metformin", "glimepiride", "calcium carbonate", "cholecalciferol"]
    glycomet = [p for p in props if p.get("combination") == "Glycomet-GP"]
    assert all("Shelcal" not in p["quote"] for p in glycomet)             # Shelcal's line was swallowed into Glycomet's quote before
    assert all(p["method"] == "brand list" and p["combination_ingredients"] for p in props)


def test_a_strength_printed_beside_a_combination_is_not_copied_onto_one_ingredient(ch):
    props = intake.rule_proposals("Telma-AM 40 mg once daily", ch)
    assert [p["dose_text"] for p in props] == ["", ""] and {p["combination_strength"] for p in props} == {"40 mg"}
    assert {p["freq_text"] for p in props} == {"once daily"}


def test_an_ingredient_the_reference_data_lacks_is_kept_and_marked_unchecked(ch):
    props = intake.rule_proposals("Zerodol-P twice daily", ch)
    by = {p["drug_candidates"][0]["name"]: p["drug_candidates"][0] for p in props}
    assert set(by) == {"aceclofenac", "acetaminophen"}
    assert by["aceclofenac"].get("unchecked") is True and not by["acetaminophen"].get("unchecked")


def test_a_brand_inside_a_longer_word_is_not_a_brand():
    assert brands.find("Augmentation of the schedule") == []
    assert [b[0] for b in brands.find("take Augmentin and Combiflam")] == ["Augmentin", "Combiflam"]


def test_a_line_that_looks_like_a_medicine_but_is_unknown_becomes_an_unchecked_proposal(ch):
    props = intake.rule_proposals("Becosules 1 daily\nUnknowmed 250 mg twice daily", ch)
    assert names(props) == ["becosules", "unknowmed"]
    assert all(p["drug_candidates"][0]["unchecked"] for p in props)
    assert props[1]["dose_text"] == "250 mg" and props[1]["freq_text"] == "twice daily"


@pytest.mark.parametrize("prose", [
    "Take one tablet every morning with water and food. Bring the prescription tomorrow evening.",
    "Take ONE tablet daily at bedtime", "Qty 30\nRefills: 2\nDr A. Sample", "CITY PHARMACY\nStore at room temperature", "Rx only",
])
def test_ordinary_label_text_is_not_turned_into_medicines(ch, prose):
    assert intake.rule_proposals(prose, ch) == []


def test_known_single_ingredient_labels_behave_as_before(ch):
    props = intake.rule_proposals("Warfarin Sodium 5 mg tablets\nTake ONE tablet daily at bedtime", ch)
    assert names(props) == ["warfarin"] and props[0]["dose_text"] == "5 mg" and props[0]["freq_text"].lower() == "daily"
    assert "combination" not in props[0] and "unchecked" not in props[0]["drug_candidates"][0]


def test_what_goes_to_the_model_has_no_names_numbers_or_addresses_but_keeps_the_medicine_lines():
    from carecircle.intake import redact_identifiers
    text = "Patient: Asha Rao\nAge 71 F\nPh 98765 43210\nDr. Mehta MBBS, mehta@clinic.in\nTab Telma-AM 40/5 once daily\nWarfarin 5 mg at bedtime\nAddress: 12 Park Road, Delhi"
    out = redact_identifiers(text)
    for gone in ("Asha", "Rao", "71", "98765", "Mehta", "mehta@", "Park Road"):
        assert gone not in out, gone
    assert "Tab Telma-AM 40/5 once daily" in out and "Warfarin 5 mg at bedtime" in out


async def test_the_medicine_list_can_be_searched_by_part_of_a_name(gm):
    t = tid(gm, "srch")
    await gm.grant("ravi", t, ("read",))
    m = gm.open("ravi", t)
    got = [x["name"] for x in await m.care_drug_search("simvast")]
    assert "simvastatin" in got and all("simvast" in n for n in got)
    starts = [x["name"] for x in await m.care_drug_search("metf")]
    assert starts and starts[0].startswith("metf")
    assert await m.care_drug_search("s") == [] and await m.care_drug_search("zzzzqqq") == []


def test_only_text_is_ever_sent_to_a_model_never_the_picture_and_never_an_identity_line(monkeypatch):
    """A prescription photo shows the patient's and the doctor's names. The OCR text is all a model needs, so what leaves the server is that text with identity lines removed."""
    sent = []

    class FakeClient:
        def converse(self, **kw):
            sent.append(kw)
            return {"output": {"message": {"content": [{"text": '{"items": []}'}]}}}
    import sys
    import types
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda *a, **k: FakeClient()))
    monkeypatch.setenv("CC_LLM", "1")
    text = "Patient: Asha Rao\nAge 71 F\nPh 98765 43210\nDr. Mehta MBBS\nTab Telma-AM 40/5 once daily"
    import inspect
    assert "image" not in inspect.signature(intake.llm_proposals).parameters and "image" not in inspect.signature(intake.propose).parameters
    intake.llm_proposals(text)
    assert len(sent) == 1
    blocks = [b for m in sent[0]["messages"] for b in m["content"]]
    assert all(set(b) == {"text"} for b in blocks), "a block other than plain text was sent"
    body = blocks[0]["text"]
    assert "Telma-AM 40/5 once daily" in body
    for gone in ("Asha", "Rao", "71", "98765", "Mehta"):
        assert gone not in body.split("SOURCE TEXT:")[1], gone


def test_every_listed_brand_names_two_or_more_ingredients_and_is_found_on_its_own():
    """The table is for combinations: a one-ingredient row would only rename a medicine. Each brand must be found whatever its case, spacing or hyphen."""
    from carecircle.brands import COMBINATIONS, find
    assert len(COMBINATIONS) >= 50
    for brand, ing in COMBINATIONS.items():
        if brand == "Calcirol-D3":                       # a single-ingredient row kept from the first list
            continue
        assert len(ing) >= 2 and len(set(ing)) == len(ing), brand
        for spelling in (brand, brand.upper(), brand.lower().replace("-", " "), brand.replace("-", "")):
            assert [b[0] for b in find(f"Tab {spelling} 1 daily")][:1] == [brand], spelling


def test_a_known_brand_with_an_unlisted_suffix_is_flagged_not_read_as_the_plain_brand():
    """Stamlo-T, Storvas-EZ, Pantocid-D ... are usually combinations; reading them as the one-ingredient brand lost the other ingredient with no sign of it."""
    from carecircle import intake
    ch = Checker()
    for text, ing in [("Stamlo-T 5", "amlodipine"), ("Storvas-EZ 10", "atorvastatin"), ("Atorva-F 10", "atorvastatin"), ("Rosuvas-F 10", "rosuvastatin"),
                      ("Pantocid-D", "pantoprazole"), ("Omez-DSR", "omeprazole"), ("Cipro-TZ", "ciprofloxacin")]:
        got = intake.propose(text, ch)
        assert [(p["drug_candidates"][0]["name"], bool(p.get("possible_combination"))) for p in got] == [(ing, True)], text
    for text in ("Dolo 650", "Telma 40", "Glycomet tab", "Crocin od", "Stamlo 5 mg", "Telma-H 40"):        # plain brands, and a listed combination: no warning
        assert not [p for p in intake.propose(text, ch) if p.get("possible_combination")], text


def test_no_listed_combination_loses_an_ingredient_on_a_multi_line_prescription():
    """Every listed brand, in turn with every other, one per line with dose and timing lines between: all ingredients come out."""
    import itertools
    from carecircle import intake
    ch = Checker()
    for (a, ia), (b, ib) in itertools.combinations(brands.COMBINATIONS.items(), 2):
        text = f"1. {a}\n   40/5\n   once daily\n2. {b}\n   at night"
        got = {(p["combination"], p["drug_candidates"][0]["name"]) for p in intake.rule_proposals(text, ch) if p.get("combination")}
        assert got == {(a, i) for i in ia} | {(b, i) for i in ib}, text


def test_the_brand_table_the_reader_uses_is_the_one_in_the_reference_graph(ch):
    """Brands are (:Brand)-[:CONTAINS {pos}]->(:Ingredient)-[:IS]->(:Drug) in cc_ref and the matcher reads them from there; the dict is only the loader's source."""
    assert ch.load_brands() == len(brands.COMBINATIONS) and brands.FROM_GRAPH
    for b, ings in brands.COMBINATIONS.items():
        got = [r[0] for r in ch.g.ro_query("MATCH (:Brand {name:$b})-[c:CONTAINS]->(i:Ingredient) RETURN i.name ORDER BY c.pos", {"b": b}).result_set]
        assert got == ings, b
    rows = ch.g.ro_query("MATCH (b:Brand {name:'Telma-AM'})-[c:CONTAINS]->(i:Ingredient) RETURN i.name ORDER BY c.pos").result_set
    assert [r[0] for r in rows] == ["telmisartan", "amlodipine"]
    assert {x["brand"] for x in ch.brands_containing("amlodipine")} >= {"Telma-AM", "Concor-AM"}
    linked = ch.g.ro_query("MATCH (:Ingredient {name:'telmisartan'})-[:IS]->(d:Drug) RETURN d.name").result_set
    assert linked == [["telmisartan"]]


def test_a_brand_added_only_to_the_graph_is_found_by_the_reader(ch):
    ch.g.query("MERGE (b:Brand {key:'zzcombo'}) SET b.name='Zzcombo' WITH b MERGE (i:Ingredient {name:'metformin'}) CREATE (b)-[:CONTAINS {pos:0}]->(i)")
    try:
        ch.load_brands()
        assert [f[0] for f in brands.find("Zzcombo 10 mg")] == ["Zzcombo"]
    finally:
        ch.g.query("MATCH (b:Brand {key:'zzcombo'}) DETACH DELETE b")
        ch.load_brands()


@pytest.mark.parametrize("text, kept", [
    ("Telma-AM 40 once daily\nAmlodipine 5 mg at night", {("Telma-AM", "telmisartan"), ("Telma-AM", "amlodipine"), ("", "amlodipine")}),
    ("Amlodipine 5 mg at night\nTelma-AM 40 once daily", {("Telma-AM", "telmisartan"), ("Telma-AM", "amlodipine"), ("", "amlodipine")}),
    ("Glycomet-GP 1\nMetformin 500 mg twice daily", {("Glycomet-GP", "metformin"), ("Glycomet-GP", "glimepiride"), ("", "metformin")}),
    ("Metformin 500 mg twice daily\nGlycomet-GP 1", {("Glycomet-GP", "metformin"), ("Glycomet-GP", "glimepiride"), ("", "metformin")}),
    ("Shelcal\nCalcirol-D3\nOnce weekly", {("Shelcal", "calcium carbonate"), ("Shelcal", "cholecalciferol"), ("Calcirol-D3", "cholecalciferol")}),
    ("Telma 40 AM\nonce daily", {("Telma-AM", "telmisartan"), ("Telma-AM", "amlodipine")}),
])
def test_no_ingredient_is_lost_to_the_order_of_the_lines(text, kept):
    """A later plain line used to delete an earlier proposal for the same medicine that had no dose (a combination's ingredient never has one)."""
    got = {(p.get("combination", ""), p["drug_candidates"][0]["name"]) for p in intake.propose(text, Checker())}
    assert got == kept, text


def test_a_four_line_prescription_loses_nothing_and_the_unlisted_one_is_flagged():
    got = intake.propose("Rx\nTelma 40 AM\nonce daily\nStamlo Beta\n1 tab night", Checker())
    names = {(p.get("combination", ""), p["drug_candidates"][0]["name"]) for p in got}
    assert {("Telma-AM", "telmisartan"), ("Telma-AM", "amlodipine")} <= names
    assert any(p.get("possible_combination") == "Stamlo Beta" for p in got)        # the one the table does not list is flagged, not dropped
