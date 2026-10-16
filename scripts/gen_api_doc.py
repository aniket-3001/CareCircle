"""Write docs/API.md from the live operation table, so the reference cannot drift from the code. Run: python scripts/gen_api_doc.py"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from graphmem import ops  # noqa: E402

HEAD = """# HTTP API

Interactive reference for the routes with typed bodies (sign-in, account, circles, invites, push, intake, forks): `/docs` (Swagger) and `/openapi.json` on any running server.

Every other operation goes through one route, and the table below is generated from the code (`python scripts/gen_api_doc.py`).

```
POST /v1/tenants/{circle}/{op}
Authorization: Bearer <session token or agent key>
Content-Type: application/json

{"person": "asha"}
```

- The body is the operation's arguments as a JSON object; the reply is `{"result": ...}`.
- `{circle}` is the circle's id (the page does not show it; `GET /v1/account/circles` lists yours). Authorisation is checked inside the engine on every query: a read-scope key cannot call a write operation.
- Arguments are bound against the real method signature; unknown or missing ones are rejected before the graph is touched.
- The same table backs the MCP server: over stdio (`python -m graphmem.mcp_server`) and over HTTP at `POST /mcp` (streamable HTTP, `Authorization: Bearer <key>`, stateless; off with `CC_MCP_HTTP=0`).
- Care Circle records and cross-checks; none of these operations returns advice.

| Operation | Scope | Arguments (* required) | What it does |
|---|---|---|---|
"""
rows = []
for name, d in ops.describe().items():
    args = ", ".join(f"`{a['name']}`" + ("*" if a["required"] else "") for a in d["args"]) or "none"
    rows.append(f"| `{name}` | {d['scope']} | {args} | {d['doc'].replace('|', '/')} |")
pathlib.Path(__file__).resolve().parents[1].joinpath("docs", "API.md").write_text(HEAD + "\n".join(rows) + "\n", encoding="utf-8")
print(len(rows), "operations")
