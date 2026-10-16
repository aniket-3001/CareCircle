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
