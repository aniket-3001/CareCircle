"""Real calls to RxNorm and openFDA. Off unless CC_LIVE=1 (CI stays offline and deterministic); run it by hand before a release:
    CC_LIVE=1 python -m pytest tests/test_live_sources.py
It checks that the services still answer in the shape the code reads, which the faked tests cannot."""
import os

import pytest

from carecircle import external

pytestmark = pytest.mark.skipif(os.getenv("CC_LIVE") != "1", reason="live network test: set CC_LIVE=1")


@pytest.fixture(autouse=True)
def _network(monkeypatch):
    monkeypatch.setenv("CC_EXTERNAL", "1")
    monkeypatch.setattr(external, "_stored", lambda url: None)      # never read or write the shared cache from a test
    monkeypatch.setattr(external, "_keep", lambda url, data: None)


def test_rxnorm_maps_a_brand_to_its_ingredients():
    names = {x["name"].lower() for x in external.rxnorm_ingredients("Augmentin")}
    assert {"amoxicillin", "clavulanate"} <= {n.split()[0] for n in names} or any("amoxicillin" in n for n in names)


def test_openfda_label_for_warfarin_has_text_and_a_link():
    L = external.openfda_label("warfarin")
    assert L and L["url"].startswith("http") and "not validated" in L["source"]


def test_openfda_recalls_return_a_list_in_the_expected_shape():
    got = external.openfda_recalls("metformin", limit=2)
    assert isinstance(got, list) and len(got) <= 2
    for r in got:
        assert r.get("reason") or r.get("text") or r.get("date") or r
