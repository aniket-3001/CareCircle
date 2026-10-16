# HTTP API

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
| `add_episode` | write | `session`*, `role`*, `content`*, `agent`, `at` | Append an immutable event to a session. Ordering (seq + NEXT edge) is assigned atomically in-graph. |
| `add_episodes` | write | `session`*, `items`*, `agent` | Append several events to one session in a single write: one authorisation, one query, and a contiguous block of sequence numbers with |
| `assert_facts` | write | `facts`* | Assert several facts with one authorisation. Each item takes the arguments of assert_fact (subject, predicate, obj, and optionally |
| `ingest` | write | `session`*, `role`*, `content`* | Store a message as an episode, extract facts from it, and link each fact to that episode. |
| `history` | read | `session`*, `limit`, `before_seq` | Persistent conversation history, oldest first, newest `limit` turns (optionally before a seq). |
| `sessions` | read | `limit` |  |
| `search_episodes` | read | `query`*, `limit` |  |
| `search_text` | read | `query`*, `limit` | Full-text search over episode content (FalkorDB full-text index, prefix match on every word, best score first). |
| `assert_fact` | write | `subject`*, `predicate`*, `obj`*, `sources`, `conf`, `exclusive`, `valid_from`, `agent`, `at`, `inferred_from` | Create-or-reinforce a fact. `exclusive` predicates (one value at a time, e.g. 'lives_in') supersede |
| `recall` | read | `query`*, `as_of`, `hops`, `limit`, `mode` | Entity-anchored graph recall. Every result carries its provenance (source episodes) and the graph path |
| `fact_history` | read | `subject`*, `predicate`* | Full bi-temporal chain for (subject, predicate): every value ever held, oldest first. |
| `embed_missing` | write | `limit` | Backfill vectors for current facts that have none (e.g. after enabling embeddings on an existing graph). |
| `forget_fact` | write | `fact_id`*, `reason`*, `redact_sources` | Retract a fact: close it, blank its content, drop its links, leave a tombstone with the reason. |
| `add_skill` | write | `name`*, `description`*, `steps`*, `tags`, `sources` |  |
| `record_run` | write | `skill`*, `success`*, `task_id`, `notes`, `agent` | Record one execution outcome; the skill's win/run counters (its ranking signal) move atomically. |
| `best_skills` | read | `tags`, `limit` | Rank skills for a context by smoothed success rate (Laplace), then by experience. |
| `skill_runs` | read | `skill`*, `limit` |  |
| `create_task` | write | `title`*, `payload` |  |
| `claim_task` | write | `task_id`*, `expected_version` | Atomic claim: succeeds for exactly one caller even if many race (guard is in the WHERE clause). |
| `handoff` | write | `task_id`*, `to_agent`*, `note`, `plan_id`, `expected_version` | Owner hands the task to another agent. Fails (False) if the caller is not the owner or state moved on. The receiver must be able to |
| `accept` | write | `task_id`* |  |
| `complete` | write | `task_id`*, `result` |  |
| `get_task` | read | `task_id`* |  |
| `open_tasks` | read | `limit` |  |
| `create_plan` | write | `task_id`*, `steps`*, `derived_from`, `revises` | A plan remembers exactly which facts it was derived from, so staleness is a graph traversal. |
| `check_plan` | read | `plan_id`* | Is any input of this plan outdated? Walks DERIVED_FROM then SUPERSEDES* to the current value. |
| `rebase_plan` | write | `plan_id`*, `steps` | Create a revised plan re-derived from the current versions of every input. Returns the diff. |
| `resume` | read | `task_id`* | Everything a receiving agent needs: task, handoff chain, latest plan + staleness, plan inputs. |
| `graph_schema` | read | none | What this graph holds: node labels and relationship types, each with a count. |
| `graph_path` | read | `source`*, `target`*, `max_hops`, `source_label`, `target_label` | Shortest path between two nodes, ignoring edge direction: the nodes on it and the relationship between each pair. |
| `graph_influence` | read | `metric`, `label`, `top` | The most influential nodes: metric 'pagerank' (many well-connected nodes point here) or 'betweenness' (many shortest paths go through here). |
| `graph_communities` | read | `method`, `label`, `top` | Groups of nodes that belong together: method 'wcc' (connected components) or 'labelpropagation' (communities inside a connected graph). |
| `graph_neighbourhood` | read | `ref`*, `depth`, `label`, `limit` | Everything within `depth` hops of one node, ignoring direction, nearest first (at most `limit` nodes). |
| `care_record` | write | `person`*, `drug`*, `action`, `dose_text`, `freq_text`, `source_type`, `quote`, `source_text`, `confirm`, `at`, `edited` | A change to what `person` takes. action 'set' (start/change) or 'stop'. The previous current entry is closed and linked |
| `care_confirm` | write | `dose_id`* | A person confirms a pending entry (after looking at the quote beside the source). Makes it current. |
| `care_regimen` | read | `person`*, `as_of` | What `person` takes now, or at `as_of` (ms): confirmed 'set' entries valid at that time. |
| `care_check` | read | `person`*, `as_of` | Interaction flags for the regimen at `as_of`, from the shared reference graph (sources attached; never 'safe'). |
| `care_resolve` | read | `text`*, `n` | Top-n drug name candidates for an OCR/voice string. Nothing is auto-accepted; a person chooses. |
| `care_ack` | write | `dose_id`* | The calling carer says they have seen this change. |
| `care_divergence` | read | `person`*, `now` | Per carer: confirmed changes they have not acknowledged and a [0,1] divergence score. Older unacknowledged changes count |
| `care_nudges` | write | `person`*, `now`, `remind_after_h`, `escalate_after_h`, `hold` | Reminders due: unacknowledged changes older than remind_after_h -> 'remind' that carer; older than escalate_after_h -> |
| `care_reminders` | read | `person`*, `now`, `remind_after_h`, `escalate_after_h` | Reminders that are due, as a read-only preview: nothing is claimed, so looking at them never uses them up (care_nudges claims and delivers). |
| `care_give` | write | `person`*, `drug`*, `slot`* | Record that the calling carer gave `drug` for dose slot `slot` (e.g. '2026-10-16 08:00'). A slot can be claimed once: |
| `care_gives` | read | `person`*, `limit` |  |
| `care_people` | read | none | Patients and carers known in this circle. |
| `care_drug_info` | read | `drug`* | What public sources say about one medicine on record: the official label's own words (openFDA / DailyMed), the RxNorm identifier, and |
| `care_recalls` | read | `person`* | Ongoing public recalls listed for the medicines on record. Only medicine names go out. Shown as published; whether one applies depends on the |
| `care_measure` | write | `person`*, `kind`*, `value`*, `unit`, `at`, `note` | Record one reading a carer took or was told. Refused only when the number cannot be a real reading (a typing slip). |
| `care_measures` | read | `person`*, `kind`, `limit` | Readings, newest first. Optional `kind` filter. |
| `care_forget_measure` | write | `measure_id`* |  |
| `care_trend` | read | `person`*, `kind`*, `drug`, `window_days`, `now` | The readings of one kind with the dates that `drug`'s entry changed marked on the same timeline. For each change: how many readings and |
| `care_appoint` | write | `person`*, `title`*, `at`*, `place`, `who`, `bring` |  |
| `care_appointments` | read | `person`*, `now` | Upcoming first (soonest first), then past ones, newest first. A past planned appointment reads as done: nothing is rewritten. |
| `care_appointment_edit` | write | `appointment_id`*, `title`, `at`, `place`, `who`, `bring` | Change an appointment's details. Only what is sent changes; who edited it and when is kept. |
| `care_profile_edit` | write | `item_id`*, `text`* | Reword a condition or an allergy. An allergy is matched to a medicine name again, so the cross-check follows the new wording. |
| `care_appointment_cancel` | write | `appointment_id`* |  |
| `care_since_visit` | read | `person`*, `appointment_id`, `now` | What to bring to the doctor: every change to the record since the previous appointment (or the last 30 days), the flags now, what no |
| `care_condition_add` | write | `person`*, `name`* |  |
| `care_allergy_add` | write | `person`*, `text`* |  |
| `care_profile` | read | `person`* |  |
| `care_profile_remove` | write | `item_id`* |  |
| `care_allergy_check` | read | `person`* | Recorded allergies against the medicines on record: an exact generic name, or a medicine in a common group (short hand-written list). |
| `care_summary_counts` | read | `person`* | Plain counts over the record for a talk with a pharmacist: how complicated the regimen reads, a short anticholinergic list total (a subset), and |
| `care_reading_stats` | read | `person`* | How often what was read from a photo, voice note or document was saved without a change by the carer who checked it. No text is kept, only |
| `care_watch` | write | `person`*, `drug`*, `on` |  |
| `care_watched` | read | `person`* |  |
| `care_witness` | write | `person`*, `drug`*, `slot`* | A carer other than the one who gave the dose confirms they saw it given. Idempotent for the same witness; refused for the giver. |
| `care_handover` | write | `person`*, `text`* |  |
| `care_handovers` | read | `person`*, `limit` |  |
| `care_sole_knowers` | read | `person`* | For each medicine on record, who knows about its current entry (the carer who recorded it plus everyone who acknowledged it). An entry known |
| `care_hubs` | read | `person`* | Graph-algorithm views: which medicines sit in most hazards within this regimen, and the PageRank hubs of the reference graph |
| `care_graph` | read | `person`*, `include_history`, `now` | The circle as a graph: nodes and edges, each with plain-language metadata (read scope). |
| `care_timeline` | read | `person`*, `limit`, `now` | Everything that happened for this person, newest first, as plain sentences. |
| `care_forget` | write | `dose_id`*, `reason` | Remove one entry for good and return a receipt. |
| `care_forget_person` | write | `person`*, `confirm` | Remove everything about the person cared for (entries, dose slots, reminders). Needs the person's name typed as `confirm`. |
| `care_receipts` | read | none | Receipts of everything that was removed for good (hash, who, when), newest first. |
| `care_export_fhir` | read | `person`* | The regimen as a FHIR R4 Bundle of MedicationStatement resources (free text only). |
| `care_followup_suggest` | read | `person`*, `now` | Suggested follow-ups from the record as it is now, minus any already on the list. Read-only: nothing is written until a person approves. |
| `care_followup_add` | write | `person`*, `items`* | Write the follow-ups a person approved (each one: key, text, kind, basis = entry ids). A key already on the list is not added twice. |
| `care_followups` | read | `person`* | The list, open first. `stale` means an entry it was written from has since been replaced or stopped: look again before doing it. |
| `care_followup_done` | write | `followup_id`*, `dismiss` | Mark a follow-up done (or dismissed). Who and when are kept. |
| `care_chat_ask` | write | `person`*, `question`*, `now`, `daily_limit`, `lang` | Ask the helper assistant about this circle. Both sides of the exchange are stored for the asking carer, so the chat is there on any device. |
| `care_chat_history` | read | `limit` | This carer's conversation with the helper assistant, oldest first. |
| `care_chat_clear` | write | none | Delete this carer's conversation with the helper assistant. |
| `record_decision` | write | `summary`*, `used`*, `answer` |  |
| `explain` | read | `decision_id`* | Why did the agent decide this? Everything it used, with the episodes those facts came from. |
| `stats` | read | none |  |
| `graph_view` | read | `limit` | Snapshot of the tenant graph for visualization: newest nodes first, with the edges among them. |
