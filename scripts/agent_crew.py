"""Two REAL Claude Code agents (headless `claude -p`) coordinate through graphmem's MCP server on a real repository.

  planner      finds the blast radius of a ticket, records the scope fact, writes a plan derived from it, hands the task off
  (this script then changes the scope fact behind the planner's back, as a third teammate would)
  implementer  resumes the task, notices the plan is stale, rebases it and records a traceable decision

The script then verifies, from the graph itself, that the handoff chain, the stale-plan detection and the decision trace exist.
Needs: the `claude` CLI logged in, FalkorDB on :6379.  PYTHONPATH=. python scripts/agent_crew.py [repo=../data/click] [model=haiku]"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

from graphmem import Db, GraphMem
from graphmem.repo_loader import load_repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_agent(name, key, prompt, model, turns=14):
    cfg = {"mcpServers": {"graphmem": {"command": sys.executable, "args": ["-m", "graphmem.mcp_server"],
                                       "env": {"GRAPHMEM_API_KEY": key, "PYTHONPATH": ROOT}}}}
    f = os.path.join(tempfile.mkdtemp(), f"{name}.json")
    json.dump(cfg, open(f, "w"))
    p = subprocess.run([shutil.which("claude") or "claude", "-p", "--model", model, "--strict-mcp-config", "--mcp-config", f,
                        "--allowedTools", "mcp__graphmem__*", "ToolSearch", "--disallowedTools", "Bash", "Edit", "Write", "Read", "Glob", "Grep", "WebFetch", "WebSearch",
                        "--max-turns", str(turns), "--output-format", "json"], capture_output=True, text=True, cwd=ROOT, timeout=600, input=prompt)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        out = {"result": p.stdout[-500:] + p.stderr[-500:]}
    print(f"--- {name}: turns={out.get('num_turns')} cost=${out.get('total_cost_usd')}\n{str(out.get('result'))[:900]}\n")
    return out


async def main(repo, model):
    gm, t = GraphMem(Db()), f"agents-{uuid.uuid4().hex[:5]}"
    keys = {a: await gm.issue_key(a) for a in ("planner", "implementer", "teammate")}
    for a in keys:
        await gm.grant(a, t, ("read", "write"))
    boot = gm.open("teammate", t)
    print("code graph:", await boot.code_load(**load_repo(repo)))
    hub = (await boot.criticality(1))["rows"][0]["file"]
    print("tenant", t, "| most critical file:", hub)

    run_agent("planner", keys["planner"], f"""You are the PLANNER agent. Use ONLY the graphmem MCP tools. Tenant: {t}.
1. call op=change_impact with args {{"paths": ["{hub}"]}} to see what depends on {hub}.
2. call op=assert_fact with args {{"subject": "ticket-7", "predicate": "scope", "obj": "{hub}", "exclusive": true}}; keep the returned id.
3. call op=create_task with args {{"title": "ticket-7: refactor {hub}"}}; keep the task id. Then call op=claim_task with {{"task_id": <id>}}.
4. call op=create_plan with args {{"task_id": <id>, "steps": [<3 short steps naming dependants from step 1>], "derived_from": [<the fact id from step 2>]}}; keep the plan id.
5. call op=handoff with args {{"task_id": <id>, "to_agent": "implementer", "note": "plan ready", "plan_id": <plan id>}}.
Finish with one line: TASK=<task id> PLAN=<plan id>.""", model)

    rows = await boot._q("MATCH (t:Task) RETURN t.id ORDER BY t.created_at DESC LIMIT 1", scope="read")
    if not rows:
        print("FAIL: planner created no task"); return 1
    task = rows[0][0]
    other = (await boot.criticality(3))["rows"][-1]["file"]
    await boot.assert_fact("ticket-7", "scope", other, exclusive=True)
    print(f"teammate re-scopes ticket-7 to {other} while the task is handed off\n")

    run_agent("implementer", keys["implementer"], f"""You are the IMPLEMENTER agent. Use ONLY the graphmem MCP tools. Tenant: {t}. Task id: {task}.
1. call op=accept with args {{"task_id": "{task}"}}.
2. call op=resume with args {{"task_id": "{task}"}} and read the plan check: say whether the plan is stale and why.
3. If stale, call op=rebase_plan with args {{"plan_id": <the plan id from resume>}}.
4. call op=recall with args {{"query": "ticket-7 scope"}}; take the id of the CURRENT fact.
5. call op=record_decision with args {{"summary": "proceed with re-scoped ticket-7", "used": [<that fact id>], "answer": <one sentence>}}.
Finish with one line: STALE=<true/false> DECISION=<decision id>.""", model)

    # ---- verify from the graph, not from what the agents said
    chk = []
    h = await boot._q("MATCH (t:Task {id:$t})-[r:HANDED_OFF]->(a:Agent) RETURN r.from, r.to", {"t": task}, scope="read")
    chk.append(("handoff planner -> implementer recorded", h == [["planner", "implementer"]]))
    plans = await boot._q("MATCH (p:Plan)-[:FOR]->(:Task {id:$t}) OPTIONAL MATCH (p)-[:REVISES]->(o:Plan) RETURN p.id, o.id", {"t": task}, scope="read")
    chk.append(("implementer rebased the stale plan (a revising plan exists)", any(r[1] for r in plans)))
    d = await boot._q("MATCH (d:Decision {agent:'implementer'})-[:USED]->(f:Fact) RETURN d.id, f.sname, f.otext", scope="read")
    chk.append(("decision trace links to the re-scoped fact", any(r[2] == other for r in d)))
    for name, ok in chk:
        print(("PASS " if ok else "FAIL ") + name)
    if os.getenv("KEEP_TENANT"):
        print("\nkept tenant for inspection (FalkorDB Browser on :3000):", t)
    else:
        ctl = await gm._ctl()
        await gm.db.drop_tenant(t)
        await ctl.query("MATCH (n) WHERE n.id IN ['planner','implementer','teammate',$t] DETACH DELETE n", {"t": t})
        await ctl.query("MATCH (k:ApiKey) WHERE NOT ()-[:HAS_KEY]->(k) DELETE k")
    return 0 if all(ok for _, ok in chk) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "../data/click", sys.argv[2] if len(sys.argv) > 2 else "haiku")))
