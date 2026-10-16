"""Fill a local FalkorDB with two small synthetic graphs to look at in FalkorDB Browser (docs/EXPLORE.md):

  mem__explore-circle   a care circle: a person, two carers, a regimen with a changed dose, one change a carer has not seen
  mem__explore-agents   agent memory: a session, facts that were superseded, a skill with runs, a task that was handed off, a plan, a decision

  python scripts/seed_explore.py            (FALKORDB_HOST / FALKORDB_PORT as for the app)

Everything is invented; no personal data. Run it again to rebuild both graphs from scratch (only these two names are touched)."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graphmem import Db, GraphMem  # noqa: E402

CIRCLE, AGENTS = "explore-circle", "explore-agents"
H = 3_600_000


async def seed(gm: GraphMem) -> dict:
    for t in (CIRCLE, AGENTS):
        await gm.db.drop_tenant(t)

    # ---- a care circle
    for a in ("ravi-explore", "meena-explore"):
        await gm.grant(a, CIRCLE, ("read", "write", "admin"))
    ravi, meena = gm.open("ravi-explore", CIRCLE), gm.open("meena-explore", CIRCLE)
    ids = {}
    for drug, dose, freq in (("metformin", "500 mg", "twice daily with food"), ("warfarin", "5 mg", "at bedtime"), ("atorvastatin", "20 mg", "at bedtime")):
        ids[drug] = (await ravi.care_record("asha", drug, dose_text=dose, freq_text=freq, source_type="typed"))["id"]
    for i in ids.values():
        await meena.care_ack(i)
    changed = await ravi.care_record("asha", "warfarin", dose_text="7 mg", freq_text="at bedtime", source_type="typed")        # replaces the 5 mg entry
    await ravi.care_record("asha", "clarithromycin", dose_text="500 mg", freq_text="twice daily", source_type="typed")         # a known major interaction with warfarin
    await meena.care_ack(changed["id"])                                                                                      # meena has seen the warfarin change, not the antibiotic

    # ---- agent memory
    for a in ("planner", "coder"):
        await gm.grant(a, AGENTS, ("read", "write"))
    planner, coder = gm.open("planner", AGENTS), gm.open("coder", AGENTS)
    e1 = await planner.add_episode("incident-7", "user", "The payments API returns 502 after the 14:00 deploy")
    e2 = await coder.add_episode("incident-7", "agent", "Rolled back the 14:00 deploy; the 502s stopped")
    e3 = await planner.add_episode("incident-7", "user", "The fix will ship in release 2.4 on Friday")
    f1 = await planner.assert_fact("payments api", "status", "failing", sources=[e1["id"]], exclusive=True)
    f2 = await coder.assert_fact("payments api", "status", "recovered", sources=[e2["id"]], exclusive=True)                   # supersedes the first
    f3 = await planner.assert_fact("release 2.4", "ships_on", "friday", sources=[e3["id"]], exclusive=True)
    await coder.assert_fact("payments api", "depends_on", "ledger service", sources=[e2["id"]])
    await coder.add_skill("rollback-deploy", "Roll a service back to the last good release", ["find last good release", "redeploy it", "watch the error rate"], ["ops"])
    for ok in (True, True, False, True):
        await coder.record_run("rollback-deploy", ok)
    task = await planner.create_task("Fix the 502 on the payments API")
    await planner.claim_task(task)
    plan = await planner.create_plan(task, ["reproduce", "patch the ledger client", "ship in 2.4"], derived_from=[f3["id"] if isinstance(f3, dict) else f3])
    await planner.handoff(task, "coder", "Rolled back already; the patch is yours", plan_id=plan)
    await coder.accept(task)
    await coder.record_decision("Roll back rather than patch forward", used=[f2["id"] if isinstance(f2, dict) else f2], answer="rollback")
    return {"circle": f"mem__{CIRCLE}", "agents": f"mem__{AGENTS}", "reference": "cc_ref"}


async def main() -> None:
    gm = GraphMem(Db(host=os.getenv("FALKORDB_HOST", "localhost"), port=int(os.getenv("FALKORDB_PORT", "6379"))))
    out = await seed(gm)
    print("seeded:", ", ".join(out.values()))
    print("open FalkorDB Browser (http://localhost:3000), connect to localhost:6379, and pick one of those graphs. Queries: docs/EXPLORE.md")


if __name__ == "__main__":
    asyncio.run(main())
