"""One test group per Track 02 requirement. Run against a live FalkorDB (docker run -p 6379:6379 falkordb/falkordb)."""
import asyncio

import pytest

from graphmem import Db, GraphMem, PermissionDenied
from conftest import tid


async def setup_pair(gm, label="a", agents=("alice",)):
    t = tid(gm, label)
    for a in agents:
        await gm.grant(a, t, ("read", "write"))
    return t, [gm.open(a, t) for a in agents]


# ------------------------------------------------------------ 1. episodic / semantic / procedural
async def test_episodic_ordering_and_chain(gm):
    t, (m,) = await setup_pair(gm)
    for i in range(5):
        await m.add_episode("s1", "user", f"msg {i}")
    h = await m.history("s1")
    assert [e["content"] for e in h] == [f"msg {i}" for i in range(5)]
    assert [e["seq"] for e in h] == [1, 2, 3, 4, 5]
    rows = await m._q("MATCH (:Episode)-[r:NEXT]->(:Episode) RETURN count(r)", scope="read")
    assert rows[0][0] == 4


async def test_semantic_supersede_and_as_of(gm):
    t, (m,) = await setup_pair(gm)
    a = await m.assert_fact("Alice", "lives_in", "Paris", exclusive=True, at=1_000)
    b = await m.assert_fact("Alice", "lives_in", "Berlin", exclusive=True, at=2_000)
    assert b["superseded"] == [a["id"]]
    now = await m.recall("alice")
    assert [f["object"] for f in now if f["predicate"] == "lives_in"] == ["Berlin"]
    past = await m.recall("alice", as_of=1_500)
    assert [f["object"] for f in past if f["predicate"] == "lives_in"] == ["Paris"]
    hist = await m.fact_history("Alice", "lives_in")
    assert [h["value"] for h in hist] == ["Paris", "Berlin"] and hist[0]["valid_to"] == 2_000


async def test_fact_reinforcement_not_duplication(gm):
    t, (m,) = await setup_pair(gm)
    for _ in range(3):
        r = await m.assert_fact("Bob", "likes", "tea")
    assert r["support"] == 3
    rows = await m._q("MATCH (f:Fact) RETURN count(f)", scope="read")
    assert rows[0][0] == 1


async def test_recall_has_provenance_and_multihop(gm):
    t, (m,) = await setup_pair(gm)
    ep = await m.add_episode("s", "user", "Carol works at Acme and Acme is in Oslo")
    await m.assert_fact("Carol", "works_at", "Acme", sources=[ep["id"]])
    await m.assert_fact("Acme", "located_in", "Oslo", sources=[ep["id"]])
    res = await m.recall("carol", hops=2)
    by_pred = {r["predicate"]: r for r in res}
    assert by_pred["works_at"]["hop"] == 1
    assert by_pred["located_in"]["hop"] == 2          # reached only via the graph
    assert by_pred["located_in"]["provenance"][0]["episode"] == ep["id"]
    assert "Acme" in by_pred["located_in"]["path"]
    assert not [r for r in await m.recall("carol", hops=1) if r["predicate"] == "located_in"]


async def test_procedural_ranking_learns_from_outcomes(gm):
    t, (m,) = await setup_pair(gm)
    await m.add_skill("restart-service", "restart it", ["ssh", "systemctl restart"], tags=["ops"])
    await m.add_skill("rollback-deploy", "roll back", ["helm rollback"], tags=["ops"])
    for ok in (True, True, False, True):
        await m.record_run("restart-service", ok)
    for ok in (False, False, True):
        await m.record_run("rollback-deploy", ok)
    best = await m.best_skills(tags=["ops"])
    assert [s["name"] for s in best] == ["restart-service", "rollback-deploy"]
    assert best[0]["runs"] == 4 and best[0]["wins"] == 3
    await m.record_run("rollback-deploy", True)
    await m.record_run("rollback-deploy", True)
    await m.record_run("rollback-deploy", True)
    await m.record_run("rollback-deploy", True)
    assert (await m.best_skills(tags=["ops"]))[0]["name"] == "rollback-deploy"


# ------------------------------------------------------------ 2. persistent history across processes
async def test_memory_survives_new_client(gm):
    t, (m,) = await setup_pair(gm)
    ep = await m.add_episode("s", "user", "remember the launch code is 7")
    await m.assert_fact("Launch", "code", "7", sources=[ep["id"]])
    db2 = Db()                                # a brand-new client/connection pool = a "restarted" process
    gm2 = GraphMem(db2)
    m2 = gm2.open("alice", t)
    assert (await m2.history("s"))[0]["content"] == "remember the launch code is 7"
    assert (await m2.recall("launch"))[0]["object"] == "7"
    cont = await m2.add_episode("s", "user", "next")   # sequence continues, not restarted
    assert cont["seq"] == 2


# ------------------------------------------------------------ 3. shared state & handoffs
async def test_handoff_chain_and_cas(gm):
    t, (a, b) = await setup_pair(gm, agents=("alice", "bob"))
    task = await a.create_task("triage incident")
    assert await a.claim_task(task) is True
    assert await b.claim_task(task) is False           # already claimed
    assert await b.handoff(task, "alice") is False     # bob is not the owner
    assert await a.handoff(task, "bob", "over to you") is True
    assert await a.handoff(task, "bob") is False       # alice no longer owns it
    assert await b.accept(task) is True
    assert await b.complete(task, "fixed") is True
    r = await b.resume(task)
    assert r["task"]["status"] == "done"
    assert [(h["frm"], h["to"]) for h in r["handoffs"]] == [("alice", "bob")]


async def test_claim_race_exactly_one_winner(gm):
    agents = tuple(f"agent{i}" for i in range(20))
    t, mems = await setup_pair(gm, agents=agents)
    task = await mems[0].create_task("contended")
    wins = await asyncio.gather(*[m.claim_task(task) for m in mems])
    assert sum(wins) == 1
    owner = (await mems[0].get_task(task))["owner"]
    assert owner == agents[wins.index(True)]


async def test_stale_plan_detected_via_lineage(gm):
    t, (a, b) = await setup_pair(gm, agents=("alice", "bob"))
    f1 = await a.assert_fact("deadline", "is", "friday", exclusive=True, at=1_000)
    f2 = await a.assert_fact("owner", "is", "carol", exclusive=True, at=1_000)
    task = await a.create_task("ship report")
    await a.claim_task(task)
    plan = await a.create_plan(task, ["draft", "send by deadline"], derived_from=[f1["id"], f2["id"]])
    await a.handoff(task, "bob", plan_id=plan)
    assert (await b.check_plan(plan))["stale"] is False
    await a.assert_fact("deadline", "is", "wednesday", exclusive=True, at=2_000)   # requirement changes after planning
    chk = await b.check_plan(plan)
    assert chk["stale"] is True and len(chk["changes"]) == 1
    ch = chk["changes"][0]
    assert ch["was"] == "friday" and ch["now"][0]["value"] == "wednesday"
    rb = await b.rebase_plan(plan)
    assert (await b.check_plan(rb["plan"]))["stale"] is False
    assert (await b.resume(task))["plan"]["id"] == rb["plan"]


# ------------------------------------------------------------ 4. concurrency
async def test_concurrent_writers_no_loss_ordered_history(gm):
    agents = tuple(f"w{i}" for i in range(16))
    t, mems = await setup_pair(gm, agents=agents)

    async def work(m, i):
        for j in range(15):
            await m.add_episode("shared", "agent", f"{i}-{j}")
            await m.assert_fact(f"topic{j % 3}", "seen_by", f"w{i}")

    await asyncio.gather(*[work(m, i) for i, m in enumerate(mems)])
    h = await mems[0].history("shared", limit=1000)
    assert len(h) == 16 * 15
    assert [e["seq"] for e in h] == list(range(1, 16 * 15 + 1))          # no gaps, no duplicates
    nxt = await mems[0]._q("MATCH ()-[r:NEXT]->() RETURN count(r)", scope="read")
    assert nxt[0][0] == 16 * 15 - 1
    facts = await mems[0]._q("MATCH (f:Fact) RETURN count(f), sum(f.support)", scope="read")
    assert facts[0][0] == 3 * 16 and facts[0][1] == 16 * 15              # reinforcement counts exact under contention


async def test_exclusive_fact_race_converges_to_one_current(gm):
    t, mems = await setup_pair(gm, agents=tuple(f"x{i}" for i in range(8)))
    await asyncio.gather(*[m.assert_fact("room", "temp", f"{20 + i}", exclusive=True) for i, m in enumerate(mems)])
    rows = await mems[0]._q("MATCH (f:Fact {pred:'temp', cur:true}) RETURN count(f)", scope="read")
    assert rows[0][0] == 1


# ------------------------------------------------------------ 5. tenancy
async def test_tenant_isolation_and_policy(gm):
    ta, (alice,) = await setup_pair(gm, "a", ("alice",))
    tb, (bob,) = await setup_pair(gm, "b", ("bob",))
    await alice.assert_fact("alice-secret", "is", "swordfish")
    await alice.add_episode("s", "user", "swordfish")
    await bob.assert_fact("bob-fact", "is", "ok")
    assert await bob.recall("swordfish") == [] and await bob.search_episodes("swordfish") == []
    assert await bob.history("s") == []
    # no grant -> denied on every path
    intruder = gm.open("bob", ta)
    for call in (intruder.recall("swordfish"), intruder.history("s"), intruder.add_episode("s", "user", "x")):
        with pytest.raises(PermissionDenied):
            await call
    # read-only grant cannot write; revoke takes effect on existing handle
    await gm.grant("carol", ta, ("read",))
    carol = gm.open("carol", ta)
    assert (await carol.recall("alice-secret"))[0]["object"] == "swordfish"
    with pytest.raises(PermissionDenied):
        await carol.assert_fact("x", "y", "z")
    await gm.revoke("carol", ta)
    with pytest.raises(PermissionDenied):
        await carol.recall("alice-secret")


async def test_invalid_tenant_ids_rejected(gm):
    for bad in ("", "a b", "x;DROP", "../etc", "A", "a" * 60):
        with pytest.raises(ValueError):
            await gm.create_tenant(bad)


async def test_injection_safe_values(gm):
    t, (m,) = await setup_pair(gm)
    nasty = "x'}) DETACH DELETE (n) //\" \\ \n"
    await m.add_episode("s", "user", nasty)
    await m.assert_fact(nasty, "p", nasty)
    assert (await m.history("s"))[0]["content"] == nasty
    assert (await m.stats())["Fact"] == 1


# ------------------------------------------------------------ traceability & forgetting
async def test_decision_trace_explains_answer(gm):
    t, (m,) = await setup_pair(gm)
    ep = await m.add_episode("s", "user", "the vendor changed their SLA to 99.9")
    f = await m.assert_fact("vendor", "sla", "99.9", sources=[ep["id"]])
    await m.add_skill("escalate", "escalate", ["page oncall"], tags=["ops"])
    sk = (await m.best_skills())[0]
    d = await m.record_decision("recommend escalation", [f["id"], sk["id"]], "escalate to vendor")
    ex = await m.explain(d)
    types = {u["type"] for u in ex["used"]}
    assert types == {"Fact", "Skill"}
    fact_used = [u for u in ex["used"] if u["type"] == "Fact"][0]
    assert fact_used["source_episodes"] == [ep["id"]] and "99.9" in fact_used["summary"]


async def test_forget_retracts_everywhere(gm):
    t, (m,) = await setup_pair(gm)
    ep = await m.add_episode("s", "user", "my SSN is 123-45-6789")
    f = await m.assert_fact("user", "ssn", "123-45-6789", sources=[ep["id"]])
    task = await m.create_task("t")
    plan = await m.create_plan(task, ["use ssn"], derived_from=[f["id"]])
    await m.forget_fact(f["id"], "user requested deletion", redact_sources=True)
    assert await m.recall("ssn") == [] and await m.recall("123-45-6789") == []
    assert await m.search_episodes("6789") == []
    assert (await m.history("s"))[0]["content"] is None and (await m.history("s"))[0]["redacted"] is True
    raw = await m._q("MATCH (n) WHERE any(k IN keys(n) WHERE toString(n[k]) CONTAINS '6789') RETURN count(n)", scope="read")
    assert raw[0][0] == 0                                 # the value is gone from the whole graph
    chk = await m.check_plan(plan)
    assert chk["stale"] and chk["changes"][0]["status"] == "retracted"
    tomb = await m._q("MATCH (t:Tombstone)-[:TOMBSTONES]->(:Fact {id:$f}) RETURN t.reason", {"f": f["id"]}, scope="read")
    assert tomb[0][0] == "user requested deletion"


async def test_transitive_staleness_through_inferred_facts(gm):
    t, (m,) = await setup_pair(gm)
    base = await m.assert_fact("api", "limit", "100", exclusive=True, at=1_000)
    other = await m.assert_fact("db", "region", "eu", exclusive=True, at=1_000)
    derived = await m.assert_fact("batch", "size", "50", inferred_from=[base["id"]], at=1_000)     # inferred from the api limit
    task = await m.create_task("tune batch")
    plan = await m.create_plan(task, ["use batch size"], derived_from=[derived["id"], other["id"]])
    assert (await m.check_plan(plan))["stale"] is False
    await m.assert_fact("api", "limit", "20", exclusive=True, at=2_000)                           # upstream of the plan's input changes
    chk = await m.check_plan(plan)
    assert chk["stale"] and chk["changes"][0]["status"] == "upstream_superseded"
    assert chk["changes"][0]["upstream"]["was"] == "100" and chk["changes"][0]["now"][0]["value"] == "20"
    rb = await m.rebase_plan(plan)
    assert (await m.check_plan(rb["plan"]))["stale"] is False                                     # re-derived from current facts
