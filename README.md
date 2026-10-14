# graphmem (working name) - graph-native memory & coordination for agents on FalkorDB

Agents that remember across sessions and share state, where **the graph is the engine**: recall, handoffs,
stale-plan detection, skill ranking, access control and forgetting are all Cypher traversals on FalkorDB.
Remove FalkorDB and there is no product (there is no second store). No LLM key or GPU is needed for the core.

## Run
```bash
docker run -d -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest   # 3000 = FalkorDB Browser
python -m venv .venv && .venv/Scripts/pip install falkordb pytest pytest-asyncio   # Linux/macOS: .venv/bin
PYTHONPATH=. python demo.py          # handoff + stale-plan + decision-trace walkthrough
python -m pytest -q                  # 33 tests (requirements, HTTP/MCP, spaces, extraction, rate limits, retry)
PYTHONPATH=. python bench/proof.py   # 8 end-to-end scenarios (restarts the falkordb-dev container; --no-restart to skip)
PYTHONPATH=. python bench/load.py 16 4 40   # tenants agents ops-per-agent
```

## Interfaces
- HTTP API + UI: `pip install fastapi uvicorn mcp httpx`, then `GRAPHMEM_ADMIN_KEY=secret python -m graphmem.api` and open http://127.0.0.1:8000
  (create an agent with `POST /admin/agents`, grant it a tenant with `POST /admin/grants`, paste its `gm_...` key into the page).
  `python scripts/seed_demo.py http://127.0.0.1:8000 secret` loads a demo tenant.
- MCP (stdio): `GRAPHMEM_API_KEY=gm_... python -m graphmem.mcp_server`. Same operations and authorization as the HTTP API.
- API keys are stored only as SHA-256 hashes in the `ctl` graph.
- Shared spaces (`graphmem/spaces.py`): explicit per-fact publishing; only the fact triple crosses, never raw conversations;
  forgetting a fact removes its published copies. Also exposed over HTTP (`/v1/spaces/...`) and MCP.

## Track 02 requirement -> where it lives
| Requirement | Graph structure | Code / test |
|---|---|---|
| Episodic | `Episode -NEXT-> Episode`, `-IN_SESSION-> Session`, immutable, ordered atomically in-graph | `add_episode`, `history` / `test_episodic_*` |
| Semantic | `Fact -SUBJECT/OBJECT-> Entity`, `-EXTRACTED_FROM-> Episode`, `SUPERSEDES` chain with validity window; `as_of` queries | `assert_fact`, `recall`, `fact_history` |
| Procedural | `Skill <-OF- Run -FOR-> Task`; ranking = smoothed success rate from run outcomes | `add_skill`, `record_run`, `best_skills` |
| Persistent history | everything lives in FalkorDB; new process sees it | `test_memory_survives_new_client` |
| Shared state & handoffs | `Task` with version; claim/handoff are single guarded queries (compare-and-set); `HANDED_OFF` chain; `Plan -DERIVED_FROM-> Fact` lineage | `claim_task`, `handoff`, `check_plan`, `rebase_plan`, `resume` |
| High concurrency | graph per tenant (writes serialize per graph); atomic single-query transitions | `test_concurrent_writers_*`, `test_claim_race_*`, `bench/load.py` |
| Per tenant | graph `mem__<tenant>`; grants `(Agent)-[:GRANTED]->(Tenant)` in a `ctl` graph checked on every query | `policy.py`, `test_tenant_isolation_and_policy` |
| Traceable decisions | `Decision -USED-> Fact/Episode/Skill/Plan`, answers carry provenance + graph path | `record_decision`, `explain` |
| Forgetting | tombstone with reason, value scrubbed from whole graph, optional source redaction | `forget_fact` / `test_forget_*` |

## Measured (laptop: Windows 11, 12 logical cores, Docker Desktop; single runs, indicative only)
- FalkorDB: 8 writers x 6 heavy batches: one shared graph 2.19 s vs graph-per-tenant 0.93 s (2.36x). Details in `docs/DECISION.md`.
- Engine, in-process, sequential: add_episode ~3 ms, policy check ~1 ms, recall ~14 ms.
- **HTTP load test** (`bash bench/run_http_load.sh <api_procs> <tenants> <agents> <seconds> <load_procs>`), 64 agents over 16 tenants,
  mixed workload, every request through HTTP -> API -> FalkorDB (about 3 database queries per request):

  | API processes | req/s | p50 write | p50 recall | failed | integrity |
  |---|---|---|---|---|---|
  | 1 | 244 | 214 ms | 323 ms | 0 | 16/16 tenants gap-free, no acknowledged write lost |
  | 2 | 322 | 161 ms | 253 ms | 0 | same |
  | 4 | 448 | 111 ms | 184 ms | 0 | same |
  | 8 (128 agents) | ~395 | 237 ms | 382 ms | 0 | same |

  Scaling flattens at 4-8 API processes because the test machine itself runs out of CPU (API processes ~100% of a core each,
  plus load generators and FalkorDB), so these are lower bounds for dedicated hardware. Not tested: a second machine, FalkorDB Cloud.
- Overload behaviour: FalkorDB rejects queries beyond `MAX_QUEUED_QUERIES` (default 25). Before the fix ~13% of requests failed with
  HTTP 500 at 8 processes; now the engine retries that exact error with backoff and, if still overloaded, answers 503 + `Retry-After`.

## Honest limits
- Extraction: `ingest` turns text into facts with deterministic rules (narrow: clear statements only) or, if `GRAPHMEM_LLM_URL/MODEL/KEY` are set on the server, an OpenAI-compatible LLM. The LLM path is tested only against a fake server; its quality is unmeasured.
- Rate limiting is per API process (in memory).
- Recall is lexical entity matching + graph expansion, no embeddings yet. It is explainable but will miss paraphrases.
- Shared spaces are not yet shown in the UI.
- Persistence: the quick-start `docker run` is snapshot-only. For durability use `GRAPHMEM_ADMIN_KEY=... docker compose up -d --build` (volume + append-only file). Tested: data and API keys survive `docker kill`; with `appendfsync everysec` up to ~1 s of writes can be lost in a crash.
- Not benchmarked on LoCoMo/LongMemEval; we make no accuracy claims.
- FalkorDB quirk found: `MATCH (a) WHERE ... MATCH (a)-[..]` silently returns no rows unless a `WITH a` sits between.

See `docs/DECISION.md` (why not Graphiti/Hindsight/Mem0, with spike evidence) and `docs/DESIGN_SKETCH.md`.
