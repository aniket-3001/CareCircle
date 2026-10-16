"""The graph-algorithm views over the public reference graph (carecircle/algos.py, op `care_hubs`): PageRank hubs, hazard clusters, and the degree of each medicine
inside one regimen. Needs the reference graph loaded (CI and the app load it first)."""
from conftest import tid


async def circle(gm, drugs):
    t = tid(gm, "hub")
    await gm.grant("ann", t, ("read", "write"))
    m = gm.open("ann", t)
    for d in drugs:
        await m.care_record("asha", d, dose_text="1 tablet", freq_text="daily", source_type="typed")
    return m


async def test_regimen_hubs_count_hazards_inside_the_regimen_only(gm):
    two = await (await circle(gm, ["warfarin", "clarithromycin"])).care_hubs("asha")
    rows = {r["drug"]: (r["hazards_in_regimen"], round(r["weight"], 2)) for r in two["regimen_hubs"]["rows"]}
    assert rows == {"warfarin": (1, 0.7), "clarithromycin": (1, 0.7)}                  # the one major pair, seen from each end
    three = await (await circle(gm, ["warfarin", "clarithromycin", "metformin"])).care_hubs("asha")
    rows = {r["drug"]: (r["hazards_in_regimen"], round(r["weight"], 2)) for r in three["regimen_hubs"]["rows"]}
    assert rows == {"warfarin": (2, 1.0), "clarithromycin": (2, 1.0), "metformin": (2, 0.6)}      # metformin is moderate with both (0.3 each); the major pair weighs 0.7
    assert "HAZARD" in three["regimen_hubs"]["cypher"]


async def test_global_hubs_are_a_real_pagerank_over_the_reference_graph(gm):
    m = await circle(gm, ["warfarin"])
    g = (await m.care_hubs("asha"))["global_hubs"]
    scores = [r["score"] for r in g["rows"]]
    assert len(scores) == 10 and scores == sorted(scores, reverse=True) and all(s > 0 for s in scores)
    assert len({r["drug"] for r in g["rows"]}) == 10 and "algo.pageRank" in g["cypher"]
    assert all(0 < x < 1 for x in scores)                                            # PageRank scores are shares of a total of 1


async def test_an_empty_regimen_has_no_hubs_and_no_error(gm):
    t = tid(gm, "hub-empty")
    await gm.grant("ann", t, ("read", "write"))
    h = await gm.open("ann", t).care_hubs("asha")
    assert h["regimen_hubs"]["rows"] == [] and len(h["global_hubs"]["rows"]) == 10
