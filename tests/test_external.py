"""Live public sources (RxNorm, openFDA) are used for lookups only, fail soft, and never block the app. Network is faked here."""
import pytest

from carecircle import external
from carecircle.checks import Checker
from conftest import tid


def test_disabled_by_default_in_tests_and_fails_soft(monkeypatch):
    assert external.rxnorm_ingredients("augmentin") == [] and external.openfda_label("warfarin") is None
    monkeypatch.setenv("CC_EXTERNAL", "1")
    monkeypatch.setattr(external, "_get", lambda url: None)               # service down
    assert external.rxnorm_ingredients("augmentin") == [] and external.openfda_label("warfarin") is None


def test_rxnorm_suggestions_are_kept_only_if_the_reference_graph_has_them(monkeypatch):
    monkeypatch.setenv("CC_EXTERNAL", "1")
    monkeypatch.setattr(external, "rxnorm_ingredients", lambda t: [{"name": "amoxicillin", "rxcui": "723", "source": "RxNorm (NLM)"},
                                                                   {"name": "notarealdrug", "rxcui": "1", "source": "RxNorm (NLM)"}])
    got = Checker().resolve("zzqx brandname", 3)
    assert [c["name"] for c in got] == ["amoxicillin"] and got[0]["via"] == "RxNorm (NLM)"


def test_openfda_label_is_quoted_and_sourced(monkeypatch):
    monkeypatch.setenv("CC_EXTERNAL", "1")
    monkeypatch.setattr(external, "_get", lambda url: {"results": [{"boxed_warning": ["WARNING:  BLEEDING RISK  can cause major bleeding"], "indications_and_usage": ["1 INDICATIONS AND USAGE x"],
                                                                    "effective_time": "20250617", "openfda": {"spl_set_id": ["abc"], "brand_name": ["Coumadin"]}}]})
    L = external.openfda_label("warfarin")
    assert L["boxed_warning"].startswith("BLEEDING RISK") and "abc" in L["url"] and "not validated" in L["source"]
    assert external.openfda_label('x" OR "y') is None                        # no query injection through the name


async def test_drug_info_op_reads_with_read_scope(gm, monkeypatch):
    t = tid(gm, "di")
    await gm.grant("ravi", t, ("read",))
    info = await gm.open("ravi", t).care_drug_info("Warfarin")
    assert info["drug"] == "warfarin" and info["in_interaction_reference"] and info["label"] is None and info["available"] is False


async def test_recalls_come_from_the_names_on_record_only(gm, monkeypatch):
    seen = []
    monkeypatch.setattr(external, "openfda_recalls", lambda d, limit=2: seen.append(d) or ([{"drug": d, "number": "D-1", "reason": "x"}] if d == "metformin" else []))
    t = tid(gm, "rc")
    await gm.grant("ravi", t, ("read", "write"))
    m = gm.open("ravi", t)
    await m.care_record("asha", "metformin", dose_text="500 mg")
    await m.care_record("asha", "warfarin", dose_text="4 mg")
    await m.care_set_timezone("America/New_York")                              # openFDA lists US recalls: only a US circle looks them up
    out = await m.care_recalls("asha")
    assert sorted(seen) == ["metformin", "warfarin"] and [r["number"] for r in out["recalls"]] == ["D-1"] and "not a statement about this person" in out["note"]
    assert "asha" not in repr(seen)                                           # nothing but medicine names is sent


async def test_sole_knowers_flags_what_only_one_carer_knows(gm):
    t = tid(gm, "sk")
    for c in ("ravi", "meena"):
        await gm.grant(c, t, ("read", "write", "admin"))
    ravi, meena = gm.open("ravi", t), gm.open("meena", t)
    a = await ravi.care_record("asha", "metformin", dose_text="500 mg")
    await meena.care_ack(a["id"])                                             # both know metformin
    await ravi.care_record("asha", "warfarin", dose_text="4 mg")              # only Ravi knows warfarin
    await meena.care_record("asha", "vitamin d", dose_text="1000 iu")         # makes Meena a known carer; only Meena knows it
    out = await ravi.care_sole_knowers("asha")
    assert {(x["drug"], x["only"]) for x in out["sole"]} == {("warfarin", "ravi"), ("vitamin d", "meena")}
    await meena.care_ack(next(r["id"] for r in await ravi.care_regimen("asha") if r["drug"] == "warfarin"))
    out = await ravi.care_sole_knowers("asha")
    assert [x["drug"] for x in out["sole"]] == ["vitamin d"] and out["keystone"] == "meena" and out["keystone_count"] == 1


def test_lookups_survive_a_restart_through_the_reference_graph(monkeypatch):
    monkeypatch.setenv("CC_EXTERNAL", "1")
    calls = []
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"results": [{"x": 1}]}'
    monkeypatch.setattr(external.urllib.request, "urlopen", lambda req, timeout=0: calls.append(1) or R())
    url = "https://example.test/lookup?name=cache-test-xyz"
    external._cache.clear()
    assert external._get(url) == {"results": [{"x": 1}]} and len(calls) == 1
    external._cache.clear()                                                    # a restart: the in-memory cache is gone
    assert external._get(url) == {"results": [{"x": 1}]} and len(calls) == 1   # served from the graph, no second call
    external._ref().query("MATCH (c:Cached {url:$u}) DELETE c", {"u": url})


async def test_a_circle_outside_the_us_looks_up_no_recalls_and_sends_no_name(gm, monkeypatch):
    seen = []
    monkeypatch.setattr(external, "openfda_recalls", lambda d, limit=2: seen.append(d) or [])
    t = tid(gm, "rd")
    await gm.grant("ravi", t, ("read", "write"))
    m = gm.open("ravi", t)
    await m.care_record("asha", "metformin", dose_text="500 mg")
    for tz in (None, "Asia/Kolkata", "Europe/London"):                          # the default zone is India's
        if tz:
            await m.care_set_timezone(tz)
        out = await m.care_recalls("asha")
        assert seen == [] and out["available"] is False and out["region"] == "US only" and "no medicine name was sent" in out["note"]


async def test_fhir_codes_only_exact_ingredient_matches_and_says_which(gm, monkeypatch):
    monkeypatch.setattr(external, "rxnorm_ingredients", lambda d: {"metformin": [{"name": "metformin", "rxcui": "6809"}],
                                                                   "becosules": [{"name": "thiamine", "rxcui": "10454"}]}.get(d, []))
    t = tid(gm, "fh")
    await gm.grant("ravi", t, ("read", "write"))
    m = gm.open("ravi", t)
    await m.care_record("asha", "metformin", dose_text="500 mg")
    await m.care_record("asha", "becosules", dose_text="1")                    # RxNorm offers a different name: a guess, not a match
    plain = await m.care_export_fhir("asha")
    assert plain["meta"]["tag"][0]["code"] == "free-text-only" and not any("coding" in e["resource"].get("medicationCodeableConcept", {}) for e in plain["entry"])
    got = await m.care_export_fhir("asha", coded=True)
    by = {e["resource"]["medicationCodeableConcept"]["text"]: e["resource"]["medicationCodeableConcept"] for e in got["entry"] if e["resource"]["resourceType"] == "MedicationStatement"}
    assert by["Metformin"]["coding"][0]["code"] == "6809" and "rxnorm" in by["Metformin"]["coding"][0]["system"]
    assert "coding" not in by["Becosules"]
    assert got["meta"]["tag"][0]["code"] == "coded-where-exact" and "1 of 2" in got["meta"]["tag"][0]["display"]
