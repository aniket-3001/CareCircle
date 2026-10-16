"""docs/EXPLORE.md is only worth reading if its queries work. Seed the explore graphs, run every ```cypher block in the guide against the graph it names,
and require rows back (and the facts the guide states about them)."""
import importlib.util
import pathlib
import re

import pytest

from graphmem import Db, GraphMem

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("seed_explore", ROOT / "scripts" / "seed_explore.py")
seed_explore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_explore)

BLOCK = re.compile(r"```cypher\n// graph: (\S+)\n(.*?)```", re.S)
QUERIES = BLOCK.findall((ROOT / "docs" / "EXPLORE.md").read_text(encoding="utf-8"))


@pytest.fixture
async def seeded():
    db = Db()
    gm = GraphMem(db)
    out = await seed_explore.seed(gm)
    yield db, out
    for t in (seed_explore.CIRCLE, seed_explore.AGENTS):
        await db.drop_tenant(t)
    ctl = await gm._ctl()
    await ctl.query("MATCH (a:Agent) WHERE a.id IN ['ravi-explore','meena-explore','planner','coder'] DETACH DELETE a")
    await ctl.query("MATCH (t:Tenant) WHERE t.id IN [$a,$b] DETACH DELETE t", {"a": seed_explore.CIRCLE, "b": seed_explore.AGENTS})


def test_the_guide_has_the_queries_it_promises():
    assert len(QUERIES) >= 15
    assert {g for g, _ in QUERIES} == {"mem__explore-circle", "mem__explore-agents", "cc_ref"}


@pytest.mark.parametrize("graph,query", QUERIES, ids=[q.strip().splitlines()[0][:60] for _, q in QUERIES])
async def test_every_query_in_the_guide_runs_and_returns_rows(seeded, graph, query):
    db, _ = seeded
    res = (await db.client.select_graph(graph).ro_query(query)).result_set
    assert len(res) > 0


async def test_what_the_guide_says_about_the_seeded_data_is_true(seeded):
    db, _ = seeded
    circle = db.client.select_graph("mem__explore-circle")
    now = {r[0]: r[1] for r in (await circle.ro_query("MATCH (d:Dose {cur: true, status: 'confirmed'}) RETURN d.drug, d.dose_text")).result_set}
    assert now == {"metformin": "500 mg", "warfarin": "7 mg", "atorvastatin": "20 mg", "clarithromycin": "500 mg"}       # warfarin was changed 5 mg -> 7 mg
    unseen = (await circle.ro_query("MATCH (c:Person {role: 'carer'}), (d:Dose {cur: true}) WHERE NOT (c)-[:ACKED]->(d) AND d.by <> c.id RETURN c.id, d.drug")).result_set
    assert [tuple(r) for r in unseen] == [("meena-explore", "clarithromycin")]                                              # the one change a carer has not seen
    agents = db.client.select_graph("mem__explore-agents")
    old = (await agents.ro_query("MATCH (new:Fact)-[:SUPERSEDES]->(old:Fact) RETURN new.otext, old.otext, old.cur")).result_set
    assert [tuple(r) for r in old] == [("recovered", "failing", False)]
    ref = db.client.select_graph("cc_ref")
    assert (await ref.ro_query("MATCH (:Drug {name:'clarithromycin'})-[i:INTERACTS]-(:Drug {name:'warfarin'}) RETURN i.level")).result_set[0][0] == "major"
