"""End-to-end demo: two agents share one tenant's memory, hand off a task, a requirement changes mid-flight,
and the receiving agent catches the stale plan by graph traversal. Run: python demo.py (needs FalkorDB on :6379)."""
import asyncio, uuid
from graphmem import Db, GraphMem

async def main():
    gm = GraphMem(Db()); t = f"demo-{uuid.uuid4().hex[:5]}"
    for a in ("planner", "executor"): await gm.grant(a, t, ("read", "write"))
    planner, executor = gm.open("planner", t), gm.open("executor", t)

    ep = await planner.add_episode("kickoff", "user", "Client wants the report by Friday; Carol owns it.")
    f_dead = await planner.assert_fact("report", "deadline", "friday", sources=[ep["id"]], exclusive=True)
    f_own = await planner.assert_fact("report", "owner", "carol", sources=[ep["id"]], exclusive=True)
    task = await planner.create_task("ship client report")
    await planner.claim_task(task)
    plan = await planner.create_plan(task, ["draft", "review with carol", "send by deadline"],
                                     derived_from=[f_dead["id"], f_own["id"]])
    await planner.handoff(task, "executor", "plan ready", plan_id=plan)
    print("1. planner handed off task with plan", plan)

    ep2 = await planner.add_episode("kickoff", "user", "UPDATE: client moved the deadline to Wednesday.")
    await planner.assert_fact("report", "deadline", "wednesday", sources=[ep2["id"]], exclusive=True)
    print("2. requirement changed AFTER the plan was written")

    await executor.accept(task)
    r = await executor.resume(task)
    print("3. executor resumes. handoff chain:", [(h['frm'], h['to']) for h in r["handoffs"]])
    chk = r["plan"]["check"]
    print("   plan stale?", chk["stale"])
    for c in chk["changes"]: print(f"   - '{c['subject']} {c['predicate']}': planned on {c['was']!r}, now {c['now'][0]['value']!r}")
    rb = await executor.rebase_plan(plan)
    print("4. executor rebased the plan ->", rb["plan"], "| stale now?", (await executor.check_plan(rb['plan']))["stale"])

    facts = await executor.recall("report deadline")
    d = await executor.record_decision("schedule delivery for the new deadline", [f["id"] for f in facts if f["current"]] + [ep2["id"]],
                                       "deliver by Wednesday")
    print("5. decision trace:")
    for u in (await executor.explain(d))["used"]:
        print(f"   used {u['type']}: {u['summary']}  (from episodes {u['source_episodes']})")
    await gm.db.drop_tenant(t)
    await (await gm._ctl()).query("MATCH (t:Tenant {id:$t}) DETACH DELETE t", {"t": t})   # also remove tenant + grants from ctl
asyncio.run(main())
