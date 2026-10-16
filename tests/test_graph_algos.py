"""Graph algorithms as read-only operations on a tenant's memory graph. Every expectation is worked out by hand from a small graph built here."""
import pytest

from conftest import tid
from graphmem import ops


async def world(gm, label="ga"):
    """  hub <- a, b, c, d (four notes point at a hub);  a -> b;  chain p -> q -> r -> s;  an island x - y  """
    t = tid(gm, label)
    await gm.grant("ann", t, ("read", "write"))
    m = gm.open("ann", t)
    await m._q("""
        CREATE (hub:Entity {key:'hub', name:'Hub'}),
               (a:Entity {key:'a', name:'A'}), (b:Entity {key:'b', name:'B'}), (c:Entity {key:'c', name:'C'}), (d:Entity {key:'d', name:'D'}),
               (a)-[:LINKS]->(hub), (b)-[:LINKS]->(hub), (c)-[:LINKS]->(hub), (d)-[:LINKS]->(hub), (a)-[:LINKS]->(b),
               (p:Task {id:'p', title:'P'}), (q:Task {id:'q', title:'Q'}), (r:Task {id:'r', title:'R'}), (s:Task {id:'s', title:'S'}),
               (p)-[:THEN]->(q), (q)-[:THEN]->(r), (r)-[:THEN]->(s),
               (x:Skill {key:'x', name:'X'}), (y:Skill {key:'y', name:'Y'}), (x)-[:LINKS]->(y)""")
    return t, m


async def test_schema_counts_what_is_there(gm):
    t, m = await world(gm)
    s = await m.graph_schema()
    assert {n["label"]: n["count"] for n in s["nodes"]} == {"Entity": 5, "Task": 4, "Skill": 2}
    assert {r["type"]: r["count"] for r in s["relationships"]} == {"LINKS": 6, "THEN": 3}


async def test_shortest_path_names_every_step(gm):
    t, m = await world(gm)
    r = await m.graph_path("p", "s")
    assert r["found"] and r["length"] == 3
    assert [n["ref"] for n in r["path"]] == ["p", "q", "r", "s"] and r["relationships"] == ["THEN"] * 3
    assert r["path"][0] == {"label": "Task", "ref": "p", "title": "P"}
    back = await m.graph_path("s", "p")                                    # direction is ignored
    assert back["found"] and [n["ref"] for n in back["path"]] == ["s", "r", "q", "p"]
    near = await m.graph_path("a", "d")                                    # a - hub - d (two hops), not the long way round
    assert near["length"] == 2 and [n["ref"] for n in near["path"]] == ["a", "hub", "d"]


async def test_no_path_is_an_answer_not_an_error(gm):
    t, m = await world(gm)
    assert (await m.graph_path("p", "x"))["found"] is False                      # different islands
    far = await m.graph_path("p", "s", max_hops=2)                               # too far for the allowance
    assert far["found"] is False and "2 hops" in far["reason"]
    gone = await m.graph_path("p", "nobody")
    assert gone["found"] is False and "target" in gone["reason"]
    assert (await m.graph_path("p", "p"))["length"] == 0


async def test_influence_ranks_the_hub_first(gm):
    t, m = await world(gm)
    pr = await m.graph_influence("pagerank", label="Entity", top=3)
    assert pr["rows"][0]["ref"] == "hub" and pr["rows"][0]["score"] > pr["rows"][1]["score"]
    assert len(pr["rows"]) == 3 and "algo.pageRank" in pr["cypher"]
    hc = await m.graph_influence("harmonic", label="Task", top=10)
    assert [r["ref"] for r in hc["rows"]] == ["p", "q", "r", "s"]                 # along p -> q -> r -> s the start reaches the rest fastest, the end reaches nothing
    assert hc["rows"][-1]["score"] == 0 and "HarmonicCentrality" in hc["cypher"]
    with pytest.raises(ValueError, match="betweenness is not offered"):
        await m.graph_influence("betweenness")                                    # FalkorDB 4.22's version of it is not reliable, so it is refused, not answered


async def test_communities_find_the_islands(gm):
    t, m = await world(gm)
    c = await m.graph_communities("wcc", top=10)
    assert [g["size"] for g in c["groups"]] == [5, 4, 2]                          # entities, tasks, skills
    assert c["groups"][0]["kinds"] == {"Entity": 5} and c["nodes_in_graph"] == 11
    only = await m.graph_communities("wcc", label="Skill")
    assert [g["size"] for g in only["groups"]] == [2]
    lp = await m.graph_communities("labelpropagation", top=10)
    assert sum(g["size"] for g in lp["groups"]) == 11


async def test_neighbourhood_is_nearest_first_and_bounded(gm):
    t, m = await world(gm)
    n = await m.graph_neighbourhood("hub", depth=1)
    assert {x["ref"] for x in n["nodes"]} == {"a", "b", "c", "d"} and {x["hop"] for x in n["nodes"]} == {1}
    n2 = await m.graph_neighbourhood("p", depth=2)
    assert [(x["ref"], x["hop"]) for x in n2["nodes"]] == [("q", 1), ("r", 2)]
    capped = await m.graph_neighbourhood("hub", depth=2, limit=2)
    assert len(capped["nodes"]) == 2 and capped["truncated"]
    assert (await m.graph_neighbourhood("nobody"))["found"] is False


async def test_an_empty_graph_gives_empty_answers(gm):
    t = tid(gm, "ga-empty")
    await gm.grant("ann", t, ("read", "write"))
    m = gm.open("ann", t)
    await m.add_episode("s", "user", "one thing")                   # the graph exists but holds no relationships
    assert (await m.graph_communities())["groups"][0]["size"] >= 1
    assert (await m.graph_path("a", "b"))["found"] is False
    assert (await m.graph_influence())["rows"] is not None


@pytest.mark.parametrize("call,msg", [
    (lambda m: m.graph_influence(metric="degree"), "pagerank"),
    (lambda m: m.graph_influence(metric="betweenness"), "not offered"),
    (lambda m: m.graph_communities(method="louvain"), "wcc"),
    (lambda m: m.graph_influence(label="Nope"), "no node label"),
    (lambda m: m.graph_influence(label="Entity) DETACH DELETE (n"), "name of a node label"),
    (lambda m: m.graph_path("", "a"), "source"),
    (lambda m: m.graph_path("a", "b", max_hops="3"), "whole number"),
    (lambda m: m.graph_path("a", "b", source_label="`) MATCH (z) DELETE z //"), "name of a node label"),
    (lambda m: m.graph_neighbourhood("a" * 500), "characters"),
    (lambda m: m.graph_influence(top=True), "whole number"),
])
async def test_bad_input_is_refused_and_nothing_is_run(gm, call, msg):
    t, m = await world(gm)
    with pytest.raises(ValueError, match=msg):
        await call(m)
    assert sum(n["count"] for n in (await m.graph_schema())["nodes"]) == 11          # nothing was touched


async def test_limits_are_clamped_not_trusted(gm):
    t, m = await world(gm)
    assert len((await m.graph_influence(top=10_000))["rows"]) == 11                  # asks for 10,000, gets what exists, never more than the cap
    assert (await m.graph_path("p", "s", max_hops=10_000))["length"] == 3
    assert (await m.graph_path("p", "s", max_hops=-5))["found"] is False             # clamped up to one hop


async def test_nothing_can_be_changed_and_other_tenants_are_invisible(gm):
    t, m = await world(gm)
    other = tid(gm, "ga-other")
    await gm.grant("bob", other, ("read", "write"))
    om = gm.open("bob", other)
    await om._q("CREATE (:Entity {key:'secret', name:'Secret'})")
    assert (await m.graph_path("secret", "hub"))["found"] is False
    assert all(r["ref"] != "secret" for r in (await m.graph_influence())["rows"])
    assert (await m.graph_neighbourhood("secret"))["found"] is False


async def test_read_scope_is_enough_and_no_grant_is_refused(gm):
    t, m = await world(gm)
    await gm.grant("rita", t, ("read",))
    reader = gm.open("rita", t)
    assert (await reader.graph_path("p", "s"))["found"]
    assert (await reader.graph_influence())["rows"]
    stranger = gm.open("nobody-granted", t)
    with pytest.raises(Exception):
        await stranger.graph_schema()


async def test_the_operations_are_listed_and_callable_through_the_shared_table(gm):
    t, m = await world(gm)
    listed = ops.describe()
    for name in ("graph_schema", "graph_path", "graph_influence", "graph_communities", "graph_neighbourhood"):
        assert listed[name]["scope"] == "read" and listed[name]["doc"]
    r = await ops.invoke(gm, "ann", t, "graph_path", {"source": "p", "target": "r"})
    assert r["length"] == 2
    with pytest.raises(TypeError):
        await ops.invoke(gm, "ann", t, "graph_path", {"source": "p"})


async def test_a_big_group_still_reports_what_it_is_made_of_and_plain_data(gm):
    t = tid(gm, "ga-big")
    await gm.grant("ann", t, ("read", "write"))
    m = gm.open("ann", t)
    await m._q("CREATE (h:Entity {key:'h', name:'H'}) WITH h UNWIND range(1, 300) AS i CREATE (:Task {id:'t' + toString(i)})-[:THEN]->(h)")
    g = (await m.graph_communities("wcc"))["groups"][0]
    assert g["size"] == 301 and g["kinds"] == {"Task": 300, "Entity": 1}            # counted over the whole group, not a sample of it
    assert all(type(x) is dict for x in g["sample"]) and len(g["sample"]) == 5
    n = await m.graph_neighbourhood("h", depth=1, limit=100)
    assert len(n["nodes"]) == 100 and n["truncated"]
    assert [x["ref"] for x in n["nodes"]] == [x["ref"] for x in (await m.graph_neighbourhood("h", depth=1, limit=100))["nodes"]]   # same answer twice


# ---------------------------------------------------------------- through the doors an outside agent uses
import httpx
import pytest_asyncio

from graphmem.api import create_app
from test_api import ADMIN, make_agent


@pytest_asyncio.fixture
async def client(gm):
    app = create_app(gm, admin_key="admin-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_over_http_with_a_read_only_key_and_without_one(client, gm):
    t, _ = await world(gm)
    reader = await make_agent(client, gm, "tt-ga-reader", t, ("read",))
    r = await client.post(f"/v1/tenants/{t}/graph_path", json={"source": "p", "target": "s"}, headers=reader)
    assert r.status_code == 200 and r.json()["result"]["length"] == 3
    for op, args in (("graph_influence", {}), ("graph_communities", {"method": "labelpropagation"}), ("graph_neighbourhood", {"ref": "hub"}), ("graph_schema", {})):
        r = await client.post(f"/v1/tenants/{t}/{op}", json=args, headers=reader)
        assert r.status_code == 200, (op, r.text)
    bad = await client.post(f"/v1/tenants/{t}/graph_influence", json={"metric": "degree"}, headers=reader)
    assert bad.status_code == 422 and "pagerank" in bad.text                       # a refusal with a reason, not a 500
    assert (await client.post(f"/v1/tenants/{t}/graph_schema", json={})).status_code == 401
    stranger = await make_agent(client, gm, "tt-ga-stranger")
    assert (await client.post(f"/v1/tenants/{t}/graph_schema", json={}, headers=stranger)).status_code == 403
    unknown_arg = await client.post(f"/v1/tenants/{t}/graph_path", json={"source": "p", "target": "s", "cypher": "MATCH (n) DETACH DELETE n"}, headers=reader)
    assert unknown_arg.status_code == 422
    assert (await client.post(f"/v1/tenants/{t}/graph_schema", json={}, headers=reader)).json()["result"]["nodes"]     # nothing was deleted


async def test_through_the_mcp_tool(gm):
    from graphmem.mcp_server import build
    t, _ = await world(gm)
    server = build(gm, "ann")
    out = await server.call_tool("call", {"tenant": t, "op": "graph_path", "args_json": '{"source": "p", "target": "r"}'})
    import json as _j
    text = out.content[0].text if hasattr(out, "content") else str(out)
    assert _j.loads(text)["length"] == 2
    bad = await server.call_tool("call", {"tenant": t, "op": "graph_influence", "args_json": '{"label": "Nope"}'})
    assert "no node label" in (bad.content[0].text if hasattr(bad, "content") else str(bad))
    listed = await server.call_tool("list_ops", {})
    assert "graph_communities" in (listed.content[0].text if hasattr(listed, "content") else str(listed))


async def test_every_operation_works_as_the_read_only_database_user():
    """Production runs read scope as a database user that may only call GRAPH.RO_QUERY: the procedures must work there."""
    import uuid
    from graphmem import Db, GraphMem
    db = Db(ro_password="test-ro-pw")
    gm2 = GraphMem(db)
    t = "tt-garo-" + uuid.uuid4().hex[:6]
    try:
        await gm2.grant("tt-garo-agent", t)
        m = gm2.open("tt-garo-agent", t)
        await m._q("CREATE (:Entity {key:'a', name:'A'})-[:LINKS]->(:Entity {key:'b', name:'B'})-[:LINKS]->(:Entity {key:'c', name:'C'})")
        assert (await m.graph_schema())["nodes"][0]["count"] == 3
        assert (await m.graph_path("a", "c"))["length"] == 2
        assert (await m.graph_influence("pagerank"))["rows"][0]["ref"] == "c"
        assert (await m.graph_influence("harmonic"))["rows"][0]["ref"] == "a"
        assert (await m.graph_communities("wcc"))["groups"][0]["size"] == 3
        assert (await m.graph_communities("labelpropagation"))["groups"]
        assert len((await m.graph_neighbourhood("b"))["nodes"]) == 2
    finally:
        await db.drop_tenant(t)
        await (await gm2._ctl()).query("MATCH (n) WHERE n.id IN ['tt-garo-agent', $t] DETACH DELETE n", {"t": t})


async def test_equal_length_paths_give_the_same_answer_every_time(gm):
    t = tid(gm, "ga-tie")
    await gm.grant("ann", t, ("read", "write"))
    m = gm.open("ann", t)
    await m._q("CREATE (s:Entity {key:'s'}), (e:Entity {key:'e'}), (m1:Entity {key:'m1'}), (m2:Entity {key:'m2'}), "
               "(s)-[:L]->(m1), (m1)-[:L]->(e), (s)-[:L]->(m2), (m2)-[:L]->(e)")
    seen = {tuple(n["ref"] for n in (await m.graph_path("s", "e"))["path"]) for _ in range(6)}
    assert len(seen) == 1 and len(next(iter(seen))) == 3


async def test_a_search_that_would_visit_too_much_stops_and_says_so(gm, monkeypatch):
    from graphmem import graph_algos
    t = tid(gm, "ga-visit")
    await gm.grant("ann", t, ("read", "write"))
    m = gm.open("ann", t)
    await m._q("CREATE (s:Entity {key:'s'}), (e:Entity {key:'e'}) WITH s, e UNWIND range(1, 30) AS i CREATE (s)-[:L]->(:Entity {key:'x' + toString(i)})-[:L]->(:Entity {key:'y' + toString(i)})")
    monkeypatch.setattr(graph_algos, "MAX_VISIT", 10)
    r = await m.graph_path("s", "e", max_hops=5)
    assert r["found"] is False and "stopped after" in r["reason"]
