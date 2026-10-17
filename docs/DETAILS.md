# Care Circle: the technical write-up

The sections that used to sit in the README, moved here so the README can be read in a few minutes. Back to the [README](../README.md).

## Where FalkorDB fits

The three graphs, the data model, every Cypher query and algorithm, and the test that checks each one follow: [Why the graph is the product](#why-the-graph-is-the-product), [Three graphs, on purpose](#three-graphs-on-purpose), [Graph data model](#graph-data-model), [Queries and algorithms](#queries-and-algorithms). To look at the graphs yourself in FalkorDB Browser: [`docs/EXPLORE.md`](EXPLORE.md).

## Why the graph is the product
The reference knowledge (about 218,000 interaction pairs, enzyme links), every circle's history, the carer-acknowledgement state, the dose-slot guard and the access grants all live in FalkorDB, and the interaction checks are graph traversals. Not everything needs a graph: the table below says which features lean on one and what a plain table could do instead.

| Feature | What the graph does | Without it |
|---|---|---|
| Interaction check | `(a:Drug)-[:INTERACTS {level}]-(b:Drug)` over the regimen, plus a 2-hop enzyme path `(x)-[:INHIBITS]->(:Enzyme)<-[:SUBSTRATE_OF]-(y)` | no shared knowledge to check against |
| Who has not seen a change | `(:Carer)-[:ACKED]->(:Dose)` absence per carer; age-weighted divergence | the graph query matches an independent oracle in 40/40 generated circles. A weak baseline (only the latest change) is exact in 4/40, but a fair one, two SQL tables and one window-function query, is also exact in 40/40 (`bench/care_bench.py`). So this is correctness, and a table could do it; the graph's part here is that it sits with the rest of the record |
| History, "what did we know then?" | `Dose -[:SUPERSEDES]-> Dose` with `valid_from/valid_to`; as-of queries | overwrites lose the past |
| No double dose | one `MERGE (:Give {key})` claim per slot, single atomic query | two carers both think they gave it (one winner in each of 100 test rounds of 10 concurrent claims on one engine; a database-level atomic claim, not a proof) |
| Verified intake | each entry keeps `source_type` and the exact `quote` from the OCR/transcript | an unexplained entry |
| Hubs | `algo.pageRank` over the interaction graph; degree inside the regimen | no way to rank which medicine matters most |
| Privacy | one graph per circle (`mem__<circle>`), grants on every query | rows in a shared table |

## Three graphs, on purpose
| Graph | Holds | Why separate |
|---|---|---|
| `cc_ref` | public knowledge only: DDInter, the FDA enzyme table, cached public lookups | shared by everyone; only the system writes; no personal data |
| `mem__<circle>` | everything about one person: doses, acknowledgements, readings, appointments, conditions, allergies, notes | one graph so one query can cross types ("readings in the two weeks after the warfarin change") and so erasing a person is one drop with one receipt; each graph carries a schema version and is migrated forward when opened (`graphmem/schema.py`) |
| `ctl` | accounts, sessions, invitations, keys, push subscriptions | never holds health data |

## Graph data model
```
cc_ref   (shared, read-only reference graph; built from public data)
  (Drug {name}) -[:INTERACTS {level, source:'DDInter 2.0'}]-> (Drug)       about 218,000 pairs (level may be 'Unknown': shown as unrated)
  (Drug) -[:HAZARD {w}]-> (Drug)                                           moderate/major only, symmetric, for algorithms
  (Drug) -[:INHIBITS|INDUCES {strength, source:'FDA CYP index table'}]-> (Enzyme)
  (Drug) -[:SUBSTRATE_OF {source}]-> (Enzyme)                              FDA index substrates + a small "curated (unverified)" list

mem__<circle>   (one graph per circle)
  (Person {id, role: patient|carer})
  (Dose {id, drug, dose_text, freq_text, valid_from, valid_to, cur, action: set|stop, status: confirmed|pending,
         source_type: typed|photo|voice|document, quote, verified, by, at})
  (Dose)-[:FOR]->(Person)   (Dose)-[:OF]->(Drug)   (Dose)-[:SUPERSEDES]->(Dose)   (Person:carer)-[:ACKED {at}]->(Dose)
  (Give {key: person|drug|slot, by, at})          unique per dose slot
  (Nudge {key})                                   reminder produced once
ctl     (agents, grants, hashed API keys, Telegram chat links, and accounts)
  (:Account {agent, email, name, hash, salt, provider, sub, demo})  (:Session {hash, exp})-[:OF]->(:Account)    only a SHA-256 of a session token is stored
  (:Account)-[:MEMBER {role: owner|carer}]->(:Tenant {id, name, person, owner})        a circle;  (:Agent)-[:GRANTED {scopes}]->(:Tenant) is the engine's access check
  (:Invite {hash, circle, exp})   (:Throttle {key, n, exp})
mem__<circle> also has  (:ChatMsg {by, role, text, at})  the helper conversation, per carer
  (:Source {id, kind, text, sha256})<-[:READ_FROM]-(Dose)    the text the server read an entry from (never the picture)    (:Receipt {id, kind, hash})  what was erased, as a keyed HMAC
  (:Consent {status, who, note, at})-[:FOR]->(Person)    (:Review {name, note, share, at})-[:FOR]->(Person)    (:Setting {key, value})  time zone, receipt key
  (:Measurement {kind, value, unit, at, by})-[:FOR]->(Person)    (:Appointment {title, at, place, who, bring, status})-[:FOR]->(Person)
  (:Condition {name})-[:FOR]->(Person)   (:Allergy {text, drug})-[:FOR]->(Person)   (:Schema {v})  the graph's version
cc_ref also has  (:Cached {url, at, body})  public lookups, by medicine name only
```

**`SUPERSEDES` is derived, not authoritative.** The edge that links a medicine's entries in order is not the record of the order: the entries' own `valid_from` times are. After every change that could alter the order (a new entry, an entry marked as a mistake, an erase, an undo) the edges for that medicine and product are deleted and rebuilt from those times, so two entries recorded in the wrong order, or a late entry with an earlier date, still end up in the right chain, and a bug in building the edge can be repaired by rebuilding it. Queries that need "what stood then" use the times (`valid_from`, `valid_to`), and the edges are for walking the history in the graph view.

## Queries and algorithms
| Behaviour | Cypher / algorithm | Where |
|---|---|---|
| Direct interactions in a regimen | `MATCH (x:Drug)-[m:INTERACTS]-(y:Drug) WHERE x.name IN $d AND y.name IN $d` | `carecircle/checks.py` |
| Enzyme path | `(x)-[:INHIBITS\|INDUCES]->(e:Enzyme)<-[:SUBSTRATE_OF]-(y)` | `carecircle/checks.py` |
| Hub medicines | `CALL algo.pageRank('Drug','HAZARD')` | `carecircle/algos.py hub_drugs` |
| Shortest path between two records | breadth-first, one `MATCH (a)-[r]-(b) WHERE id(a) IN $frontier` per hop (FalkorDB 4.22 has no undirected `shortestPath`), deterministic ties | `graphmem/graph_algos.py graph_path` |
| What the record hangs on | `CALL algo.pageRank($label, null)` or `CALL algo.HarmonicCentrality({nodeLabels: [$label]})` on the tenant's own graph; betweenness is computed by the server (Brandes) over the links read from FalkorDB | `graph_algos.py graph_influence` |
| What belongs together | `CALL algo.WCC(...)` or `CALL algo.labelPropagation(...)`, grouped and counted | `graph_algos.py graph_communities` |
| Everything near one record | level-by-level `MATCH (a)-[r]-(b) WHERE id(a) IN $frontier`, nearest first, capped | `graph_algos.py graph_neighbourhood` |
| Hazard clusters | `CALL algo.WCC({nodeLabels:['Drug'], relationshipTypes:['HAZARD']})` | `algos.py clusters` |
| Most hazard-connected in this regimen | degree and summed weight inside the induced `HAZARD` subgraph | `algos.py regimen_hubs` |
| Change history / as-of | `valid_from <= $t AND (valid_to IS NULL OR valid_to > $t)` over `SUPERSEDES` chains | `graphmem/care.py care_regimen` |
| Supersede on confirm (derived) | every confirmed entry of one medicine and product is ordered by `valid_from`, the edges are deleted and rebuilt, and `cur`/`valid_to` are set from that order | `care.py _care_rechain` |
| Atomic dose-slot claim | `MERGE (g:Give {key:$k}) ON CREATE SET ... g.won=true` then `SET g.won=false` | `care.py care_give` |
| Reminder once | `MERGE (n:Nudge {key:$k}) ON CREATE SET n.fresh=true` | `care.py care_nudges` |
| Isolation and revocation | `(Agent)-[:GRANTED]->(Tenant)` checked on every query | `graphmem/policy.py` |

Each flag and each hub list shown in the app carries the query or path that produced it.

**Algorithms as agent tools.** The four `graph_*` rows above (plus `graph_schema`, which lists what a graph holds) are ordinary read-only operations, so an agent calls them over HTTP or MCP
(`graph_path`, `graph_influence`, `graph_communities`, `graph_neighbourhood`) instead of writing traversals. They run on the caller's own tenant graph through `GRAPH.RO_QUERY`, need read scope
only, take labels as parameters checked against the labels that exist, clamp every size and hop count, and return the Cypher they ran. The Graph tab's "Ask the graph" cards use the same operations.
Limits: they run on one tenant graph at a time, and on a graph with few links PageRank and harmonic centrality say little (a medicine record has few). Betweenness is computed by the server, not by FalkorDB: on FalkorDB 4.22 (what production runs) `algo.betweenness` returned 0, 1 or 2 for the middle of the same three-node chain on different runs, so the server reads the links and runs exact Brandes itself (checked against the definition on 60 random graphs; refused above about four million record-times-link steps, around a second of work). PageRank, harmonic centrality, WCC and label propagation gave identical results over 25 freshly built graphs. When most records of a graph are not linked to anything, the answer carries a note saying its rankings are shallow. Timing on a 2,200-node graph was 5 to 30 ms per call (FalkorDB's own algorithms; exact betweenness about 0.8 s at 2,000 records and 3,000 links) (one run, one machine). ### FalkorDB features used, where, and what checks them

| Feature | Where | Checked by |
|---|---|---|
| One graph per tenant (multigraph): `mem__<circle>` | `graphmem/db.py graph_name`, `graphmem/policy.py` | `tests/test_track02.py` (separate memory per tenant), `tests/test_adversarial.py` |
| Indexes, unique constraints | `graphmem/db.py`, `graphmem/schema.py` (versioned migrations) | `tests/test_requirements.py` (database enforces unique keys), `tests/test_schema.py` |
| Variable-length paths | `graphmem/memory.py` (`SUPERSEDES*1..10`, `INFERRED_FROM*1..8`: is a plan's input out of date) | `tests/test_requirements.py`, `tests/test_track02.py` (a plan whose input changed is reported stale) |
| `MERGE`, `FOREACH`, `UNWIND` | `graphmem/care.py` (atomic dose claim, supersede on confirm), `graphmem/memory.py` (ordered, gap-free events) | `tests/test_track02.py` (claim race, sequence numbers), `tests/test_rebuild.py` |
| `algo.pageRank`, `algo.WCC` on the public reference graph | `carecircle/algos.py` (op `care_hubs`) | `tests/test_care_hubs.py` |
| `algo.pageRank`, `algo.HarmonicCentrality`, `algo.WCC`, `algo.labelPropagation` on a tenant's own graph; exact betweenness computed by the server | `graphmem/graph_algos.py` (ops `graph_influence`, `graph_communities`) | `tests/test_graph_algos.py` |
| Read-only queries (`GRAPH.RO_QUERY`), ACL read-only database user | `graphmem/db.py ro_graph` | `tests/test_requirements.py` (read scope runs as a read-only user), `tests/test_graph_algos.py` |
| `GRAPH.COPY` (memory forks) | `graphmem/branch.py` | `tests/test_branch.py` |
| Full-text index; vector index (optional) | `graphmem/memory.py` (`search_text`, `recall`), `graphmem/embed.py` | `tests/test_track02.py`, `tests/test_semantic.py` |
| Query timeout and memory caps (`GRAPH.CONFIG`) | `graphmem/db.py` (`QUERY_LIMITS`) | `tests/test_limits.py` |
| Append-only persistence, snapshots | `deploy/docker-compose.prod.yml`, `deploy/backup.sh` | `scripts/check_persistence.py`, `scripts/restore_drill.py` |
| FalkorDB Browser | `docs/EXPLORE.md`, `scripts/seed_explore.py` | `tests/test_explore_queries.py` (runs every query in the guide) |

**Connected knowledge.** A circle is private and small; the public interaction data (DDInter, 1,833 medicines, 224,449 pairs) is large and shared. They are two graphs joined by medicine name at query time (`carecircle/checks.py`), so a family's record is checked against public knowledge without either being copied into the other, and a flag always names the edge and source it came from.

## Connect your agent stack

The memory engine is not tied to the web app: any agent can use the same graph through the door it already speaks. Each of these is covered by a test that does exactly what is shown (`tests/test_mcp_http.py`, `tests/test_langchain_tools.py`, `tests/test_llamaindex_tools.py`, `tests/test_api.py`, `tests/test_track02.py`).

| You use | How it connects | Notes |
|---|---|---|
| **An MCP client** (an editor, a desktop assistant, an agent framework with MCP support) | `POST https://<host>/mcp`, streamable HTTP, header `Authorization: Bearer <key>` | The same tools as the stdio server: `call(tenant, op, args_json)` for any of the ~90 operations, `remember`, `recall`, forks, shared spaces, and the graph algorithms as typed tools of their own (`graph_schema`, `graph_path`, `graph_influence`, `graph_communities`, `graph_neighbourhood`), so a model sees each with its arguments. Stateless: no MCP session is kept on the server. Same grants, scopes and rate limits as the REST API; a wrong key is a 401. Off with `CC_MCP_HTTP=0` |
| **MCP over stdio** (a local process) | `GRAPHMEM_API_KEY=gm_... python -m graphmem.mcp_server` | For a client that starts its server itself |
| **LangChain** (agents, LangGraph tool nodes, `bind_tools`) | `graphmem_tools(url, key, tenant)` in `integrations/langchain_tools.py` returns one tool per operation, built from `GET /v1/ops` | `pip install -r requirements-integrations.txt` (`langchain-core`; the server needs nothing extra). Tested against a real server: sync and async calls, a tool-call message in and a `ToolMessage` out, refusals returned to the model as text. Pass `include=["graph_path", "recall", ...]` to expose only some |
| **LlamaIndex** (agents, workflows, tool calling) | `graphmem_tools(url, key, tenant)` in `integrations/llamaindex_tools.py` returns one `FunctionTool` per operation, from the same catalogue | `llama-index-core` (in `requirements-integrations.txt`). Tested at the tool level against a real server: sync and async calls, refusals returned as text, the OpenAI tool schema a model sees. Also run with an agent driven by a real model; see below |
| **FalkorDB's own MCP server** (`@falkordb/mcpserver`) | run it against the same database as a read-only database user; recipe and findings in [`docs/EXPLORE.md`](EXPLORE.md) section 6 | Run by hand against the pinned database: schema, read queries and PageRank worked; writes and `delete_graph` were refused for a read-only user. With the default user its "read-only" setting did **not** stop `delete_graph`. It uses database credentials, so it bypasses our per-key grants: for your own machine only |
| **LangGraph** (agent state across sessions) | FalkorDB's own `FalkorDBSaver` (`pip install "langchain-falkordb[langgraph]"`) holds the agent's step-by-step state; our tools hold its long-term memory | Tested: an agent graph checkpointed in FalkorDB is found by a brand-new saver and graph (the next session), carries on in the same thread, leaves another thread untouched, and its checkpoint graph sits beside the `mem__*` graphs without mixing with them (`tests/test_langgraph_checkpoint.py`, no model needed). The saver is FalkorDB's code and connects to the database directly with the database's credentials, so it does not go through our per-key grants: use it from your own server-side agent, and give it its own graph name (`database="..."`) |
| **Anything else that can send HTTP** (LlamaIndex, a script) | `POST /v1/tenants/{tenant}/{op}` with a JSON body; `GET /v1/ops` lists every operation with its arguments | `docs/API.md` is generated from the code. Wrap an operation as a tool in two lines in any framework |
| **A key** | a signed-in person's session token works as the bearer for their own circles; an agent key (`gm_...`) comes from the admin plane | A key sees only the tenants it was granted, with the scopes it was granted |

```python
# a real MCP client, as tested: list the tools, then ask the graph how two records connect
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

http = create_mcp_http_client(headers={"Authorization": "Bearer " + KEY})
async with streamable_http_client("https://3-228-70-117.sslip.io/mcp", http_client=http) as streams:
    async with ClientSession(streams[0], streams[1]) as session:
        await session.initialize()
        print(await session.call_tool("whoami", {}))            # which circles this key may read
        print(await session.call_tool("call", {"tenant": CIRCLE, "op": "graph_path",
                                               "args_json": '{"source": "asha", "target": "atorvastatin"}'}))
```

**Run with a real model.** `scripts/agent_demo.py` (by hand, not in CI: it calls a paid model) drives a LlamaIndex `FunctionAgent` and a LangGraph agent with Amazon Bedrock's Nova Pro against a synthetic demo circle, using our tools. Both read the schema first, called `graph_path` with the real labels (`Person`, `Drug`), called `graph_influence` for betweenness, and gave answers that match the tool results (asha reaches atorvastatin through one dose; the dose with the highest betweenness is metformin's). The first run, before the tool descriptions told the model what a `label` was, showed the failure worth knowing: the model invented a label (`record`), the server refused it with a message listing the real labels, and the model stopped instead of retrying. The catalogue now carries each operation's full description, which fixed it. A model can still choose badly; the server's refusals are the safety net, not the model's judgement.

Also relevant to the FalkorDB ecosystem, stated plainly: Graphiti was tried first and is **not** the runtime (three defects on exactly the multi-tenant path, measured in `docs/DECISION.md`); we borrowed its ideas (episode to fact provenance, bi-temporal validity) and wrote them as Cypher. QueryWeaver (text to SQL), GraphRAG-SDK, Cognee and Mem0 were **not** run against this project (they need an LLM key for extraction, or do not fit), so nothing is claimed about them. The graphs are ordinary FalkorDB graphs (`mem__<circle>`), so a tool that reads FalkorDB can open them (see "Explore the graph").

## Accounts, circles and the helper
- **Sign in with email.** On the deployed site Amazon Cognito proves the email (a code by email on sign-up and for a forgotten password), the page signs in straight to Cognito as
  [The Vayu Project](https://github.com/hrsh-kr/the-vayu-project) does, and the server checks the ID token's signature, issuer, audience, expiry and verified email (`carecircle/cognito.py`)
  before it creates the account in FalkorDB. Without Cognito configured (local development, CI) the app has its own email-and-password accounts (scrypt hashes, sign-in throttling, 30-day sessions
  stored only as a SHA-256). Set `CC_COGNITO_POOL_ID` and `CC_COGNITO_CLIENT_ID` to switch.
  **Where the session lives.** By default the signed-in page keeps a 30-day session token in the browser's storage, which a script injected into the page could read. Set `CC_COOKIE_SESSIONS=1` and sign-in instead sets an `httpOnly`, `SameSite=Lax` cookie the page cannot read, and every change then also needs a CSRF header that a page on another site cannot send (`tests/test_cookie_sessions.py`; the browser end-to-end scripts pass in this mode). It is off by default on the live site only because it was added last; bearer keys for agents and the MCP endpoint are unchanged either way.
- **Demo accounts.** Two ordinary accounts, Ravi and Meena, share a demo circle for Asha; their password is shown on the sign-in page so anyone can try how a change reaches the second carer.
  "Reset the demo circle" restores it. There is also a throw-away anonymous demo with no account.
- **Your data is real and on the server.** A new account and a new circle start **empty**: nothing is pre-filled or invented. Profile, circles, roles, invitations, medicines, acknowledgements,
  doses, reminders, the helper conversation and Telegram links are all read from the graph on every load; the browser keeps only which circle is open and, unless cookie sessions are on (they are on in the live deployment, where the session is an `httpOnly` cookie the page cannot read), a sign-in token
  (`web/src/lib/session.ts`, with a test that nothing else is stored). Demo-only tools (the time warp, seeded people) appear only in demo circles.
- **Circles and carers.** Create a circle for one person, invite carers with a one-time code (72 hours, one use), rename it, remove or leave. A carer counts toward "who has not seen this" from the
  moment they join. The owner alone can invite, remove carers and erase everything about the person; if the owner leaves, the longest-standing carer becomes owner; the last member leaving deletes the circle.
  Deleting an account removes it and every circle it alone was in.
- **Profile and account page.** Name, circles and members, invitations, the Telegram link (a six-character one-time code: `/link CODE`, `/circles` to switch), password change, sign out, delete account.
- **The helper** (the sparkles button). It answers from the circle's own record: who has not seen a change, what is on record, what is flagged and why, what changed, who gave a dose, and "tell me about <medicine>". "Add warfarin 5 mg once daily"
  becomes a proposal you confirm. Questions that ask for advice (*should she stop...*, *is it safe...*, *how much...*) get a fixed refusal pointing to a prescriber or pharmacist; when the question names a medicine on the record and is about side effects, alcohol or food, the refusal also points to that medicine's published label (the book icon on Today), which is quoted with its source and not offered as advice. An emergency gets the emergency line.
  Rules answer first; only a question no rule covers goes to the optional Bedrock model (`CC_MODEL`, Amazon Nova Pro by default), with names masked, and its answer is used only if it has no advice, no reassurance words, no imperative, no link and no number that is not in the facts
  (`carecircle/assistant.py`, 20 tests including a prompt-injection attempt). The conversation is stored on the server per carer (60 questions a day), can be cleared, and can be asked by voice and read aloud.
- **More:** change a recorded dose or record a medicine as stopped (a new entry, the old one stays in the history), a printable one-page summary for a pharmacist, FHIR export, forget with a receipt.

## More than medicines
Around the medicine record, a circle also keeps what a family needs at the doctor's door. Everything below is stored in the circle's graph, is typed or confirmed by a carer, and never advises.
- **Readings over time** (blood pressure, sugar, INR, weight, pulse, temperature, oxygen, TSH): kept as typed, drawn as a line with the dates a medicine's entry changed marked on it, with the plain mean before and after each change. Only typing slips are refused (a pressure of 1200); a value is never called good or bad.
- **Appointments** with who goes and what to bring; a past one reads as done and stays in the history. **"What to bring"** assembles, from the record alone, what changed since the previous visit, the flags and their sources, anything not yet seen by every carer, readings in that time and any allergy hit.
- **Conditions and allergies.** An allergy is cross-checked against the medicines on record: an exact generic name or a medicine in a class. Class members come from the WHO ATC table as served by NLM RxClass (`data/ref/classes_atc.json`, 26 classes, refreshed with `scripts/fetch_atc_classes.py`; the class words are mapped to ATC codes by hand, the members are not), merged with a short hand-written list in `carecircle/classes.py`. Words are matched whole, with their other spellings; a class missing from the table, or an ingredient missing from its class, is not caught. Cross-reactivity between classes is not claimed. A hit says "ask the prescriber"; no hit is never shown as safe.
- **Recalls and label text.** Public sources, queried by medicine name only, cached in the reference graph: RxNorm (name to ingredient, used when the local match is weak and kept only if the reference graph has that medicine), openFDA drug labels (the official boxed warning and "used for" text, quoted with its source and date) and openFDA recall reports. Live calls are not covered by CI.
- **Only one carer knows.** A graph query over the acknowledgement edges lists current entries known to a single carer (a single point of failure) and the carer holding most of them.
- **Reminders** (unseen changes, doses due or not marked, a pack nearly out) reach people through the Telegram bot and, where the server has VAPID keys, as browser notifications (Web Push, no chat app needed). The delivery loop (`carecircle/reminders.py`) starts with either channel and does not need a Telegram token; one claim per reminder, so it is never produced twice however many channels it goes to; if every channel fails the claim is handed back and the reminder is tried again (up to five times); a circle with nothing that could be due is left alone until a slot window opens or something is written; and a lease in the control graph lets only one process run the loop.
- **Hindi** across the screens, the helper (Devanagari and Hinglish), Hindi voice input and read-aloud.

## What is in the app
The web app is React + TypeScript + Vite, in the visual language of [The Vayu Project](https://github.com/hrsh-kr/the-vayu-project) (Hanken Grotesk, a soft wash in the colour of the most serious flag, a status
card with a big number and a face, white hairline cards, dashed add tiles, a floating pill tab bar and round buttons; the AQI level colours become flag severity), phone to desktop.
- **Today:** the day's dose checklist first (times a carer confirmed from the written frequency, who marked each given, what is not marked yet, a short course ending on its last day, and a pack count that says about how many days of doses are left), then one verdict tile (never "safe"), the regimen, and every flag with its source and the Cypher, enzyme or transporter path behind it. A laboratory (in vitro) finding is the weakest, labelled kind of flag.
- **Add:** a photo, voice note (recorded in the browser), PDF, Word file or typed text becomes proposals that show the exact quoted line, a verified badge and the top three drug matches, with a box to search the whole medicine list by part of a name, or to record a medicine the data does not know as "not checked". A combination brand (Telma-AM) becomes one proposal per ingredient. Nothing is saved until a person confirms.
- **Circle:** who has not seen which change (graph query), reminders with a time-warp control, and below that, in one fold, appointments, other doses, the last seven days in counts and a note of whether the person knows about the record (with a plain view written for them; a note, not legal consent).
- **Graph:** the circle as an animated force-directed graph (people, entries, medicines, enzymes). Nodes pop in, edges draw themselves, flagged edges carry flowing dashes, major interactions pulse. **Click any node or line** and a panel explains it in plain words: what it is, who recorded it and when, the source and quoted line, who acknowledged it, interaction counts and PageRank hub rank for medicines, and the graph pattern it comes from. Layers can be toggled, nodes dragged, the view zoomed; it is keyboard-reachable.
- **History:** a look-back slider (regimen and flags as they were), a timeline written as sentences, **FHIR R4 export** (free-text `MedicationStatement`s, or with RxNorm codes only where the name matches an ingredient exactly; none are invented), a **history fingerprint** (a hash chain over the entries: keep the line, check later that the earlier entries are unchanged), a link on each entry to the text it was read from, and **forget with a receipt**: the owner removes one entry or everything about the person for good, leaving only a keyed HMAC (the key stays on the server), who and when. Any carer can instead mark an entry "entered by mistake", which keeps it in the history.
- **Pharmacist link** (Account, owners only): a read-only page with the medicines and cross-checks, for 1 hour to 7 days, at most three open at a time, closed by the owner at any moment; it shows no carers' names, chat or notes, and the pharmacist can leave a name (not verified) and a note that comes back labelled as such.
- **Follow-ups**: the record suggests things to ask or tell (a flagged pair, a recent change, a carer who has not seen a medicine, an allergy hit); a carer ticks which to keep; each is marked stale if the entry it was written from later changes (`BASIS` edges to the `Dose`).
- **Account basics**: change password (also for Cognito accounts), show/hide password, sign out of all devices, download all my data as JSON, delete a circle, quiet hours for reminders (held, not dropped), text size, search in History, edit appointments and conditions, a Help section, and an installable web app.
- **Light and dark theme**, a toggle in the header; it follows the device until a person chooses, then remembers the choice. English and Hindi (toggle beside it).
- **Telegram** does the same without an app: photo, voice, text, `/regimen`, `/check`, `/history`, `/ack`, `/gave`; proposals wait in the database, so a redeploy does not expire a Confirm button.

## The demo story (90 seconds)
1. **Start a demo circle.** Asha takes metformin, amlodipine, atorvastatin; two carers, Ravi and Meena, have acknowledged them.
2. **Add > "Sample label".** A synthetic pharmacy label is read by OCR. You see the proposed entry with the **exact line it came from** and a
   *quote verified* badge. Nothing is saved yet. Confirm it (as Ravi).
3. **Today** now flags clarithromycin + atorvastatin as *major* (DDInter), with the enzyme path `clarithromycin -INHIBITS(strong)-> CYP3A <-SUBSTRATE_OF- atorvastatin`.
   Pairs the source lists without a severity are shown as *unrated*, not safe.
4. **Circle.** Meena has not acknowledged the change. Slide the time warp to 13 hours: a reminder is produced for Meena, and an escalation for Ravi. Each is produced exactly once.
5. **Doses** (in the Circle tab). Record a dose as Ravi, then as Meena: the second is refused and names who already gave it.
6. **Graph.** Watch it assemble, click the clarithromycin node, then the red line: both explain themselves in words.
7. **History.** Slide back to see the regimen and flags as they were; export FHIR; remove an entry and see the receipt.

## Measured (one laptop; B-series and load test repeated 7 times each, see `docs/BENCHMARKS.md`)
- **Enzyme-path rule vs DDInter:** of 38 pairs flagged through FDA substrates, 31 are also in DDInter, all moderate/major; the rule recovers 61 of 145 moderate/major pairs between the same drug sets (42%): precise but narrow, so it supplements the direct lookup.
- **Carer staleness (graph query vs independent oracle):** exact in 40/40 generated circles; the weak "last change only" baseline is exact in 4/40; a fair two-table SQL baseline is exact in 40/40, so this result does not favour the graph over a table.
- **Double-dose guard:** one winner in 100 of 100 test rounds of 10 concurrent claims (single process, one engine).

- **Interaction check latency:** 16 ms median (range 12-18 over 7 runs) and 20 ms at the 95th percentile (range 16-24), for a 10-medicine regimen (direct pairs, enzyme paths and combined weight in three reads), warm, one process, FalkorDB 4.22.1 (`bench/care_bench.py`, B5). The exact results (B1-B3) were identical in all 7 runs.
- **Intake on real input:** 5 real bottle photos and 1 spoken note (browser microphone to Whisper): drug found in 6/6, with one wrong extra candidate; see `docs/BENCHMARKS.md` (B4).
- **Intake on 150 rendered labels, three levels of damage:** the right medicine first in 150/150 clean, 150/150 moderate and 139/150 harsh (10 harsh images gave no proposal); the strength copied right in 145, 150 and 129 of 150, never with a wrong extra suggestion. One harsh label lost a decimal point (`05mg` for 0.5 mg), which is why every proposal shows its quoted line and waits for a person. Synthetic labels, not photographs (`bench/intake_bench.py`, B4b).

## What runs, and how it is checked
| Feature | Where it is answered | Checked by |
|---|---|---|
| Interaction flags and enzyme paths | `cc_ref` graph (DDInter, FDA table) | unit tests, B1, B5 |
| Who has seen what, and who alone knows | circle graph (`ACKED` edges) | tests, B2 oracle, browser walk-through |
| Dose given once per slot | one conditional `MERGE` | tests, B3 |
| Readings next to medicine changes | circle graph (`Measurement`, `Dose`) | tests, browser walk-through |
| Appointments, conditions, allergy cross-check | circle graph | tests, browser walk-through |
| Recalls, label text, name lookup | RxNorm and openFDA, name only, cached in `cc_ref` | tests with the network faked; **CI stays offline; `CC_LIVE=1 pytest tests/test_live_sources.py` calls the real services (passed 2026-10-16)** |
| Helper (English and Hindi) | rules over the circle's facts; guarded model fallback (English only) | tests incl. advice refusals |
| Schema upgrades | versioned migrations per circle graph | tests |

**Not measured:** OCR/voice accuracy at scale or on home-quality photos and accents, severity accuracy against clinical truth, any patient outcome.

## Operations

**This is a demo deployment, not a production service for real patients.** It is one instance in one availability zone, one process by default (the API and the reminder loop, plus the Telegram poller when a bot token is set), one database, an in-memory rate limiter (each API process counts for itself), and no clinical or regulatory review. What is in place:

- **Deploys.** An update is deployed only after the tests pass. The pipeline first takes a database backup to S3 (`deploy/backup.sh`), then pulls the code, rebuilds `deploy/.env` from Parameter Store (`deploy/render_env.sh`), and starts the stack; if the site does not answer afterwards the previous commit is restored. **That rollback step has not been exercised on the live site**: it restores the previous *code* (the commit saved before the update), it cannot restore data (that is the backups, below), and it was only read through, not run, because a failed deploy has not happened since it was added.
- **Roles.** `CC_ROLE=api` makes a process serve requests only; `CC_ROLE=worker` runs the reminder loop and the Telegram poller; the default `all` does both, as the live site does. Splitting them lets the API be restarted or scaled without a second reminder loop, but the live deployment does not use the split, and a second API process would still have its own rate limiter.
- **Settings and secrets** live in AWS Systems Manager Parameter Store under `/carecircle/prod/` (the secrets as encrypted `SecureString`), not in the repository. The instance's role can read that path and nothing else there. To rotate a value, `put-parameter --overwrite` and deploy. This gives one place to rotate and audit and a rebuildable instance; it does not keep the values off the instance, because the containers need them while they run.
- **The database** requires its own password (`GRAPHMEM_DB_PASSWORD`; the app and the loaders send it), reads run as a database user that can only call `GRAPH.RO_QUERY`, and it keeps **snapshots only** (a save after 60 seconds with a change, 300 seconds with 100), with no append-only log: FalkorDB 4.22.1 aborts when a log holds a write for a graph that no longer exists, and this app deletes and recreates graphs on purpose (`docs/FALKORDB_CRASH.md`). The price is that a hard crash loses up to the last minute of writes.
- **Containers** have memory limits (database 2 GB, API 3 GB, Caddy 256 MB, on a 7.8 GB host) and rotating logs (three files of 10 MB each), so a runaway job or a chatty log cannot take the host down.
- **Copies of the data**, newest first: the database's own snapshot; the backup taken before every deploy; every 6 hours to S3 (kept 14 days); a daily EBS snapshot of the whole disk, 7 kept (AWS Data Lifecycle Manager). Restore steps are in `deploy/RESTORE.md`.
- **Watching.** Route 53 checks `/healthz` from outside AWS every 30 seconds; the CloudWatch alarm `carecircle-site-down` fires after two failed minutes and publishes to the SNS topic `carecircle-alerts` (an email subscription on it is how a person gets told). Alarms also reboot the instance if its operating system stops answering and recover it onto new hardware if the AWS host fails; a scheduled GitHub workflow checks `/healthz` every 15 minutes as well.
- **Rebuilding.** `deploy/infra/carecircle.yaml` is a CloudFormation template for all of the above (security group, role, instance, address, backup bucket, snapshot policy, health check and alarms). Python dependencies are pinned in `constraints.txt`.

Every push to `main` runs the tests, the web build and a headless-Chrome walk-through of the demo, and only then deploys to the instance (GitHub OIDC to AWS Systems Manager, no stored keys).
FalkorDB itself has no query time or memory limit, so the app sets one on first connect (15 s default, 60 s ceiling, 1 GiB per query; tunable with `GRAPHMEM_QUERY_TIMEOUT_MS`, `GRAPHMEM_QUERY_TIMEOUT_MAX_MS`, `GRAPHMEM_QUERY_MEM_BYTES`, `0` = off). A query that hits a cap is stopped, a write inside it is rolled back, and the caller gets a 503 that says to ask for less. `GET /admin/db` (admin key) shows the caps in force, graph counts, memory and the slowest queries with every string value removed.
One graph per circle costs memory. Measured with `bench/circle_cost.py` (150 circles, each with one confirmed medicine): **about 2.0 MB and 40 ms per circle, 12 indexes**; before the generic memory engine's indexes were made lazy it was 3.4 MB, 60 ms and 24 indexes (B8). Plan on the order of 2 GB per thousand circles on this engine and watch `/admin/db`.

FalkorDB is **pinned by digest** (4.22.1) in `docker-compose.yml`, `deploy/docker-compose.prod.yml` and the CI workflow, and `tests/test_pinned_database.py` fails if those differ or if the database a test run talks to is another version. `latest` is a moving tag: it was 4.22.1 on the server and 6.0.2 on a laptop, and three bugs hid in that gap. 4.22.1 is the newest release of the 4.x line (15 Oct 2026); 6.x is a different engine (Rust) for which FalkorDB documents no supported upgrade from 4.x yet, so moving is a deliberate migration, not a version bump. A second workflow (`.github/workflows/compat.yml`) runs the whole test suite on 6.0.2 on every push; it passes on every push, so the code is ready, and the open question is moving the data. To upgrade, change the digest in all three files and `PINNED_VERSION` in that test together, after running the suite on the new image.

## The product and the engine under it
This repository holds two things that share a database, and it helps to keep them apart.
- **The product, Care Circle.** `carecircle/` (reference data, checks, safety rules, intake, accounts, reminders, Telegram, the pharmacist link) and the care operations in `graphmem/care*.py` (the regimen, who has seen what, the dose-slot claim, the schedule), with the React app in `web/`. Every screen and every number in this README comes from this part.
- **The engine, `graphmem`.** A general multi-tenant graph memory for agents on FalkorDB: a graph per tenant, access grants, an HTTP API and an MCP server over one table of operations (`graphmem/ops.py`), plus the generic memory operations in `graphmem/memory.py` (episodes, facts that supersede each other, tasks with atomic claims, plans, forks, shared spaces). It is what Track 02 (agent memory and coordination) asks for, and it is what lets another agent use a circle's memory.
- **What depends on what.** The care code uses the engine's tenants, grants, operation table and query layer (`db.py`, `policy.py`, `ops.py`); it does **not** use the generic memory operations (episodes, facts, tasks, plans). Those are exercised by their own tests and by `docs/TRACK02.md`, and a care circle's graph only gets their indexes if something calls them (see Operations).

## Layout
`carecircle/` product logic (reference graph, checks, risk math, safety, intake, Telegram, algorithms, demo) · `graphmem/` the multi-tenant graph
memory engine (tenants, grants, HTTP API, MCP server, forks, spaces) · `web/` the React app · `deploy/` production compose, S3 backup and restore guide · `tests/` · `bench/` · `scripts/` · `docs/ARCHITECTURE.md`.
Scenario testing (real accounts and a real browser: what happens when people do what people really do, and what it found): [`docs/SCENARIOS.md`](SCENARIOS.md), run with `python scenarios/run.py` and `python scenarios/ui_scenarios.py`.
Track 02 (agent memory and coordination), each point of the brief with where it is built and how it is tested and measured: [`docs/TRACK02.md`](TRACK02.md) (`tests/test_track02.py`, `bench/track02_stress.py`).
API: every operation is callable over HTTP (`POST /v1/tenants/{circle}/{op}`); the full table is in [`docs/API.md`](API.md) and a running server serves Swagger at `/docs`.
MCP: `claude mcp add carecircle -e GRAPHMEM_API_KEY=gm_... -- python -m graphmem.mcp_server` exposes every operation (`call(tenant, "care_check", ...)`).

## Limits in full
- Interaction severity weights (minor .1, moderate .3, major .7; enzyme strong .7, moderate .3; staleness half-life 72 h) are **assumptions**, not clinical values.
- The FDA CYP table is an index list, not exhaustive. Sources may disagree. Flags are for discussion with a prescriber or pharmacist.
- **The enzyme layer is small.** The enzyme-path check rests on the FDA's table of index CYP inhibitors, inducers and substrates: 7 enzymes, 13 inhibitors, 7 inducers and 12 substrates, plus 9 substrates from a short hand-made list that is marked `curated (unverified)` wherever it appears. Together they touch **32 of the 1,833 medicines** in the reference graph. The FDA page also lists *laboratory (in vitro)* inhibitors, inducers and transporter findings (P-gp, OATP, OAT, OCT2, MATE, BCRP); those add 31 more medicines (63 in all) as the weakest kind of flag: labelled "a laboratory finding, not shown in people", given the lowest weight, shown as minor, and never shown instead of a clinical path for the same pair. When the FDA site refuses the scripted download (it did in CI), the loader uses the copy of that page bundled in `carecircle/snapshot/`. A medicine outside those gets no enzyme-path flag; its interactions come only from the DDInter pairs. **No flag is never a statement that nothing interacts.**
- The Telegram bot is tested against a fake Telegram API and, by hand, live (`/link`, `/regimen`, a typed medicine, Confirm, `/check`, a photo of a label, a reminder arriving after a back-dated unseen change, `/ack`); a spoken note, where Whisper heard "Arferin" and the matcher still offered warfarin first, with the heard text shown for a person to confirm. Voice uses a local Whisper `base` model; accuracy varies with accent and noise.
- **Which model, and why Nova is still the default.** The optional structuring model is set by `CC_MODEL` (default Amazon Nova Pro on Bedrock). Claude Haiku 4.5, Sonnet 4.5 and Opus 4.5 can be called from a developer login on this AWS account, but the server's own role is refused ("model use case details have not been submitted for this account"), so the live site cannot use them yet; the newer Claude models are refused for the account altogether. On synthetic labels, **no model beat the rules alone** and Nova was worse than the rules on damaged labels (30 of 40 strengths right against 34); Claude Haiku and Sonnet matched the rules (`docs/BENCHMARKS.md`, B7). Rules work without any model, and a model's output is only ever kept if its quote is found in the text that was read.
- Cognito's default email sender is capped at 50 messages a day, so sign-ups beyond that need Amazon SES. The Telegram link-by-code and the account pages were tested against the fake API and in Chrome, not yet live in Telegram. The helper has not been evaluated with real families: its refusal rules are keyword-based and can miss an unusual phrasing, which is why every answer is also checked for advice before it is sent.
- Reminders arrive by browser notification (Web Push) and Telegram. WhatsApp and SMS are **not built**: they need a paid sender account and a phone number per person, which this project avoids. The interface is English and Hindi; other languages need a translator to review them before they are added.
- **Where the data comes from limits where it can be used.** Interaction severities come from DDInter 2.0 (US/EU-centred drug labelling and literature) and the FDA CYP table; they are not a view of how Indian practice rates the same pairs, and many Indian brands are combinations the reference data has never heard of (the combination list in `carecircle/brands.py` is hand-written and unverified). Recalls come from openFDA, which lists US recalls only, so they are looked up only for a circle in a US time zone.
- **Not for commercial use as it stands.** DDInter is CC BY-NC-SA 4.0. A commercial service would need a licence for an interaction source (or its own curated one), a licensed brand-to-ingredient master for India, clinician review of every rule, and the regulatory and privacy steps for health data (in India, the DPDP Act, including the patient's own consent, which this project records only as a note and not as legal consent).
- Per-process rate limiting; TLS comes from Caddy in the production compose only (the dev compose has none); one shared database credential across circles; a single server in one availability zone with no replica. The database keeps snapshots only, so a hard crash can lose up to the last minute; the recovery copies are a backup taken before every deploy, one every 6 hours in S3 and a daily EBS snapshot (`deploy/RESTORE.md`). FalkorDB 4.22.1 crashes when it replays a write log in which a graph was deleted and then written again, which is why there is no write log (`docs/FALKORDB_CRASH.md`).

## Running it and settings

Without Docker (needs a FalkorDB on :6379, e.g. `docker run -p 6379:6379 falkordb/falkordb`):
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt          # Windows: .venv/Scripts
python scripts/fetch_reference.py                                           # DDInter + FDA tables into data/ref (gitignored)
python -c "from carecircle import reference as r; print(r.load())"          # build the shared cc_ref graph
(cd web && npm ci && npm run build)                                         # the React app (served by the API from web/dist)
python -m graphmem.api                                                      # http://127.0.0.1:8000
python -m pytest -q tests                                                   # the whole suite, against a live FalkorDB
(cd web && npm test)                                                        # UI unit tests; `npm run dev` for hot reload (proxies to :8000)
PORT=8000 python scripts/ui_e2e.py && PORT=8000 python scripts/ui_e2e_accounts.py    # browser walk-throughs: demo, then accounts (need Chrome and `pip install playwright`)
PYTHONPATH=. python bench/care_bench.py                                     # benchmarks below (`--out run.json`, then `python bench/gate.py bench/baselines/care_bench.json run.json` compares two runs)
```
Optional: `CC_COGNITO_POOL_ID` / `CC_COGNITO_CLIENT_ID` (email sign-up through Amazon Cognito; unset = built-in accounts), `CC_ASSISTANT=0` (the helper answers from rules only), `CC_MODEL` / `AWS_REGION` + AWS credentials let Amazon Bedrock (default `us.amazon.nova-pro-v1:0`; a Claude id such as `us.anthropic.claude-haiku-4-5-20251001-v1:0` works where the account allows it) structure what the OCR read;
`CC_LLM=0` or no credentials falls back to rules. `CC_COOKIE_SESSIONS=1` keeps the session in an httpOnly cookie (on in the live deployment), `GRAPHMEM_DB_PASSWORD` makes the database itself require a password (on in the live deployment), `GRAPHMEM_RO_PASSWORD` turns on the read-only database user (required by the production compose file), `CC_REMINDERS=0` switches the reminder loop off, and `CC_EXTERNAL=0` stops every outgoing lookup (RxNorm, openFDA). Set `TELEGRAM_BOT_TOKEN` to also run the Telegram bot in the server process (`/link <key> <circle>`, then send a photo, voice note or text).

**Look inside the graph.** `python scripts/seed_explore.py` loads two small synthetic graphs (a care circle and an agent's memory); then open FalkorDB Browser at <http://localhost:3000>, connect to `localhost:6379`, and run the queries in [`docs/EXPLORE.md`](EXPLORE.md): the regimen and its history, who has not seen a change, why an agent decided something, and PageRank over the interaction graph. A test runs every query in that guide, so they work. The live site does not expose the Browser (one login would show every family's circle); the Graph tab shows each circle's own graph and the Cypher behind it.
