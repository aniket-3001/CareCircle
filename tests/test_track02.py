"""Track 02 (Agent Memory & Coordination) conformance, one section per bullet of the brief, driven over the public HTTP API the way an outside agent
would use it (no direct engine calls except to read the database back and check what really got stored). docs/TRACK02.md maps each section to the code.

  1. Episodic, semantic and procedural memory
  2. Persistent conversation history
  3. Shared state and handoffs between agents
  4. High-concurrency reads and writes
  5. Separate memory per user or tenant
"""
import asyncio
import time

import pytest

from graphmem import Db, GraphMem
from graphmem.api import create_app
from conftest import tid
from test_api import ADMIN, client, make_agent  # noqa: F401 (fixture)


async def call(client, h, tenant, op, **args):
    r = await client.post(f"/v1/tenants/{tenant}/{op}", json=args, headers=h)
    assert r.status_code == 200, f"{op}: {r.status_code} {r.text}"
    return r.json()["result"]


async def team(client, gm, tenant, names, scopes=("read", "write")):
    return [await make_agent(client, gm, f"t2-{n}", tenant, scopes) for n in names]


# ============================================================ 1. episodic, semantic, procedural
async def test_1a_episodic_memory_is_ordered_attributed_immutable_and_searchable(client, gm):
    t = tid(gm, "ep")
    (a, b) = await team(client, gm, t, ["alice", "bob"])
    await call(client, a, t, "add_episode", session="incident-7", role="user", content="The payments API returns 502 after the 14:00 deploy")
    await call(client, b, t, "add_episode", session="incident-7", role="agent", content="Rolled back the 14:00 deploy; 502s stopped")
    await call(client, a, t, "add_episode", session="other", role="user", content="Unrelated chat about lunch")
    hist = await call(client, a, t, "history", session="incident-7")
    assert [(e["seq"], e["role"]) for e in hist] == [(1, "user"), (2, "agent")]                    # ordered within a session
    assert [e["agent"] for e in hist] == ["t2-alice", "t2-bob"]                                      # who said it is kept
    assert len(await call(client, a, t, "history", session="other")) == 1                           # sessions are separate
    assert {s["id"] for s in await call(client, a, t, "sessions")} == {"incident-7", "other"}
    hit = await call(client, b, t, "search_text", query="deploy")
    assert hit and all("deploy" in h["content"].lower() for h in hit)                                # full-text search over what happened
    ops = (await client.get("/v1/ops", headers=a)).json()
    assert not [op for op in ops if "episode" in op and any(w in op for w in ("edit", "update", "delete", "remove", "rewrite"))]      # no way to rewrite an event
    r = await client.post(f"/v1/tenants/{t}/update_episode", json={}, headers=a)
    assert r.status_code in (400, 404)


async def test_1b_semantic_memory_updates_over_time_keeps_history_and_provenance(client, gm):
    t = tid(gm, "sem")
    (a, b) = await team(client, gm, t, ["alice", "bob"])
    ep = await call(client, a, t, "add_episode", session="s", role="user", content="I moved to Berlin")
    f1 = await call(client, a, t, "assert_fact", subject="Alice", predicate="lives_in", obj="Paris", exclusive=True, at=1_000)
    f2 = await call(client, b, t, "assert_fact", subject="Alice", predicate="lives_in", obj="Berlin", exclusive=True, at=2_000, sources=[ep["id"]])
    assert f2["superseded"] == [f1["id"]]                                                            # the new value replaces the old
    now = await call(client, a, t, "recall", query="alice")
    assert [f["object"] for f in now if f["predicate"] == "lives_in"] == ["Berlin"]                 # current belief
    then = await call(client, a, t, "recall", query="alice", as_of=1_500)
    assert [f["object"] for f in then if f["predicate"] == "lives_in"] == ["Paris"]                 # what we believed at an earlier time
    hist = await call(client, a, t, "fact_history", subject="Alice", predicate="lives_in")
    assert [h["value"] for h in hist] == ["Paris", "Berlin"] and hist[0]["valid_to"]               # nothing is overwritten
    berlin = next(f for f in now if f["object"] == "Berlin")
    assert berlin["provenance"] and berlin["provenance"][0]["episode"] == ep["id"]                  # where the belief came from
    again = await call(client, a, t, "assert_fact", subject="Bob", predicate="likes", obj="tea")
    await call(client, b, t, "assert_fact", subject="Bob", predicate="likes", obj="tea")
    likes = [f for f in await call(client, a, t, "recall", query="bob") if f["predicate"] == "likes"]
    assert len(likes) == 1 and again["id"] == likes[0]["id"]                                        # repeating a fact reinforces it, not duplicates it
    await call(client, a, t, "forget_fact", fact_id=berlin["id"], reason="user asked to forget it")
    assert all(f["object"] != "Berlin" for f in await call(client, a, t, "recall", query="alice"))   # forgetting removes it from recall


async def test_1c_procedural_memory_learns_which_skill_works(client, gm):
    t = tid(gm, "proc")
    (a, b) = await team(client, gm, t, ["alice", "bob"])
    await call(client, a, t, "add_skill", name="restart-service", description="Restart the stuck worker", steps=["drain", "restart", "verify"], tags=["ops"])
    await call(client, a, t, "add_skill", name="rollback-deploy", description="Roll back the last release", steps=["find release", "roll back"], tags=["ops"])
    for ok in (True, True, True, False):
        await call(client, a, t, "record_run", skill="restart-service", success=ok)
    for ok in (False, False, True):
        await call(client, b, t, "record_run", skill="rollback-deploy", success=ok)               # another agent's outcomes count too
    best = await call(client, a, t, "best_skills", tags=["ops"])
    assert [s["name"] for s in best] == ["restart-service", "rollback-deploy"]
    assert (best[0]["runs"], best[0]["wins"]) == (4, 3) and best[0]["steps"] == ["drain", "restart", "verify"]
    for _ in range(8):
        await call(client, b, t, "record_run", skill="rollback-deploy", success=True)
    assert (await call(client, a, t, "best_skills", tags=["ops"]))[0]["name"] == "rollback-deploy"   # the ranking moves with experience
    assert await call(client, a, t, "best_skills", tags=["unrelated"]) == []


async def test_1d_the_three_kinds_are_linked_in_one_graph(client, gm):
    t = tid(gm, "link")
    (a,) = await team(client, gm, t, ["alice"])
    ep = await call(client, a, t, "add_episode", session="s", role="user", content="deploys on Friday break things")
    f = await call(client, a, t, "assert_fact", subject="deploys", predicate="risky_on", obj="friday", sources=[ep["id"]])
    sk = await call(client, a, t, "add_skill", name="freeze-friday", description="No Friday deploys", steps=["announce"], tags=["release"], sources=[f["id"]])
    rows = await call(client, a, t, "stats")
    assert rows.get("Episode") == 1 and rows.get("Fact") == 1 and rows.get("Skill") == 1
    d = await call(client, a, t, "record_decision", summary="skip Friday deploy", used=[f["id"], sk["id"]], answer="postponed")
    why = await call(client, a, t, "explain", decision_id=d)
    assert why and f["id"] in str(why) and ep["id"] in str(why)                                       # decision -> fact -> episode, one traversal


# ============================================================ 2. persistent conversation history
async def test_2_conversation_history_survives_a_restart_and_keeps_growing(client, gm):
    t = tid(gm, "hist")
    (a,) = await team(client, gm, t, ["alice"])
    for i in range(40):
        await call(client, a, t, "add_episode", session="chat", role="user" if i % 2 == 0 else "agent", content=f"turn {i}")
    # a brand-new app and database client over the same data stands in for a restarted process
    gm2 = GraphMem(Db())
    app2 = create_app(gm2, admin_key="admin-secret")
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t2") as c2:
        h = await call(c2, a, t, "history", session="chat", limit=100)                                # the same API key still works, nothing was lost
        assert [e["content"] for e in h] == [f"turn {i}" for i in range(40)] and [e["seq"] for e in h] == list(range(1, 41))
        nxt = await call(c2, a, t, "add_episode", session="chat", role="user", content="after restart")
        assert nxt["seq"] == 41                                                                       # numbering continues, it does not restart
        page = await call(c2, a, t, "history", session="chat", limit=10, before_seq=21)               # paging backwards through a long history
        assert [e["seq"] for e in page] == list(range(11, 21))
    await gm2.db.close() if hasattr(gm2.db, "close") else None


async def test_2b_care_circle_assistant_conversation_is_stored_per_person_and_can_be_cleared(client, gm):
    t = tid(gm, "chat")
    ravi = gm.open("ravi", t)
    await gm.grant("ravi", t, ("read", "write", "admin"))
    await gm.grant("meena", t, ("read", "write", "admin"))
    await gm.open("ravi", t).care_record("asha", "warfarin", dose_text="4 mg")
    r = await gm.open("ravi", t).care_chat_ask("asha", "what is on record")
    assert r
    mine = await gm.open("ravi", t).care_chat_history()
    theirs = await gm.open("meena", t).care_chat_history()
    assert [m["role"] for m in mine][:2] == ["user", "assistant"] and theirs == []                    # each carer's conversation is their own
    gm_new = GraphMem(Db())
    assert await gm_new.open("ravi", t).care_chat_history() == mine                              # and it is still there after a restart
    await ravi.care_chat_clear()
    assert await gm.open("ravi", t).care_chat_history() == []


# ============================================================ 3. shared state and handoffs
async def test_3a_agents_in_one_tenant_see_each_others_memory(client, gm):
    t = tid(gm, "shared")
    (a, b, c) = await team(client, gm, t, ["alice", "bob", "carol"])
    await call(client, a, t, "add_episode", session="s", role="agent", content="alice found the bug in billing")
    await call(client, a, t, "assert_fact", subject="billing", predicate="status", obj="broken", exclusive=True)
    seen = await call(client, b, t, "recall", query="billing")
    assert [f["object"] for f in seen] == ["broken"] and seen[0]["agent"] == "t2-alice"                 # bob reads what alice wrote
    await call(client, b, t, "assert_fact", subject="billing", predicate="status", obj="fixed", exclusive=True)
    assert [f["object"] for f in await call(client, c, t, "recall", query="billing")] == ["fixed"]       # carol sees the update, not the stale value
    assert [e["content"] for e in await call(client, c, t, "history", session="s")] == ["alice found the bug in billing"]


async def test_3b_task_handoff_chain_with_resume(client, gm):
    t = tid(gm, "task")
    (a, b, c) = await team(client, gm, t, ["alice", "bob", "carol"])
    task = await call(client, a, t, "create_task", title="triage incident 7", payload={"sev": 2})
    assert await call(client, a, t, "claim_task", task_id=task) is True
    assert await call(client, b, t, "claim_task", task_id=task) is False                                # already owned
    assert await call(client, b, t, "handoff", task_id=task, to_agent="t2-carol") is False              # bob does not own it, cannot hand it off
    assert await call(client, c, t, "accept", task_id=task) is False                                    # nothing was handed to carol yet
    fact = await call(client, a, t, "assert_fact", subject="incident7", predicate="cause", obj="bad deploy")
    plan = await call(client, a, t, "create_plan", task_id=task, steps=["roll back", "verify"], derived_from=[fact["id"]])
    assert await call(client, a, t, "handoff", task_id=task, to_agent="t2-bob", note="please verify the rollback", plan_id=plan) is True
    assert await call(client, c, t, "accept", task_id=task) is False                                    # only the named agent can accept
    assert await call(client, b, t, "accept", task_id=task) is True
    ctx = await call(client, b, t, "resume", task_id=task)                                              # the receiver gets everything in one call
    assert ctx["task"]["owner"] == "t2-bob" and ctx["task"]["status"] == "in_progress"
    assert ctx["plan"]["steps"] == ["roll back", "verify"] and ctx["handoffs"][0]["note"] == "please verify the rollback"
    await call(client, a, t, "assert_fact", subject="incident7", predicate="cause", obj="config typo", exclusive=True)   # the facts the plan used change...
    chk = await call(client, b, t, "check_plan", plan_id=plan)
    assert chk["stale"] and chk["changes"][0]["was"] == "bad deploy"                                    # ...and the plan is reported out of date
    assert await call(client, b, t, "complete", task_id=task, result="verified") is True
    assert (await call(client, a, t, "get_task", task_id=task))["status"] == "done"
    assert await call(client, a, t, "open_tasks") == []


async def test_3c_branch_merge_and_a_space_shared_across_tenants(client, gm):
    t1, t2 = tid(gm, "sp1"), tid(gm, "sp2")
    (a,) = await team(client, gm, t1, ["alice"])
    (b,) = await team(client, gm, t2, ["bob"])
    # a fork: an agent explores on a copy, then the result is merged back (or thrown away)
    await call(client, a, t1, "assert_fact", subject="service", predicate="version", obj="1", exclusive=True)
    fk = (await client.post(f"/v1/tenants/{t1}/forks", json={"label": "try v2"}, headers=a)).json()
    fid = fk["result"]["fork"] if "fork" in fk["result"] else fk["result"]["id"]
    assert (await client.post(f"/v1/forks/{fid}/assert_fact", json={"subject": "service", "predicate": "version", "obj": "2", "exclusive": True}, headers=a)).status_code == 200
    assert [f["object"] for f in await call(client, a, t1, "recall", query="service")] == ["1"]         # the main memory is untouched while exploring
    assert (await client.post(f"/v1/forks/{fid}/merge", json={"apply": True}, headers=a)).status_code == 200
    assert [f["object"] for f in await call(client, a, t1, "recall", query="service")] == ["2"]         # merged
    # a space: facts one tenant chooses to publish become readable by another tenant's agent
    f = await call(client, a, t1, "assert_fact", subject="runbook", predicate="owner", obj="platform team")
    sp = "org" + t1[-6:]                                                                                   # a space of its own for this run
    await client.post("/admin/spaces/members", json={"agent": "t2-alice", "space": sp, "scopes": ["read", "write"]}, headers=ADMIN)
    await client.post("/admin/spaces/members", json={"agent": "t2-bob", "space": sp, "scopes": ["read"]}, headers=ADMIN)
    pub = await client.post(f"/v1/spaces/{sp}/publish", json={"tenant": t1, "fact_ids": [f["id"]]}, headers=a)
    assert pub.status_code == 200
    got = (await client.post(f"/v1/spaces/{sp}/recall", json={"query": "runbook"}, headers=b)).json()["result"]
    assert [x["object"] for x in got] == ["platform team"]
    assert await call(client, b, t2, "recall", query="runbook") == []                                    # bob's own memory did not receive it
    await gm.db.client.select_graph(gm.db.space_graph_name(sp)).delete()


# ============================================================ 4. high-concurrency reads and writes
async def test_4a_many_agents_write_one_session_at_once_nothing_lost_order_exact(client, gm):
    t = tid(gm, "conc")
    names = [f"w{i}" for i in range(20)]
    hs = await team(client, gm, t, names)

    async def work(h, i):
        for j in range(10):
            await call(client, h, t, "add_episode", session="room", role="agent", content=f"{i}-{j}")
            await call(client, h, t, "assert_fact", subject=f"topic{j % 4}", predicate="seen_by", obj=f"w{i}")

    await asyncio.gather(*[work(h, i) for i, h in enumerate(hs)])
    h = await call(client, hs[0], t, "history", session="room", limit=1000)
    assert len(h) == 200 and [e["seq"] for e in h] == list(range(1, 201))                              # 200 writes, 200 events, seq 1..200 with no gap or repeat
    assert len({e["content"] for e in h}) == 200                                                       # none duplicated, none dropped
    per_agent = {}
    for e in h:
        per_agent.setdefault(e["agent"], []).append(int(e["content"].split("-")[1]))
    assert all(v == sorted(v) for v in per_agent.values())                                              # each agent's own turns stay in its order
    nxt = (await gm.open("t2-w0", t)._q("MATCH ()-[r:NEXT]->() RETURN count(r)", scope="read"))[0][0]
    assert nxt == 199                                                                                    # the chain is one unbroken line


async def test_4b_reads_run_while_writes_land_and_never_see_a_torn_state(client, gm):
    t = tid(gm, "rw")
    hs = await team(client, gm, t, [f"rw{i}" for i in range(12)])
    stop = asyncio.Event()
    bad = []

    async def writer(h, i):
        for j in range(15):
            await call(client, h, t, "add_episode", session="live", role="agent", content=f"{i}-{j}")

    async def reader(h):
        while not stop.is_set():
            hist = await call(client, h, t, "history", session="live", limit=1000)
            seqs = [e["seq"] for e in hist]
            if seqs != list(range(seqs[0], seqs[0] + len(seqs))) if seqs else False:                   # any gap in what a reader sees is a torn read
                bad.append(seqs)
            await asyncio.sleep(0)

    readers = [asyncio.create_task(reader(hs[i])) for i in range(4)]
    await asyncio.gather(*[writer(h, i) for i, h in enumerate(hs[4:])])
    stop.set()
    await asyncio.gather(*readers)
    assert not bad
    assert len(await call(client, hs[0], t, "history", session="live", limit=1000)) == 8 * 15


async def test_4c_contended_claims_and_exclusive_facts_have_exactly_one_winner(client, gm):
    t = tid(gm, "race")
    hs = await team(client, gm, t, [f"r{i}" for i in range(24)])
    task = await call(client, hs[0], t, "create_task", title="one job")
    wins = await asyncio.gather(*[call(client, h, t, "claim_task", task_id=task) for h in hs])
    assert wins.count(True) == 1                                                                         # 24 agents race, one gets it
    owner = (await call(client, hs[0], t, "get_task", task_id=task))["owner"]
    assert owner == f"t2-r{wins.index(True)}"
    await asyncio.gather(*[call(client, h, t, "assert_fact", subject="room", predicate="temp", obj=str(20 + i), exclusive=True) for i, h in enumerate(hs)])
    cur = (await gm.open("t2-r0", t)._q("MATCH (f:Fact {pred:'temp', cur:true}) RETURN count(f)", scope="read"))[0][0]
    assert cur == 1                                                                                      # concurrent updates converge to a single current value
    support = (await gm.open("t2-r0", t)._q("MATCH (f:Fact {pred:'temp'}) RETURN count(f)", scope="read"))[0][0]
    assert support == 24                                                                                 # and every value that was written is still in the history


async def test_4d_many_tenants_at_once_each_stays_correct(client, gm):
    n = 12
    tenants = [tid(gm, f"mt{i}") for i in range(n)]
    hs = [(await team(client, gm, t, [f"m{i}a", f"m{i}b"])) for i, t in enumerate(tenants)]

    async def run(i):
        t, (a, b) = tenants[i], hs[i]
        await asyncio.gather(*[call(client, a if k % 2 else b, t, "add_episode", session="s", role="agent", content=f"{i}:{k}") for k in range(20)])
        await call(client, a, t, "assert_fact", subject="tenant", predicate="number", obj=str(i), exclusive=True)
        h = await call(client, a, t, "history", session="s", limit=100)
        assert [e["seq"] for e in h] == list(range(1, 21)) and all(e["content"].startswith(f"{i}:") for e in h)
        assert [f["object"] for f in await call(client, b, t, "recall", query="tenant")] == [str(i)]

    t0 = time.perf_counter()
    await asyncio.gather(*[run(i) for i in range(n)])
    assert time.perf_counter() - t0 < 60                                                                 # 240 writes across 12 tenants complete promptly


async def test_4e_a_full_queue_is_retried_not_lost(client, gm, monkeypatch):
    t = tid(gm, "retry")
    (a,) = await team(client, gm, t, ["alice"])
    results = await asyncio.gather(*[client.post(f"/v1/tenants/{t}/add_episode", json={"session": "burst", "role": "agent", "content": str(i)}, headers=a) for i in range(150)])
    assert all(r.status_code == 200 for r in results)                                                   # a burst of 150 at once: no 5xx, no dropped request
    assert len(await call(client, a, t, "history", session="burst", limit=1000)) == 150


# ============================================================ 5. separate memory per user or tenant
async def test_5a_a_tenants_memory_is_unreachable_from_another_and_names_do_not_collide(client, gm):
    ta, tb = tid(gm, "iso-a"), tid(gm, "iso-b")
    (alice,) = await team(client, gm, ta, ["alice"])
    (bob,) = await team(client, gm, tb, ["bob"])
    await call(client, alice, ta, "add_episode", session="s", role="user", content="alice's secret is swordfish")
    await call(client, alice, ta, "assert_fact", subject="vault", predicate="code", obj="swordfish")
    await call(client, bob, tb, "assert_fact", subject="vault", predicate="code", obj="1234")            # the same names, a different tenant
    for op, args in (("history", {"session": "s"}), ("recall", {"query": "vault"}), ("search_text", {"query": "swordfish"}), ("sessions", {}), ("stats", {})):
        r = await client.post(f"/v1/tenants/{ta}/{op}", json=args, headers=bob)
        assert r.status_code == 403, op                                                                  # bob cannot read alice's tenant through any operation
    assert [f["object"] for f in await call(client, alice, ta, "recall", query="vault")] == ["swordfish"]
    assert [f["object"] for f in await call(client, bob, tb, "recall", query="vault")] == ["1234"]
    assert await call(client, bob, tb, "search_text", query="swordfish") == []                           # nothing of alice's turns up in bob's search
    assert gm.db.graph_name(ta) != gm.db.graph_name(tb)                                                  # each tenant is its own graph in the database
    names = await gm.db.list_tenant_graphs()
    assert ta in names and tb in names


async def test_5b_scopes_grants_and_revocation_are_enforced_on_every_call(client, gm):
    t = tid(gm, "scope")
    (rw,) = await team(client, gm, t, ["writer"])
    (ro,) = await team(client, gm, t, ["reader"], scopes=("read",))
    await call(client, rw, t, "add_episode", session="s", role="user", content="hello")
    assert len(await call(client, ro, t, "history", session="s")) == 1                                   # a read-only agent can read
    for op, args in (("add_episode", {"session": "s", "role": "user", "content": "x"}), ("assert_fact", {"subject": "a", "predicate": "b", "obj": "c"}), ("create_task", {"title": "t"})):
        assert (await client.post(f"/v1/tenants/{t}/{op}", json=args, headers=ro)).status_code == 403    # but cannot write
    assert (await client.post(f"/v1/tenants/{t}/care_forget_person", json={"person": "x", "confirm": "x"}, headers=ro)).status_code == 403
    await client.request("DELETE", f"/admin/grants/t2-writer/{t}", headers=ADMIN)
    assert (await client.post(f"/v1/tenants/{t}/history", json={"session": "s"}, headers=rw)).status_code == 403   # revoked: effective on the very next call


async def test_5c_every_account_and_circle_in_care_circle_is_its_own_memory(client, gm):
    ta, tb = tid(gm, "circ-a"), tid(gm, "circ-b")
    await gm.grant("ravi", ta, ("read", "write", "admin"))
    await gm.grant("dev", tb, ("read", "write", "admin"))
    await gm.open("ravi", ta).care_record("asha", "warfarin", dose_text="4 mg")
    await gm.open("dev", tb).care_record("asha", "metformin", dose_text="500 mg")                        # even the same person's name in two circles is two records
    assert [r["drug"] for r in await gm.open("ravi", ta).care_regimen("asha")] == ["warfarin"]
    assert [r["drug"] for r in await gm.open("dev", tb).care_regimen("asha")] == ["metformin"]
    with pytest.raises(Exception):
        await gm.open("dev", ta).care_regimen("asha")                                                    # dev has no access to circle A
    await gm.open("ravi", ta).care_forget_person("asha", confirm="asha")                                 # erasing circle A's person...
    assert [r["drug"] for r in await gm.open("dev", tb).care_regimen("asha")] == ["metformin"]            # ...does not touch circle B
    refs = gm.db.client.select_graph("cc_ref")
    assert not (await refs.query("MATCH (n) WHERE n:Dose OR n:Person RETURN count(n)")).result_set[0][0]  # the shared reference graph holds no one's data


async def test_5d_deleting_a_tenant_removes_all_of_its_memory_and_only_its_memory(client, gm):
    ta, tb = tid(gm, "del-a"), tid(gm, "del-b")
    (a,) = await team(client, gm, ta, ["alice"])
    (b,) = await team(client, gm, tb, ["bob"])
    await call(client, a, ta, "add_episode", session="s", role="user", content="mine")
    await call(client, b, tb, "add_episode", session="s", role="user", content="yours")
    await gm.db.drop_tenant(ta)
    assert ta not in await gm.db.list_tenant_graphs() and tb in await gm.db.list_tenant_graphs()
    assert [e["content"] for e in await call(client, b, tb, "history", session="s")] == ["yours"]
