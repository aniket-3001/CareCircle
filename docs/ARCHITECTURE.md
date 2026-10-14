# Architecture

```mermaid
flowchart LR
  subgraph Agents
    A1[Claude Code / Cursor / custom agent]
  end
  A1 -- MCP stdio --> MCP[mcp_server.py]
  A1 -- HTTP bearer key --> API[api.py FastAPI]
  UI[Web UI /] --> API
  MCP --> OPS[ops.py whitelisted operations]
  API --> OPS
  OPS --> POL[policy.py grants checked on every query]
  POL --> MEM[memory.py TenantMemory + codegraph.py tools]
  OPS --> SP[spaces.py shared spaces]
  API --> BR[branch.py fork / dry-run / merge]
  MEM & SP & BR --> DB[(FalkorDB)]
  subgraph FalkorDB graphs
    CTL[ctl: agents, grants, keys, forks]
    T1[mem__tenant: memory + code graph]
    F1[fork__tenant__id: GRAPH.COPY branch]
    S1[shared__space: published facts]
  end
  DB --- CTL & T1 & F1 & S1
```

Request path: key -> `ctl` lookup (agent) -> op whitelist -> grant check (`read`/`write`/`admin`) -> parameterised Cypher on the
tenant's graph (retried only on FalkorDB's "queue full" error, 503 if it persists).

## Merge flow
```mermaid
sequenceDiagram
  participant P as agent
  participant T as mem__t (tenant graph)
  participant F as fork__t__id
  P->>T: fork: GRAPH.COPY (snapshot_ts)
  T-->>F: copy of nodes, edges, indexes
  P->>F: assert_fact / create_plan / ... (same API)
  P->>T: merge dry-run: conflicts (exclusive facts changed since snapshot), plans with outdated inputs
  P->>T: merge apply: replay fork-new items (skip or overwrite conflicts), then check new plans for staleness
  P->>F: delete graph
```

## Why one graph per tenant
Hard isolation (no tenant filter to forget in a query) and FalkorDB serializes writes per graph, so tenants write in parallel
(2.36x on heavy writes in our spike, see `docs/DECISION.md`). One hot tenant with many writers is bounded by single-graph write
speed; batch writes (`UNWIND`) for that case.
