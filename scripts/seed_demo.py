"""Seed a demo tenant + API keys through the real admin API.
Usage: python scripts/seed_demo.py http://127.0.0.1:8000 ADMIN_KEY"""
import json, sys, urllib.request

base, admin = sys.argv[1], sys.argv[2]
def call(path, body, key, method="POST"):
    r = urllib.request.Request(base + path, data=json.dumps(body).encode(), method=method,
                               headers={"Authorization": "Bearer " + key, "content-type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=20))

key = call("/admin/agents", {"agent": "planner"}, admin)["api_key"]
exe = call("/admin/agents", {"agent": "executor"}, admin)["api_key"]
for a in ("planner", "executor"):
    call("/admin/grants", {"agent": a, "tenant": "acme", "scopes": ["read", "write"]}, admin)
T = lambda op, body, k=key: call(f"/v1/tenants/acme/{op}", body, k)["result"]

ep = T("add_episode", {"session": "kickoff", "role": "user", "content": "Client wants the report by Friday; Carol owns it."})
d = T("assert_fact", {"subject": "report", "predicate": "deadline", "obj": "friday", "sources": [ep["id"]], "exclusive": True})
o = T("assert_fact", {"subject": "report", "predicate": "owner", "obj": "carol", "sources": [ep["id"]], "exclusive": True})
T("assert_fact", {"subject": "carol", "predicate": "works_in", "obj": "finance", "sources": [ep["id"]]})
T("add_skill", {"name": "send-report", "description": "Deliver a client report", "steps": ["draft", "review", "send"], "tags": ["reports"]})
for ok in (True, True, False, True): T("record_run", {"skill": "send-report", "success": ok})
task = T("create_task", {"title": "ship client report"})
T("claim_task", {"task_id": task})
plan = T("create_plan", {"task_id": task, "steps": ["draft", "review with carol", "send by deadline"], "derived_from": [d["id"], o["id"]]})
T("handoff", {"task_id": task, "to_agent": "executor", "note": "plan ready", "plan_id": plan})
ep2 = T("add_episode", {"session": "kickoff", "role": "user", "content": "UPDATE: client moved the deadline to Wednesday."})
d2 = T("assert_fact", {"subject": "report", "predicate": "deadline", "obj": "wednesday", "sources": [ep2["id"]], "exclusive": True})
dec = T("record_decision", {"summary": "schedule delivery for the new deadline", "used": [d2["id"], ep2["id"]], "answer": "deliver by Wednesday"}, exe)
print(json.dumps({"planner_key": key, "executor_key": exe, "task": task, "plan": plan, "decision": dec}))
