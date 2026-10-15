# Care Circle

**One shared, verified memory of a loved one's medicines, for the family who look after them.**
Graph Hacks 2026 (WeMakeDevs x FalkorDB), Track 02: Agent Memory & Coordination.

When several people care for one person, nobody holds the whole picture. A photo of a new prescription lands in one chat, a dose
changes by phone, a sibling gives a tablet the other already gave. Care Circle keeps one memory in a FalkorDB graph. Each carer reaches
it through a web app or Telegram (their own agent identity), adds a medicine by **photo, voice note, PDF/Word or text**, and the circle then
knows what is on record, **who has seen each change**, which entries **interact** according to public sources, and which dose slots are **already given**.

**It records and cross-checks. It never advises.** It never says what to take, stop or change. Every flag shows its source and the graph
path behind it, and "no flag" is never reported as "safe". All data in the demo is synthetic; no real person's data is used.

**Live demo: https://52-200-189-188.sslip.io** (press "Start a demo circle"; synthetic data only).

![Today](docs/img/flags.png)

## Why the graph is the product
Remove FalkorDB and nothing is left: the reference knowledge (about 218,000 interaction pairs, enzyme links), every circle's history, the
carer-acknowledgement state, the dose-slot guard and the access grants all live in it, and the checks are graph traversals and algorithms.

| Feature | What the graph does | Without it |
|---|---|---|
| Interaction check | `(a:Drug)-[:INTERACTS {level}]-(b:Drug)` over the regimen, plus a 2-hop enzyme path `(x)-[:INHIBITS]->(:Enzyme)<-[:SUBSTRATE_OF]-(y)` | no shared knowledge to check against |
| Who has not seen a change | `(:Carer)-[:ACKED]->(:Dose)` absence per carer; age-weighted divergence | a flat log cannot say who is behind (baseline "last change only" is right in 0/40 circles, the graph query in 40/40) |
| History, "what did we know then?" | `Dose -[:SUPERSEDES]-> Dose` with `valid_from/valid_to`; as-of queries | overwrites lose the past |
| No double dose | one `MERGE (:Give {key})` claim per slot, single atomic query | two carers both think they gave it (exactly one winner in 100/100 races of 10 concurrent claims) |
| Verified intake | each entry keeps `source_type` and the exact `quote` from the OCR/transcript | an unexplained entry |
| Hubs | `algo.pageRank` over the interaction graph; degree inside the regimen | no way to rank which medicine matters most |
| Privacy | one graph per circle (`mem__<circle>`), grants on every query | rows in a shared table |

## Run it
Deployed on one AWS EC2 instance (t3.large, Docker Compose, Caddy for HTTPS, Bedrock through the instance role, only ports 80/443 open): `deploy/docker-compose.prod.yml`.

```bash
# everything: FalkorDB (append-only volume) + app. First start downloads the public reference data and loads it (a few minutes).
GRAPHMEM_ADMIN_KEY=change-me docker compose up -d --build
open http://localhost:8000          # press "Start a demo circle"     (FalkorDB Browser: http://localhost:3000)
```
Without Docker (needs a FalkorDB on :6379, e.g. `docker run -p 6379:6379 falkordb/falkordb`):
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt          # Windows: .venv/Scripts
python scripts/fetch_reference.py                                           # DDInter + FDA tables into data/ref (gitignored)
python -c "from carecircle import reference as r; print(r.load())"          # build the shared cc_ref graph
(cd web && npm ci && npm run build)                                         # the React app (served by the API from web/dist)
python -m graphmem.api                                                      # http://127.0.0.1:8000
python -m pytest -q tests                                                   # 79 tests against live FalkorDB
(cd web && npm test)                                                        # UI unit tests; `npm run dev` for hot reload (proxies to :8000)
PORT=8000 python scripts/ui_e2e.py                                          # browser walk-through (needs Chrome and `pip install playwright`)
PYTHONPATH=. python bench/care_bench.py                                     # benchmarks below
```
Optional: `CC_MODEL` / `AWS_REGION` + AWS credentials let Amazon Bedrock (default `us.amazon.nova-pro-v1:0`) structure what the OCR read;
`CC_LLM=0` or no credentials falls back to rules. Set `TELEGRAM_BOT_TOKEN` to also run the Telegram bot in the server process (`/link <key> <circle>`, then send a photo, voice note or text).

## What is in the app
The web app is React + TypeScript + Vite, built on the design system of [Vayu Labs](https://github.com/hrsh-kr/vayu-labs) (its tokens, shell, tab bar, sheets and
segmented controls are reused), light and dark, phone to desktop.
- **Today:** one verdict tile (never "safe"), the regimen, and every flag with its source and the Cypher or enzyme path behind it.
- **Add:** a photo, voice note (recorded in the browser), PDF, Word file or typed text becomes proposals that show the exact quoted line, a verified badge and the top three drug matches. Nothing is saved until a person confirms.
- **Circle:** who has not seen which change (graph query), reminders with a time-warp control, and a once-per-slot dose log.
- **Graph:** the circle as an animated force-directed graph (people, entries, medicines, enzymes). Nodes pop in, edges draw themselves, flagged edges carry flowing dashes, major interactions pulse. **Click any node or line** and a panel explains it in plain words: what it is, who recorded it and when, the source and quoted line, who acknowledged it, interaction counts and PageRank hub rank for medicines, and the graph pattern it comes from. Layers can be toggled, nodes dragged, the view zoomed; it is keyboard-reachable.
- **History:** a look-back slider (regimen and flags as they were), a timeline written as sentences, **FHIR R4 export** (free-text `MedicationStatement`s; no medicine codes are invented), and **forget with a receipt**: remove one entry or everything about the person for good, leaving only a SHA-256 hash, who and when.
- **Telegram** does the same without an app: photo, voice, text, `/regimen`, `/check`, `/history`, `/ack`, `/gave`; proposals wait in the database, so a redeploy does not expire a Confirm button.

## The demo story (90 seconds)
1. **Start a demo circle.** Asha takes metformin, amlodipine, atorvastatin; two carers, Ravi and Meena, have acknowledged them.
2. **Add > "Use a sample label".** A synthetic pharmacy label is read by OCR. You see the proposed entry with the **exact line it came from** and a
   *quote verified* badge. Nothing is saved yet. Confirm it (as Ravi).
3. **Today** now flags clarithromycin + atorvastatin as *major* (DDInter), with the enzyme path `clarithromycin -INHIBITS(strong)-> CYP3A <-SUBSTRATE_OF- atorvastatin`.
   Pairs the source lists without a severity are shown as *unrated*, not safe.
4. **Circle.** Meena has not acknowledged the change. Slide the time warp to 13 hours: a reminder is produced for Meena, and an escalation for Ravi. Each is produced exactly once.
5. **Doses** (in the Circle tab). Record a dose as Ravi, then as Meena: the second is refused and names who already gave it.
6. **Graph.** Watch it assemble, click the clarithromycin node, then the red line: both explain themselves in words.
7. **History.** Slide back to see the regimen and flags as they were; export FHIR; remove an entry and see the receipt.

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
ctl     (agents, grants, hashed API keys, Telegram chat links)
```

## Queries and algorithms
| Behaviour | Cypher / algorithm | Where |
|---|---|---|
| Direct interactions in a regimen | `MATCH (x:Drug)-[m:INTERACTS]-(y:Drug) WHERE x.name IN $d AND y.name IN $d` | `carecircle/checks.py` |
| Enzyme path | `(x)-[:INHIBITS\|INDUCES]->(e:Enzyme)<-[:SUBSTRATE_OF]-(y)` | `carecircle/checks.py` |
| Hub medicines | `CALL algo.pageRank('Drug','HAZARD')` | `carecircle/algos.py hub_drugs` |
| Hazard clusters | `CALL algo.WCC({nodeLabels:['Drug'], relationshipTypes:['HAZARD']})` | `algos.py clusters` |
| Most hazard-connected in this regimen | degree and summed weight inside the induced `HAZARD` subgraph | `algos.py regimen_hubs` |
| Change history / as-of | `valid_from <= $t AND (valid_to IS NULL OR valid_to > $t)` over `SUPERSEDES` chains | `graphmem/care.py care_regimen` |
| Supersede on confirm | `OPTIONAL MATCH (old:Dose {cur:true, drug:x.drug}) ... FOREACH ... CREATE (x)-[:SUPERSEDES]->(old)` | `care.py _care_activate` |
| Atomic dose-slot claim | `MERGE (g:Give {key:$k}) ON CREATE SET ... g.won=true` then `SET g.won=false` | `care.py care_give` |
| Reminder once | `MERGE (n:Nudge {key:$k}) ON CREATE SET n.fresh=true` | `care.py care_nudges` |
| Isolation and revocation | `(Agent)-[:GRANTED]->(Tenant)` checked on every query | `graphmem/policy.py` |

Each flag and each hub list shown in the app carries the query or path that produced it. FalkorDB features used: multiple graphs (one per circle),
indexes, unique constraints, variable-length paths, `FOREACH`, `UNWIND` bulk loads, `algo.pageRank`, `algo.WCC`, read-only queries (`GRAPH.RO_QUERY`),
`GRAPH.COPY` (memory forks), full-text and vector indexes (optional recall), append-only persistence.

## Safety by design
- **No advice.** A scanner (`carecircle/safety.py`) rejects outgoing text that tells someone to take, stop, skip or change a dose. Messages are
  templates whose facts (drug, hours, carer) are checked before sending.
- **Refuses to judge.** States are `no_data`, `partial`, `flags` or `no_known_conflict`; the last always says "this is not a statement of safety".
- **Quote and verify.** The model only structures text the OCR/ASR already read. Each quote must appear in that text; otherwise the entry stays
  *pending* and never reaches the regimen or the checks until a person confirms it. Every proposal needs a person's confirmation.
- **Unknown stays unknown.** 26% of DDInter pairs have severity "Unknown": shown as *unrated*.

## Measured (single runs on one laptop; `docs/BENCHMARKS.md`)
- **Enzyme-path rule vs DDInter:** of 38 pairs flagged through FDA substrates, 31 are also in DDInter, all moderate/major; the rule recovers 61 of 145 moderate/major pairs between the same drug sets (42%): precise but narrow, so it supplements the direct lookup.
- **Carer staleness (graph query vs independent oracle):** exact in 40/40 generated circles; "last change only" baseline 0/40.
- **Double-dose guard:** one winner in 100/100 rounds of 10 concurrent claims.

- **Intake on real input:** 5 real bottle photos and 1 spoken note (browser microphone to Whisper): drug found in 6/6, with one wrong extra candidate; see `docs/BENCHMARKS.md` (B4).

**Not measured:** OCR/voice accuracy at scale or on home-quality photos and accents, severity accuracy against clinical truth, any patient outcome.

## Operations
Every push to `main` runs the tests, the web build and a headless-Chrome walk-through of the demo, and only then deploys to the instance (GitHub OIDC to AWS Systems Manager, no stored keys).
FalkorDB is snapshotted to a private S3 bucket every 6 hours, CloudWatch alarms reboot or recover the instance, and a scheduled workflow checks `/healthz` (`deploy/RESTORE.md`).

## Limits, stated plainly
- Interaction severity weights (minor .1, moderate .3, major .7; enzyme strong .7, moderate .3; staleness half-life 72 h) are **assumptions**, not clinical values.
- The FDA CYP table is an index list, not exhaustive. Sources may disagree. Flags are for discussion with a prescriber or pharmacist.
- The Telegram bot is tested against a fake Telegram API and, by hand, live (`/link`, `/regimen`, a typed medicine, Confirm, `/check`, a photo of a label, a reminder arriving after a back-dated unseen change, `/ack`); a spoken note, where Whisper heard "Arferin" and the matcher still offered warfarin first, with the heard text shown for a person to confirm. A photo reading shows the strength but not a frequency written two lines below the drug name. Voice uses a local Whisper `base` model; accuracy varies with accent and noise.
- Anthropic models on Bedrock were unavailable on the account used (verification pending), so the default structuring model is Amazon Nova; rules work without any model.
- Per-process rate limiting; no TLS in the compose file (put a proxy in front); one shared database credential across circles.

## Data and licences
Interaction data: **DDInter 2.0**, CC BY-NC-SA 4.0 (**non-commercial** use; attribution required), downloaded by `scripts/fetch_reference.py`, not stored in this repository.
Enzyme data: the FDA "Drug Development and Drug Interactions" substrates/inhibitors/inducers table. A snapshot of the FDA table (US government work) is bundled in `carecircle/snapshot/` as a fallback when the FDA site blocks scripted downloads. Demo circles, labels and people are synthetic.

## AI use disclosure
This project was built with substantial help from Claude (Anthropic) via Claude Code: design discussion, code, tests and docs were written with
AI assistance and reviewed and run by the author. At runtime, an optional Amazon Bedrock model (Amazon Nova) only turns OCR/transcript text into
proposed fields; it never decides interactions or doses.

## Layout
`carecircle/` product logic (reference graph, checks, risk math, safety, intake, Telegram, algorithms, demo) · `graphmem/` the multi-tenant graph
memory engine (tenants, grants, HTTP API, MCP server, forks, spaces) · `web/` the React app · `deploy/` production compose, S3 backup and restore guide · `tests/` · `bench/` · `scripts/` · `docs/ARCHITECTURE.md`.
MCP: `claude mcp add carecircle -e GRAPHMEM_API_KEY=gm_... -- python -m graphmem.mcp_server` exposes every operation (`call(tenant, "care_check", ...)`).
