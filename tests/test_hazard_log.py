"""docs/HAZARDS.md is only worth having if every hazard in it is tied to a test that exists. A row without a real test fails here."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOG = (ROOT / "docs" / "HAZARDS.md").read_text(encoding="utf-8")


def rows():
    return [r for r in LOG.splitlines() if re.match(r"\| H\d+ \|", r)]


def test_there_are_hazards_and_each_names_a_test():
    rs = rows()
    assert len(rs) >= 16
    for r in rs:
        assert re.search(r"`(tests/\w+\.py::\w+|web/src/[\w/.]+\.test\.ts)", r), f"no test named in: {r[:60]}"
    ids = [re.match(r"\| (H\d+) \|", r).group(1) for r in rs]
    assert len(ids) == len(set(ids)), "a hazard id is used twice"


def test_every_named_test_exists():
    for r in rows():
        for path, name in re.findall(r"`(tests/\w+\.py)::(\w+)`", r):
            src = (ROOT / path).read_text(encoding="utf-8")
            assert re.search(rf"^(async )?def {name}\b", src, re.M), f"{path}::{name} does not exist (row {r[:30]})"
        for path in re.findall(r"`(web/src/[\w/.]+\.test\.ts)", r):
            assert (ROOT / path).exists(), path


# Hazards the log called "caught" while a review still reproduced the failure. A row that names only a test that exists proves nothing about coverage, so
# for these the row must keep naming the test that reproduces the exact failure that was found. This does not prove a row is complete; it stops a row that
# once failed in review from quietly losing the test that pinned it.
REPRODUCTIONS = {
    "H1": ["tests/test_brands.py::test_no_ingredient_is_lost_to_the_order_of_the_lines",
           "tests/test_brands.py::test_a_known_brand_with_an_unlisted_suffix_is_flagged_not_read_as_the_plain_brand",
           "tests/test_brands.py::test_a_four_line_prescription_loses_nothing_and_the_unlisted_one_is_flagged"],
    "H3": ["tests/test_carecircle.py::test_a_two_medicine_quote_cannot_lend_one_strength_to_the_other",
           "tests/test_carecircle.py::test_the_rule_reading_wins_when_a_model_disagrees_on_a_strength"],
    "H6": ["tests/test_care_schedule.py::test_two_gives_sent_together_with_no_times_set_are_one_dose",
           "tests/test_care_schedule.py::test_the_same_ingredient_from_two_products_keeps_its_own_times_and_one_guard"],
    "H17": ["tests/test_carecircle.py::test_bot_saves_a_combination_as_its_own_product_and_never_over_a_plain_entry",
            "tests/test_care_schedule.py::test_a_combination_is_one_row_with_its_name_and_strength_and_one_tick",
            "tests/test_brands.py::test_no_ingredient_is_lost_to_the_order_of_the_lines"],
    "H21": ["tests/test_reminders.py::test_a_web_push_the_service_refused_is_handed_back_and_delivered_on_the_next_pass"],
}


def test_hazards_that_failed_in_review_name_the_test_that_reproduces_the_failure():
    by_id = {re.match(r"\| (H\d+) \|", r).group(1): r for r in rows()}
    for hid, tests in REPRODUCTIONS.items():
        for t in tests:
            assert f"`{t}`" in by_id[hid], f"{hid} no longer names {t}"
            path, name = t.split("::")
            assert re.search(rf"^(async )?def {name}\b", (ROOT / path).read_text(encoding="utf-8"), re.M), f"{t} does not exist"
