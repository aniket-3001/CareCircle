# Design sketch

## Topology

- `ctl` graph: Tenant, Agent, Grant(agent -> tenant, scopes). Policy lives in the graph and is checked by traversal.
- `mem__<tenant>` graph per tenant: all memory for that tenant (hard isolation = separate graph; write parallelism per graph).
- `shared__<space>` graph(s): explicitly published facts; every item keeps provenance back to the publishing tenant.

## Node / edge model (per-tenant graph)

Nodes: Session, Episode (immutable raw event), Entity, Fact (semantic; valid_from, valid_to, recorded_at, version),
Skill (procedural), Run (one execution of a skill, outcome), Task (unit of work/handoff, `version` for compare-and-set),
Plan, Decision (decision trace), Agent (ref).

Edges:

- (Episode)-[:IN_SESSION]->(Session); (Episode)-[:NEXT]->(Episode)            persistent history, ordered
- (Fact)-[:EXTRACTED_FROM]->(Episode); (Fact)-[:ABOUT]->(Entity); (Fact)-[:SUPERSEDES]->(Fact)   semantic + provenance + temporal
- (Skill)-[:LEARNED_FROM]->(Episode); (Run)-[:OF]->(Skill); (Run)-[:SUCCEEDED|FAILED]->(Task)   procedural, success-weighted
- (Task)-[:HANDED_OFF {from,to,at,reason}]->(Agent); (Task)-[:CLAIMED_BY]->(Agent)             coordination, CAS on Task.version
- (Plan)-[:DERIVED_FROM {fact_version}]->(Fact)                                                 lineage: stale-plan detection by traversal
- (Decision)-[:USED]->(Fact|Skill|Plan|Episode)                                                 every answer is traceable

## Where the graph does the work (no graph -> feature disappears)

1. Recall: entity-anchored multi-hop expansion + temporal validity filter + provenance path returned with every answer.
2. Stale-plan check: traverse Plan-DERIVED_FROM->Fact, compare versions / SUPERSEDES chain before an agent acts.
3. Procedural ranking: Skill -> Run -> outcome aggregation per context.
4. Handoff: atomic CAS claim on Task node; HANDED_OFF chain is the audit trail.
5. Policy: Grant edges decide which graphs/scopes an agent may read/write; forget = invalidate + tombstone with reason.

## Proof plan (the demo)

Tests, each run with and without the graph path: (a) tenant leak test, (b) N concurrent agents writing, (c) stale-plan
handoff, (d) kill process -> restart -> memory intact, (e) every answer returns its provenance path.

## Build order (after event opens)

core client + schema -> episodic/semantic write+recall -> tenancy/policy -> handoff CAS + lineage -> procedural -> demo/UI -> README + blog.
