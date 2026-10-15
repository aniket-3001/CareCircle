import math, pytest
from carecircle import risk, reference
from carecircle.checks import Checker


def test_noisy_or_and_decay():
    assert risk.regimen_risk([]) == 0.0
    assert risk.regimen_risk([0.7, 0.3]) == pytest.approx(1 - 0.3 * 0.7, abs=1e-4)
    assert risk.decay(0) == 1.0 and risk.decay(72) == pytest.approx(0.5)
    assert risk.severity_weight("Unknown") is None and risk.severity_weight("Major") == 0.7
    assert 0 < risk.divergence([0.7], [10]) < risk.divergence([0.7], [200]) <= 1


def test_fda_parse():
    f = reference.parse_fda_cyp(open(reference.DATA / "fda_cyp.html", encoding="utf-8", errors="ignore").read())
    assert ("clarithromycin", "CYP3A", "strong") in f["inhibits"]
    assert ("warfarin", "CYP2C9") in f["substrates"]            # S-warfarin footnote stripped


@pytest.fixture(scope="module")
def chk():
    return Checker()


def test_direct_flag_and_unknown_not_safe(chk):
    r = chk.check(["Simvastatin", "Clarithromycin", "metformin"])
    assert any(x["level"] == "major" and set(x["drugs"]) == {"clarithromycin", "simvastatin"} for x in r["direct"])
    assert r["regimen_risk"] >= 0.7 and "not a statement of safety" in r["notice"]


def test_enzyme_path_via_graph(chk):
    r = chk.check(["fluconazole", "warfarin"])                    # CYP2C9 moderate inhibitor + substrate
    assert any("CYP2C9" in p["path"] for p in r["enzyme_paths"])


def test_control_unrelated_and_unknown_drug(chk):
    r = chk.check(["amlodipine", "notarealdrug"])
    assert r["not_in_reference"] == ["notarealdrug"] and r["regimen_risk"] == 0.0
