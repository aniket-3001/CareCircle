# Track 02, point by point

The brief: *build agents that remember across sessions and share state with each other. Memory should persist, update over time, and be available to every agent that needs it.*

Care Circle is the product built on this. The memory engine under it (`graphmem/`) is generic: any agent can use it over HTTP (`docs/API.md`) or MCP.

## Where the engine and the care record meet (added after the round 3 review)

The review's diagnosis was fair: the engine fitted the brief, but the product's own agents did not use it. What changed:

- **The helper remembers its conversation.** Each answer stores what it was about and the order it listed things; the next question is read against it ("and what about Ravi?", "why is the second one flagged?"). When a reference cannot be resolved it asks which one; it never guesses and never asks the model to. The no-advice check applies to every follow-up. (`tests/test_helper_memory.py`)
- **Agent memory is joined to the care record.** `add_episode` / MCP `remember` and `assert_fact` take `about` (an entry or the person of this circle; checked first); a fact about an entry is found by `recall` through the entry's medicine too, with the path, and retracted when the entry is erased. The note is an ABOUT edge from an episode, labelled "noted by <agent>, unverified", shown beside the entry, and returned by `recall` with the path to the entry. It cannot change a dose, a flag, the checklist or the history log (a test compares the whole record before and after), and erasing the entry redacts it. Handover notes attach to entries the same way. (`tests/test_agent_notes.py`)
- **One demo shows an agent remembering and a second agent holding off** until the carer it affects has seen the change (`scripts/agent_memory_demo.py`, run in CI as `tests/test_agent_memory_demo.py`).
- **Handoffs are handoffs.** A handover note is attached to its entry, addressed to a named carer and accepted by that carer; it is marked stale when the entry changes. (`tests/test_handoff.py`, browser scenario U22)
- **The bot, the web helper and the reminder loop share state.** The Telegram bot asks the same helper, so a carer's conversation is one conversation across web and Telegram; every reminder that really went out is logged against its entry, so "has Meena been reminded?" has an answer. (`tests/test_carecircle.py`, `tests/test_reminder_log.py`)
- **A real model can drive it.** `scripts/agent_demo.py langchain --mode memory` gives a model (Amazon Nova Pro) the memory tools. On 18 October 2026, run by hand once against a local server after the night agent had left its note and Meena had not seen the change, it called `recall` (and got the note with its path), then `care_divergence`, and answered that Meena was behind and it was holding off; it wrote nothing. This is one run of one model, not a benchmark, and it is not part of CI (it calls a paid model).
- **Agents cannot use up shared state.** Claiming reminders needs the owner's right; everyone else reads them with `care_reminders`. (`tests/test_scope_enforced.py`)

What is genuinely this project's, and what is not: episodes, facts with validity times, skills, handoffs and grants are what any agent-memory library does (Graphiti, Zep and Mem0 among them); the engine is not claimed as new. What is specific here is the care coordination built on it: who has seen what, one claim per dose slot (and per tablet), reminders that are delivered or handed back, and notes that sit beside a human-confirmed record without ever rewriting it.

Everything below is checked by `tests/test_track02.py` (18 tests, one section per bullet, driven over the public HTTP API like an outside agent) and `bench/track02_stress.py` (load plus an audit of what was stored). Both run in CI or by hand.

| Brief | What is built | Where | Checked by |
|---|---|---|---|
| **Episodic memory** | An immutable, ordered event log per session: `seq`, a `NEXT` edge to the previous event, who said it, when. Full-text search over events. There is no operation that edits an event. | `add_episode`, `history`, `sessions`, `search_text` in `graphmem/memory.py` | `test_1a`, engine tests |
| **Semantic memory** | Facts (subject, predicate, object) that update over time: an exclusive fact closes the old value and opens the new one; repeating a fact adds support instead of a duplicate; `as_of` answers "what did we believe then"; every fact links to the events it came from and says which agent wrote it; multi-hop recall; forgetting retracts a fact everywhere it was copied. | `assert_fact`, `recall`, `fact_history`, `forget_fact` | `test_1b` |
| **Procedural memory** | Skills with steps and tags; each run's outcome moves win/run counters atomically; `best_skills` ranks by smoothed success rate, so what works rises. | `add_skill`, `record_run`, `best_skills` | `test_1c` |
| The three kinds are one graph | A decision links to the facts and skills it used, and those to the events they came from, so "why did the agent do that" is one traversal. | `record_decision`, `explain` | `test_1d` |
| **Persistent conversation history** | Sessions live in FalkorDB, not in a process: a fresh server and database client read the same history, numbering continues, long histories page backwards. Care Circle's helper chat is stored per carer, survives a restart, and can be cleared. | `history(before_seq)`, `care_chat_*` | `test_2`, `test_2b` |
| **Shared state between agents** | Agents granted on a tenant read and write the same graph, so what one learns is available to the next, with who wrote it. A fork lets an agent explore on a copy and merge or discard; a space lets tenants publish chosen facts to others. | `recall`, forks (`/v1/tenants/{t}/forks`), spaces | `test_3a`, `test_3c` |
| **Handoffs** | A task is created, claimed (one owner), handed to a named agent with a note and a plan, accepted only by that agent, resumed with the whole context in one call, and completed. A plan remembers which facts it was derived from, so when one changes the plan is reported out of date. | `create_task`, `claim_task`, `handoff`, `accept`, `resume`, `complete`, `create_plan`, `check_plan` | `test_3b` |
| **High-concurrency reads and writes** | One conditional write per claim (a single winner however many race; ticking a combination tablet is one claim over all its ingredients, with the same guarantee); sequence numbers assigned inside the database in one statement; reads run on the read path while writes land; FalkorDB's own unique constraints back it up; a full queue is retried with backoff and then answered 503, never dropped. | `graphmem/db.py` (`RetryingGraph`), the queries in `memory.py` | `test_4a` to `test_4e`, `bench/track02_stress.py` |
| **Separate memory per user or tenant** | One graph per tenant (`mem__<id>`), per circle in Care Circle. Every call checks the agent's grant and scope; read scope can run as a database user that may only call `GRAPH.RO_QUERY`; keys are stored only as hashes; revocation applies on the next call; deleting a tenant drops its graph. Public reference data is a separate graph that holds nobody's data. | `graphmem/policy.py`, `docs/API.md` | `test_5a` to `test_5d`, `tests/test_adversarial.py` |

## Misuse is refused, not stored

Probing with bad input found four defects, now fixed and pinned by `test_6a` to `test_6c`: a task could be handed to an agent with no access to the tenant (stranding it); an empty message or a fact with a blank part was stored; a 1 MB message was accepted; a negative `limit` produced a database error (HTTP 500). Now a handoff goes only to an agent who can write in the tenant, a message needs content of at most 100,000 characters, a fact needs a subject, predicate and object, and `limit` must be a whole number from 1 to 5,000, each answered with a 400 and a reason. Out-of-order task moves (finishing an unclaimed task, accepting twice, claiming a finished one) return `false` and change nothing.

## Persistence

Production runs FalkorDB with snapshots only (a save after 60 s with a change or 300 s with 100; no append-only file, because FalkorDB 4.22.1 crashed replaying one, see `docs/FALKORDB_CRASH.md`), on a named volume, with `restart: unless-stopped` (`deploy/docker-compose.prod.yml`), and snapshots to S3 every 6 hours. `scripts/check_persistence.py` proves it: it starts a throwaway FalkorDB with those same settings, writes history, facts, a skill outcome, a claimed task and a care record, restarts the container and reads everything back with a new client (all present, numbering continues), then saves a snapshot, writes one more event and kills the container hard (SIGKILL): the 31 events in the snapshot are back, and the one written after it is reported as kept or lost, not promised (a hard crash can lose up to a minute of writes).

## Load test results

`bench/track02_stress.py`, four phases, each followed by an audit of what the database actually holds. The table of scales below is from earlier single runs, taken before the database was pinned; for the pinned 4.22.1, seven repeated runs with median and range are in `docs/BENCHMARKS.md` ("Repeated runs"). The audits are pass/fail.

| Phase | What happens | Audit |
|---|---|---|
| A write storm | N agents append to **one shared session** and assert facts at once | every event stored, `seq` 1..N with no gap or repeat, no duplicates |
| B mixed | writers and readers on one tenant together | zero torn reads (every page a reader sees is contiguous); every write stored; one current value per fact |
| C claim race | K agents claim one task; then one task each | exactly one winner on the contended task; every uncontended claim succeeds |
| D many tenants | T tenants written at once | no tenant holds anything but its own data |

In-process against a local FalkorDB (no network), laptop, Windows + Docker Desktop:

| Scale | A: req/s | B: req/s | C: req/s | D: req/s | Audits |
|---|---|---|---|---|---|
| 30 agents, 30 tenants | 477 | 296 | 531 | 486 | all pass |
| 150 agents, 50 tenants | 427 | 285 | 532 | 489 | all pass |

A run of this script against the live server is **not** a result to cite: it ran on 17 October against the production database and caused the outage written up in `docs/FALKORDB_CRASH.md`, and the script now refuses any server that is not this machine unless told it is disposable.

Latency under contention (150 agents all writing one session, local): median 130 ms, but the slowest 5 per cent of `add_episode` calls wait about 2 s, because FalkorDB runs one writer at a time per graph and a hot session is one graph. A single engine-level writer sustains about 780 `add_episode` per second into one session. `assert_fact` and reads on the same tenant stay near their median. With a realistic number of agents (30) the p99 is about 140 ms.

`add_episode` cost grows slowly with history (2.5 ms at 500 events, 4 ms at 3,000; measured in-process, sequentially).

## Limits, stated plainly

- One FalkorDB instance, no replica: a hot tenant is bounded by one writer, and a lost disk is recovered from the 6-hourly S3 snapshot, not failed over. The restore path is rehearsed (`scripts/restore_drill.py`: newest production snapshot into a fresh database in 3 seconds, data intact); a hard crash can lose up to the last minute of writes (the database keeps snapshots only, saved after 60 s with a change; see `docs/FALKORDB_CRASH.md`), and a lost disk up to 6 hours (`deploy/RESTORE.md`).
- **A graph per session was measured and rejected.** The 2-second write tail comes from one writer per graph, so a graph per session looked like the cure. Same code, a throwaway comparison against a database set to 2 threads like production: up to 32 concurrent writers the two layouts were within run-to-run noise (about 15%); at 150 writers on 8 or 32 sessions, a graph per session gave 1,100 against 650-750 events/s and halved the slowest 1% (about 170 ms against 290-330 ms). But sending the same 150 writers' events to the one graph in batches of 5 (`add_episodes`) gave 1,250-1,340 events/s, more than the split layout, with no change to the design. The split also makes asking a question across sessions slower (8 sessions: 3 ms against 11 ms; 32 sessions: 3 ms against 40 ms) and every feature that spans sessions a fan-out. So the advice for a busy tenant is to batch, which already exists. Caveats: one machine, load generator and database together, a Python client that tops out near 1,100 events/s on its own, 15 writes per writer; it shows the direction, not production capacity.
- The load test is closed-loop (each simulated agent sends its next request when the last returns) and shows saturation behaviour; it is not a model of any real traffic.
- Vector (paraphrase) recall needs an embedding model; with none configured, recall is lexical plus graph (`tests/test_semantic.py` covers the vector path with a fake embedder).
- The memory engine holds what agents write. It does not judge whether a fact is true.
