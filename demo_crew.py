"""Three agents (planner / reviewer / implementer) coordinate a change on a real repository through one tenant graph.
Deterministic, no LLM. Usage: PYTHONPATH=. python demo_crew.py [path-to-python-git-repo]   (default: this repository)"""
import asyncio
import sys
import uuid

from graphmem import Db, GraphMem
from graphmem.branch import fork, merge, open_fork
from graphmem.repo_loader import load_repo


async def main(root: str):
    gm = GraphMem(Db()); t = f"crew-{uuid.uuid4().hex[:5]}"
    for a in ("planner", "reviewer", "implementer"):
        await gm.grant(a, t, ("read", "write"))
    planner, reviewer, impl = (gm.open(a, t) for a in ("planner", "reviewer", "implementer"))

    stats = await planner.code_load(**load_repo(root))
    print("0. code graph loaded into the tenant:", stats)
    hub = (await planner.criticality(1))["rows"][0]["file"]
    print(f"1. most critical file by PageRank: {hub}")

    scope = await planner.assert_fact("ticket-42", "scope", hub, exclusive=True)
    task = await planner.create_task("ticket-42: refactor " + hub)
    await planner.claim_task(task)

    br = await fork(gm, "planner", t, "dry-run ticket-42")                  # branch memory, try the change on the copy
    fm = await open_fork(gm, "planner", br["id"])
    imp = await fm.change_impact([hub])
    deps = [r["file"] for r in imp["dependants"]["rows"]][:5]
    print(f"2. dry-run on a fork ({br['copy_ms']} ms copy): changing {hub} touches {len(imp['dependants']['rows'])} dependants, e.g. {deps}")
    print("   Cypher:", imp["dependants"]["cypher"][:110], "...")
    await fm.create_plan(task, [f"update {d}" for d in deps] + ["run tests"], derived_from=[scope["id"]])
    rep = await merge(gm, "planner", br["id"])                               # dry-run merge: nothing applied
    print("3. merge dry-run report:", {k: rep["would_apply"][k] for k in ("tasks", "plans")}, "conflicts:", len(rep["conflicts"]))
    await merge(gm, "planner", br["id"], apply=True)
    plan = (await planner.resume(task))["plan"]["id"]            # the plan written on the fork is now in the tenant

    owner = (await planner.who_to_ask(hub))["rows"]
    print("4. who to ask about it:", owner[:2])
    await planner.handoff(task, "implementer", "plan ready; ask " + (owner[0]["person"] if owner else "nobody"), plan_id=plan)

    other = (await reviewer.criticality(3))["rows"][-1]["file"]
    await reviewer.assert_fact("ticket-42", "scope", other, exclusive=True)  # a teammate re-scopes the ticket mid-flight
    print(f"5. reviewer re-scopes ticket-42 to {other} while the task is in flight")

    await impl.accept(task)
    r = await impl.resume(task)
    chk = r["plan"]["check"]
    print("6. implementer resumes: plan stale?", chk["stale"], "|", [(c["subject"], c["was"], "->", c["now"][0]["value"]) for c in chk["changes"]])
    rb = await impl.rebase_plan(plan)
    print("   rebased plan", rb["plan"], "stale now?", (await impl.check_plan(rb["plan"]))["stale"])
    d = await impl.record_decision("proceed with re-scoped change", [(await impl.recall("ticket-42 scope"))[0]["id"]], "implement in " + other)
    print("7. decision trace:", [(u["type"], u["summary"]) for u in (await impl.explain(d))["used"]])
    await gm.db.drop_tenant(t)
    for f in await gm.db.client.list_graphs():
        if f.startswith(f"fork__{t}"):
            await gm.db.client.select_graph(f).delete()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "."))
