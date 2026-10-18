"""The graph algorithms do work the product uses: flags are read most-connected first, the record's dependence on each carer has a number and finds flags no carer
holds whole, and the medicines on record are grouped by the enzyme they share. Round 3 called the algorithms decorative; each of these changes what a carer reads."""
import json

from conftest import tid
from carecircle.algos import group_pathways, order_flags


# ------------------------------------------------------------------ pure functions: synthetic data, so the expectation does not depend on the reference data
def flags():
    return {
        "direct": [{"kind": "direct", "drugs": ["a", "b"], "level": "moderate", "source": "s"}, {"kind": "direct", "drugs": ["c", "d"], "level": "moderate", "source": "s"},
                   {"kind": "direct", "drugs": ["b", "c"], "level": "major", "source": "s"}, {"kind": "direct", "drugs": ["a", "e"], "level": "minor", "source": "s"}],
        "unrated": [{"kind": "direct", "drugs": ["a", "e"], "level": "unknown", "source": "s"}, {"kind": "direct", "drugs": ["b", "d"], "level": "unknown", "source": "s"}],
        "enzyme_paths": [{"x": "a", "y": "b", "enzyme": "CYP3A", "strength": "in vitro"}, {"x": "c", "y": "d", "enzyme": "CYP3A", "strength": "strong"},
                         {"x": "a", "y": "e", "enzyme": "CYP2D6", "strength": "strong"}],
    }


HUBS = {"rows": [{"drug": "a", "weight": 0.5}, {"drug": "b", "weight": 2.0}, {"drug": "c", "weight": 1.5}, {"drug": "d", "weight": 0.2}, {"drug": "e", "weight": 0.0}]}


def test_flags_are_read_by_severity_then_by_how_connected_the_pair_is_and_none_is_added_or_dropped():
    res = flags()
    before = {json.dumps(f, sort_keys=True) for k in res for f in res[k]}
    order_flags(res, HUBS)
    assert [(f["drugs"], f["level"]) for f in res["direct"]] == [(["b", "c"], "major"), (["a", "b"], "moderate"), (["c", "d"], "moderate"), (["a", "e"], "minor")]       # (a,b) 2.5 before (c,d) 1.7
    assert [f["centrality"] for f in res["direct"]] == [3.5, 2.5, 1.7, 0.5]
    assert [f["drugs"] for f in res["unrated"]] == [["b", "d"], ["a", "e"]]
    assert [(f["enzyme"], f["x"]) for f in res["enzyme_paths"]] == [("CYP3A", "c"), ("CYP2D6", "a"), ("CYP3A", "a")]                                                    # strong before in vitro, then most connected
    after = {json.dumps({k: v for k, v in f.items() if k != "centrality"}, sort_keys=True) for k in res for f in res[k]}
    assert after == before                                                                                                                                         # the same flags, only reordered and numbered


def test_a_less_severe_flag_never_outranks_a_more_severe_one_however_connected():
    res = {"direct": [{"kind": "direct", "drugs": ["x", "y"], "level": "minor", "source": "s"}, {"kind": "direct", "drugs": ["p", "q"], "level": "major", "source": "s"}],
           "unrated": [], "enzyme_paths": []}
    order_flags(res, {"rows": [{"drug": "x", "weight": 9.0}, {"drug": "y", "weight": 9.0}, {"drug": "p", "weight": 0.1}, {"drug": "q", "weight": 0.1}]})
    assert [f["level"] for f in res["direct"]] == ["major", "minor"]


def test_ordering_is_deterministic_for_ties():
    a, b = flags(), flags()
    b["direct"].reverse()
    order_flags(a, {"rows": []})
    order_flags(b, {"rows": []})
    assert [f["drugs"] for f in a["direct"]] == [f["drugs"] for f in b["direct"]]


def test_pathways_group_the_medicines_that_share_an_enzyme_and_say_who_acts_on_it():
    rows = [("CYP3A", "enzyme", "atorvastatin", "SUBSTRATE_OF", None, "FDA"), ("CYP3A", "enzyme", "amlodipine", "SUBSTRATE_OF", None, "FDA"),
            ("CYP3A", "enzyme", "clarithromycin", "INHIBITS", "strong", "FDA"), ("CYP2D6", "enzyme", "codeine", "SUBSTRATE_OF", None, "FDA"),
            ("OCT2", "transporter", "metformin", "SUBSTRATE_OF", None, "FDA"), ("OCT2", "transporter", "cimetidine", "INHIBITS", "in vitro", "FDA")]
    out = group_pathways(rows, ["atorvastatin", "amlodipine", "clarithromycin", "codeine", "metformin", "cimetidine", "vitamin d"])
    assert [(g["enzyme"], g["kind"], g["drugs"], g["acting"]) for g in out["groups"]] == [
        ("CYP3A", "enzyme", ["amlodipine", "atorvastatin", "clarithromycin"], ["clarithromycin"]), ("OCT2", "transporter", ["cimetidine", "metformin"], ["cimetidine"])]
    assert "amlodipine, atorvastatin and clarithromycin all share CYP3A (clarithromycin slows or speeds it up)" == out["groups"][0]["meaning"]
    assert out["uncovered"] == ["vitamin d"] and "codeine" in out["covered"]                                    # a lone medicine on CYP2D6 is covered but shares nothing; the uncovered are named


def test_nothing_shared_is_an_empty_list_and_the_uncovered_are_still_named():
    out = group_pathways([("CYP2D6", "enzyme", "codeine", "SUBSTRATE_OF", None, "FDA")], ["codeine", "vitamin d"])
    assert out["groups"] == [] and out["uncovered"] == ["vitamin d"]


# ------------------------------------------------------------------ against the real database and reference graph
async def circle(gm):
    t = tid(gm, "gw")
    for a in ("gw-a", "gw-b"):
        await gm.grant(a, t, ("read", "write", "admin"))
    return t, gm.open("gw-a", t), gm.open("gw-b", t)


async def test_the_real_check_reads_the_most_connected_flag_first_within_a_severity_and_the_verdict_is_unchanged(gm):
    t, a, b = await circle(gm)
    for d in ("warfarin", "clarithromycin", "atorvastatin", "amlodipine", "metformin", "simvastatin"):
        await a.care_record("asha", d, dose_text="1 mg", freq_text="daily")
    chk = await a.care_check("asha")
    for level in ("major", "moderate"):
        same = [f for f in chk["direct"] if f["level"].lower() == level]
        assert same and [f["centrality"] for f in same] == sorted((f["centrality"] for f in same), reverse=True), level
    hubs = {r["drug"]: r["weight"] for r in (await a.care_hubs("asha"))["regimen_hubs"]["rows"]}
    top = chk["direct"][0]
    assert top["level"].lower() == "major" and top["centrality"] == round(sum(hubs.get(d, 0) for d in top["drugs"]), 2)
    assert hubs["clarithromycin"] == max(hubs.values()) and "clarithromycin" in top["drugs"]                          # the medicine in the most lines leads
    # ordering adds or drops nothing: the same set of pairs a plain check of the same medicines finds
    from graphmem.care import checker
    plain = checker().check([r["drug"] for r in chk["regimen"]])
    assert {tuple(sorted(f["drugs"])) for f in chk["direct"]} == {tuple(sorted(f["drugs"])) for f in plain["direct"]}
    assert chk["judgement"]["state"] == "flags"


async def test_the_pathways_view_finds_the_shared_route_in_a_real_regimen(gm):
    t, a, b = await circle(gm)
    for d in ("atorvastatin", "clarithromycin", "amlodipine", "vitamin d"):
        await a.care_record("asha", d, dose_text="1 mg", freq_text="daily")
    p = (await a.care_hubs("asha"))["pathways"]
    cyp = next(g for g in p["groups"] if g["enzyme"] == "CYP3A")
    assert {"atorvastatin", "clarithromycin", "amlodipine"} <= set(cyp["drugs"]) and "clarithromycin" in cyp["acting"]
    assert "vitamin d" in p["uncovered"] and "MATCH (d:Drug)" in p["cypher"]


async def test_dependence_counts_the_lone_entries_of_each_carer_and_finds_the_flags_no_carer_holds_whole(gm):
    t, a, b = await circle(gm)
    await a.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime")
    await b.care_record("asha", "clarithromycin", dose_text="500 mg", freq_text="twice daily")
    dep = await a.care_dependence("asha")
    assert set(dep["carers"]) == {"gw-a", "gw-b"}
    assert [x["drug"] for x in dep["carers"]["gw-a"]["sole"]] == ["warfarin"] and [x["drug"] for x in dep["carers"]["gw-b"]["sole"]] == ["clarithromycin"]
    assert all(v["score"] >= 1.0 for v in dep["carers"].values())
    pair = [s for s in dep["split_flags"] if set(s["drugs"]) == {"warfarin", "clarithromycin"}]
    assert len(pair) == 1 and pair[0]["knows_both"] == [] and "no carer knows both" in pair[0]["meaning"]
    # once Meena (gw-b) has seen the warfarin entry, she holds both halves and the flag is no longer split
    await b.care_ack(next(r["id"] for r in await a.care_regimen("asha") if r["drug"] == "warfarin"))
    after = await a.care_dependence("asha")
    assert [s for s in after["split_flags"] if set(s["drugs"]) == {"warfarin", "clarithromycin"}] == []
    assert [x["drug"] for x in after["carers"]["gw-a"]["sole"]] == [] and [x["drug"] for x in after["carers"]["gw-b"]["sole"]] == ["clarithromycin"]
    assert after["keystone"] == "gw-b"


async def test_a_lone_entry_that_sits_in_more_interaction_lines_weighs_more(gm):
    t, a, b = await circle(gm)
    await a.care_record("asha", "clarithromycin", dose_text="500 mg", freq_text="daily")          # known only to gw-a, and in many lines with the others
    await b.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily")               # known only to gw-b
    for d in ("atorvastatin", "amlodipine", "simvastatin"):
        e = (await b.care_record("asha", d, dose_text="1 mg", freq_text="daily"))["id"]
        await a.care_ack(e)                                                                         # shared by both
    dep = await a.care_dependence("asha")
    cl = next(x for x in dep["carers"]["gw-a"]["sole"] if x["drug"] == "clarithromycin")
    mf = next(x for x in dep["carers"]["gw-b"]["sole"] if x["drug"] == "metformin")
    assert cl["weight"] > mf["weight"] >= 1.0 and cl["connected"] > mf["connected"]
    assert dep["keystone"] == "gw-a"


async def test_dependence_is_empty_for_one_carer_and_needs_read_access_only(gm):
    from graphmem import ops
    from graphmem.policy import PermissionDenied
    import pytest
    t = tid(gm, "gw1")
    await gm.grant("only", t, ("read", "write", "admin"))
    await gm.grant("ro", t, ("read",))
    m = gm.open("only", t)
    await m.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily")
    dep = await m.care_dependence("asha")
    assert dep["keystone"] is None and dep["split_flags"] == []                                        # one carer: nobody else exists to be behind
    assert ops.OPS["care_dependence"] == "read"
    assert (await ops.invoke(gm, "ro", t, "care_dependence", {"person": "asha"}))["keystone"] is None
    with pytest.raises(PermissionDenied):
        await ops.invoke(gm, "nobody", t, "care_dependence", {"person": "asha"})


async def test_the_circle_graph_draws_a_route_that_two_of_her_medicines_share_even_when_nothing_is_flagged_on_it(gm):
    t, a, b = await circle(gm)
    for d in ("atorvastatin", "amlodipine"):                                                    # two medicines cleared by the same enzyme; neither slows it
        await a.care_record("asha", d, dose_text="1 mg", freq_text="daily")
    g = await a.care_graph("asha")
    nodes = g["nodes"] if isinstance(g["nodes"], list) else list(g["nodes"].values())
    enz = [n for n in nodes if n["kind"] == "enzyme"]
    assert [n["label"] for n in enz] == ["CYP3A"], [n["label"] for n in enz]
    assert any(m[0] == "Medicines on record that share it" and "atorvastatin and amlodipine share CYP3A" in m[1].replace("amlodipine and atorvastatin", "atorvastatin and amlodipine") for m in enz[0]["meta"])
    ids = {e["id"] for e in g["edges"]}
    assert {"drug:atorvastatin>substrate>enzyme:CYP3A", "drug:amlodipine>substrate>enzyme:CYP3A"} <= ids
    assert len(ids) == len(g["edges"])                                                            # no edge is drawn twice
