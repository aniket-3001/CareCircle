# Starting-point decision

## Decision

**Do not run Graphiti as the runtime. Build our own memory engine directly on FalkorDB (Cypher),
reusing the best *ideas* from Graphiti, Hindsight, MemP and Planfence.**
LLM extraction is an optional plug-in; the graph-native core must work without any LLM key.

## Evidence (all measured on this machine: Windows 11, Docker Desktop, FalkorDB `latest` = graph module 6.0.2

graphiti-core 0.30.2, falkordb-py 1.8.0). Single runs; treat as indicative, not benchmarks.

| Spike | Result |
| --- | --- |
| 1  FalkorDB light writes (16 writers, 150 each) | one graph 3140 w/s vs graph-per-tenant 3527 w/s (1.12x) -> client/network bound, not server bound |
| 1b FalkorDB heavy writes (8 writers x 6 x 20k-row CREATE) | one graph 2.19s vs graph-per-tenant 0.93s -> **2.36x**: write serialization is per graph, tenants parallelize |
| 1b reads during heavy writes | same graph: p50 6.8ms / p99 58.8ms; other graph: p50 2.2ms / p99 21.9ms -> reads are not blocked by writers (snapshot reads) |
| 2  Graphiti tenancy (12 tenants x 25 episodes, interleaved) | writes isolated 0/12 wrong; **reads via shared driver wrong 12/12 (return 0 rows)** (issue #1842 reproduced at node-class level; decorator-wrapped `Graphiti.search` paths not exercised) |
| 2  clone churn | 120 `clone()` -> 120 un-awaited `build_indices` tasks, **20 `MaxConnectionsError`** (issue #1934 reproduced) |
| 3  workaround: one long-lived driver per tenant | writes OK, reads 0/12 wrong, 0 leaks, adversarial cross-read returns 0 rows, 0 connection errors |
| 3  index build on current server | **13x `db.idx.fulltext.createNodeIndex` rejected** ("received 5 arguments, expected at most 1"): graphiti-core 0.30.2 fulltext index DDL is incompatible with FalkorDB graph 6.0.2 |

Also: no LLM API key exists in this environment, and Graphiti ingestion needs one for every episode.

## Why not the alternatives

- Graphiti: three live defects on exactly our multi-tenant path; the workaround (driver per tenant) works but
  fulltext/keyword search is broken on the current FalkorDB, and we would be gluing around its core.
- Hindsight: graph is Postgres tables + SQL CTEs; no FalkorDB path; porting = rewriting the core (see research notes).
- Mem0: removed external graph stores in v3. Cognee: FalkorDB only via community adapter; ACL mechanics unclear.

## What we take from each

- Graphiti: Episode -> Fact provenance, bi-temporal fact validity (invalidate, never delete), hybrid retrieval.
- Hindsight: retain / recall / reflect, parallel retrieval strategies + rank fusion, causal edges, "bank" per tenant.
- MemP: procedural memory = skills distilled from trajectories, updated by success/failure.
- Planfence: plans store the exact fact versions they were derived from; check lineage before acting.
- Collaborative Memory / GateMem: private vs shared tiers, provenance on every fragment, explicit forgetting.

## Known caveats of this decision

- Spikes ran on one laptop, one run each, Docker Desktop networking.
- Graphiti's decorator-protected paths (`Graphiti.search`, `retrieve_episodes`) were not exercised (no LLM key).
- FalkorDB per-graph write parallelism is measured (2.36x) but graph-count/memory limits at 1000s of tenants are untested.
