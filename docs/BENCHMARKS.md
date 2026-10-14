# Benchmarks

All numbers are single runs on one laptop (Windows 11, Docker Desktop, FalkorDB graph module 6.0.2) and indicative only.
The load generator and the database share the CPU. Scripts are in `bench/`; each prints its own caveats.

## B1 Stale-plan detection (`bench/coord_bench.py`, 5 seeds)

200 plans over 300 base + 150 derived + 50 second-level facts; 15 base facts change (about 54.8 plans are truly stale).
Ground truth is an independent Python closure over the generator's dependency table.

| System | Missed stale plans (unsafe) | Wasted redos | Notes |
|---|---|---|---|
| Flat memory (no lineage) | 54.8 | 0 | never notices |
| Optimistic concurrency (global version) | 0 | 145 | precision 0.27 |
| Per-key versions | 33 | 0 | recall 0.40, misses derived facts |
| graphmem lineage (`DERIVED_FROM` / `INFERRED_FROM` traversal) | 0 | 0 | about 0.5 s to check 200 plans |

A baseline that kept a full dependency table would match graphmem; the claim is one-query traversal with provenance, not impossibility elsewhere.

## B2 Concurrent edits: branch/merge vs alternatives (`bench/branch_bench.py`, 5 seeds)

8 agents start from one snapshot of 200+ exclusive facts and each performs 20 writes; `overlap` is the share of writes aimed at a hot set
of 10 keys the others also write with different values. Ground truth is serial execution. Only the `graph` row runs on FalkorDB (real
`GRAPH.COPY` forks, dry-run merge, apply with `on_conflict=skip`, then re-assert only the skipped writes); the other rows are in-process
models of the strategy. "Wall" is in write units (agents in parallel; graph redo writes are serialized through the tenant graph).

| overlap | system | true conflicts | caught | silent overwrites | redone writes | wall | final == serial truth |
|---|---|---|---|---|---|---|---|
| 25% | last-writer-wins | 30 | 0 | **30** | 0 | 20 | 5/5 |
| 25% | OCC (redo whole task) | 30 | 30 | 0 | 140 | 40 | 5/5 |
| 25% | global lock | 30 | 0 (prevented) | 0 | 0 | 160 | 5/5 |
| 25% | graph fork + merge | 30 | 30 | 0 | **30** | 50 | 5/5 |
| 50% | last-writer-wins | 70 | 0 | **70** | 0 | 20 | 5/5 |
| 50% | OCC (redo whole task) | 70 | 70 | 0 | 140 | 40 | 5/5 |
| 50% | global lock | 70 | 0 (prevented) | 0 | 0 | 160 | 5/5 |
| 50% | graph fork + merge | 70 | 70 | 0 | **70** | 90 | 5/5 |

With no overlap all systems agree (0 conflicts). The graph approach redoes only the conflicting writes (30/70 vs 140 for whole-task OCC)
and never overwrites silently; at 50% overlap it is slower in wall time than OCC in this model because resolution writes go through one
graph. The point is lost work and safety, not speed. Synthetic; OCC/lock/LWW are models, not measured systems.

## B4 Real git history (`bench/real_history.py`)

Question: given a file, which other files change in the same commit? The graph (imports, calls, co-change counts) is built from
the oldest 80% of each repo's commits and tested on the newest 20% (commits touching 2-15 python files). 10 candidates per query.

| repo (licence) | queries | method | recall@10 | MRR |
|---|---|---|---|---|
| click (BSD-3) | 306 | random | 0.119 | 0.101 |
| | | file-name/directory similarity | 0.233 | 0.235 |
| | | co-change counts only | **0.508** | **0.522** |
| | | import graph only | 0.140 | 0.138 |
| | | fused (RRF of co-change + graph) | 0.497 | 0.447 |
| flask (BSD-3) | 202 | random | 0.100 | 0.100 |
| | | file-name/directory similarity | 0.335 | 0.273 |
| | | co-change counts only | 0.419 | 0.431 |
| | | import graph only | 0.288 | 0.257 |
| | | fused | **0.488** | **0.443** |
| requests (Apache-2.0) | 83 | random | 0.222 | 0.203 |
| | | file-name/directory similarity | 0.239 | 0.323 |
| | | co-change counts only | 0.213 | 0.268 |
| | | import graph only | 0.336 | 0.326 |
| | | fused | 0.312 | **0.354** |

Reading: co-change history is the strongest single signal on two of three repos; the import graph alone beats it on `requests`
(37 files, most edits touch neighbours); fusing the two is best or near-best everywhere except click, where it is slightly below
co-change alone. We do not claim the graph beats history; the value is that both live in one graph and are queried together.
Caveats: import/call structure is read from HEAD (a few edges may post-date the training window; the co-change signal is leak-free);
only python files are modelled; small repos, no tuning of the fusion.

Reproduce: `git clone` the three repos next to this one, then `PYTHONPATH=. python bench/real_history.py ../data/click ../data/flask ../data/requests`.

## B7 Load and durability (`bench/http_load.py`)

64 agents over 16 tenants, mixed workload over real HTTP; every acknowledged write verified afterwards.

| API processes | req/s | p50 write | p50 recall | failed | integrity |
|---|---|---|---|---|---|
| 1 | 244 | 214 ms | 323 ms | 0 | 16/16 tenants gap-free |
| 2 | 322 | 161 ms | 253 ms | 0 | same |
| 4 | 448 | 111 ms | 184 ms | 0 | same |
| 8 (128 agents) | ~395 | 237 ms | 382 ms | 0 | same |

Scaling flattens because the test machine runs out of CPU, so these are lower bounds. FalkorDB rejects queries beyond
`MAX_QUEUED_QUERIES` (25); the engine retries that exact error with backoff and answers 503 + `Retry-After` if it persists.
