"""A combination brand must never be reduced to one ingredient, and nothing that looks like a medicine may be silently dropped.

The review typed three ordinary Indian prescriptions into the live app: Telma-AM became telmisartan only, Glycomet GP became metformin only, and Shelcal
was swallowed into the line above it. Each lost ingredient left every interaction check while the card showed a "quote verified" badge."""
import pytest

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
