"""Load a local python git checkout into a tenant through the real HTTP API (code graph for the UI's Code graph tab).
Usage: PYTHONPATH=. python scripts/seed_code_demo.py http://127.0.0.1:8000 ADMIN_KEY path/to/repo [tenant=acme] [agent=planner]"""
import json, sys, urllib.request

from graphmem.repo_loader import load_repo

base, admin, repo = sys.argv[1:4]
tenant = sys.argv[4] if len(sys.argv) > 4 else "acme"
agent = sys.argv[5] if len(sys.argv) > 5 else "planner"


def call(path, body, key):
    r = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Authorization": "Bearer " + key, "content-type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=120))


key = call("/admin/agents", {"agent": agent}, admin)["api_key"]          # issues a fresh key for the agent
call("/admin/grants", {"agent": agent, "tenant": tenant, "scopes": ["read", "write"]}, admin)
data = load_repo(repo)
print(call(f"/v1/tenants/{tenant}/code_load", data, key)["result"])
print("agent key (paste into the UI):", key)
