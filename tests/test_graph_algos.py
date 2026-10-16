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
    bt = await m.graph_influence("betweenness", label="Task", top=10)               # exact, computed by the server: along p -> q -> r -> s the two middle records carry the paths
    scores = {r["ref"]: r["score"] for r in bt["rows"]}
    assert scores == {"p": 0, "q": 2, "r": 2, "s": 0} and {r["ref"] for r in bt["rows"][:2]} == {"q", "r"}
    assert "Brandes" in bt["computed_by"] and "MATCH" in bt["cypher"]


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
    (lambda m: m.graph_influence(metric="degree"), "betweenness"),
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


# ---------------------------------------------------------------- exact betweenness
import random  # noqa: E402

from graphmem.graph_algos import brandes  # noqa: E402


def naive_betweenness(nodes, edges):
    """The definition, the slow way: all-pairs shortest-path counts, then for every (s, t) the share of s-t shortest paths through each other node."""
    from collections import deque
    adj = {v: set() for v in nodes}
    for a, b in edges:
        if a != b:
            adj[a].add(b)
    dist, sigma = {}, {}
    for s in nodes:
        d, sg, q = {s: 0}, {s: 1}, deque([s])
        while q:
            v = q.popleft()
            for w in adj[v]:
                if w not in d:
                    d[w] = d[v] + 1
                    q.append(w)
                if d[w] == d[v] + 1:
                    sg[w] = sg.get(w, 0) + sg[v]
        dist[s], sigma[s] = d, sg
    out = {v: 0.0 for v in nodes}
    for s in nodes:
        for t in nodes:
            if s == t or t not in dist[s]:
                continue
            for v in nodes:
                if v not in (s, t) and v in dist[s] and t in dist[v] and dist[s][v] + dist[v][t] == dist[s][t]:
                    out[v] += sigma[s][v] * sigma[v][t] / sigma[s][t]
    return out


def test_betweenness_by_hand():
    chain = brandes([1, 2, 3, 4, 5], [(1, 2), (2, 3), (3, 4), (4, 5)])
    assert chain == {1: 0, 2: 3, 3: 4, 4: 3, 5: 0}                                  # node 3 lies on 1-4, 1-5, 2-4, 2-5
    diamond = brandes(list("sabe"), [("s", "a"), ("s", "b"), ("a", "e"), ("b", "e")])
    assert diamond == {"s": 0, "a": 0.5, "b": 0.5, "e": 0}                          # two equal routes share the credit
    assert brandes(list("hxy"), [("h", "x"), ("h", "y")]) == {"h": 0, "x": 0, "y": 0}      # a hub that only points outward lies between nothing
    assert brandes(list("ab"), [("a", "b"), ("a", "b"), ("a", "a")]) == {"a": 0, "b": 0}    # parallel and self links change nothing
    assert brandes([], []) == {} and brandes(["only"], []) == {"only": 0}


def test_betweenness_agrees_with_the_definition_on_random_graphs():
    rng = random.Random(7)
    for _ in range(60):
        n = rng.randint(2, 9)
        nodes = list(range(n))
        edges = [(rng.randrange(n), rng.randrange(n)) for _ in range(rng.randint(0, 20))]
        got, want = brandes(nodes, edges), naive_betweenness(nodes, edges)
        assert all(abs(got[v] - want[v]) < 1e-9 for v in nodes), (nodes, edges, got, want)


async def test_betweenness_is_repeatable_and_refuses_a_graph_too_large_for_an_exact_answer(gm, monkeypatch):
    from graphmem import graph_algos
    t, m = await world(gm)
    first = await m.graph_influence("betweenness")
    assert [await m.graph_influence("betweenness") for _ in range(5)] == [first] * 5                # the same every time, unlike FalkorDB 4.22's own
    monkeypatch.setattr(graph_algos, "MAX_BETWEENNESS_WORK", 10)
    with pytest.raises(ValueError, match="too large for exact betweenness"):
        await m.graph_influence("betweenness")
    assert (await m.graph_influence("betweenness", label="Skill"))["rows"]                         # narrowing by label brings it back under the limit


async def test_a_graph_with_hardly_any_links_says_so(gm):
    t = tid(gm, "ga-thin")
    await gm.grant("ann", t, ("read", "write"))
    m = gm.open("ann", t)
    await m._q("UNWIND range(1, 6) AS i CREATE (:Entity {key: 'e' + toString(i)})")             # six records, no links at all
    for r in (await m.graph_influence("pagerank"), await m.graph_influence("betweenness"), await m.graph_communities()):
        assert "6 of 6 records are not linked" in r["note"]
    rich = await world(gm, "ga-rich")                                                           # nine links among eleven records, two of them in a pair: not shallow
    assert "note" not in await rich[1].graph_influence("pagerank") and "note" not in await rich[1].graph_communities()


def test_the_catalogue_carries_the_whole_description_so_a_model_knows_what_each_argument_means():
    listed = ops.describe()
    for name in ("graph_schema", "graph_path", "graph_influence", "graph_communities", "graph_neighbourhood"):
        assert "graph_schema" in listed[name]["help"] or name == "graph_schema"        # each says where its label values come from
        assert listed[name]["help"].startswith(listed[name]["doc"][:40])
    assert "id, key or name" in listed["graph_path"]["help"] and "optional node label" in listed["graph_path"]["help"]
    assert all(len(v["help"]) <= 700 and "\n" not in v["help"] for v in listed.values())       # bounded, on one line, for every operation
