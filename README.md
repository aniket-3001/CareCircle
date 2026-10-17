<p align="center">
  <img src="docs/img/banner.svg" alt="Care Circle: an animated graph of two carers, a person, their medicines and an enzyme, with a flagged interaction pulsing and a change travelling from one carer to the person" width="100%" />
</p>

# Care Circle

**One shared, verified memory of a loved one's medicines, for the family who look after them.**

*Graph Hacks 2026 (WeMakeDevs x FalkorDB), Track 02: Agent Memory & Coordination.*

It is 9 pm. Ravi has just changed his mother's warfarin dose by phone. His sister Meena is on the night shift and has not seen it. Tomorrow a pharmacist adds an antibiotic that interacts with it, and nobody holds the whole picture.

Care Circle keeps that picture in one FalkorDB graph. Each carer reaches it through a web app or Telegram (their own agent identity), adds a medicine by **photo, voice note, PDF/Word or text**, and the circle then knows what is on record, **who has seen each change**, which entries **interact** according to public sources, and which dose slots are **already given**.

**It records and cross-checks. It never advises.** It never says what to take, stop or change. Every flag shows its source and the graph path behind it, and "no flag" is never reported as "safe". All data in the demo is synthetic; no real person's data is used.

Live: **https://3-228-70-117.sslip.io** (press **Start a demo circle**; synthetic data only) · The same memory for any agent: **`POST /mcp`** on the same address ([Connect your agent stack](#connect-an-agent))

![Care Circle, Today screen: the day's doses, then the verdict with its flag count](docs/img/ui-today.png)

## One story it was built around

A cardiologist writes **Telma-AM** (telmisartan with amlodipine). A second doctor, months later, writes plain **amlodipine** for the ankle swelling. On the shelf they are two different boxes; in the body it is amlodipine twice. Care Circle reads the Telma-AM line as *two* ingredients (a hand-written brand list, marked unverified, with "check the pack"), keeps the plain amlodipine as its own entry, and then shows both under the same ingredient with the words "this may be the same medicine from two sources", plus who recorded each and from which quoted line. It says nothing about what to do: the card ends with "discuss with a prescriber or pharmacist". (Browser scenario U14 walks exactly this; `tests/test_duplicates.py` holds the rule.)

## Why it is different

- **It does the daily job.** A written "twice daily" becomes suggested clock times that a person confirms; **Today** then lists each dose slot, who marked it given, and what is not marked yet, and a second carer who taps the same slot is told who got there first. A short course ends on its last day, and a pack count says about how many days of doses are left.
- **One memory for the whole circle.** Not a chat per person: one graph that says what is on record now, what it replaced, and which carer has not yet seen the change.
- **Every flag shows its work.** The source (DDInter 2.0 or the FDA table), the edge it came from, and the exact line of the photo or voice note that produced the entry. A pair the source lists without a severity is shown *unrated*, never "safe".
- **Code decides, AI only structures.** A model may turn OCR or a transcript into *proposed* fields; each proposal's quote must appear in the text that was read, and nothing reaches the regimen until a person confirms it. It never decides an interaction or a dose.
- **The graph holds the record.** Reference knowledge (224,449 interaction pairs, enzyme links), every circle's history, who has seen what, the once-per-slot dose guard and the access grants all live in FalkorDB, one graph per circle.
- **Agents can use the same memory.** An MCP endpoint, LangChain and LlamaIndex tools and graph algorithms (paths, PageRank, betweenness, communities) run on a circle's graph, with the same keys and read-only checks.

## Try it in two minutes

1. Open the live address and press **Start a demo circle**. Asha takes metformin, amlodipine and atorvastatin; two carers, Ravi and Meena, have both acknowledged them.
2. **Add**, then **Sample label**: a synthetic pharmacy label is read by OCR. You see the proposed entry, the exact line it came from and a *quote verified* badge. Nothing is saved yet. Confirm it.
3. **Today** now flags clarithromycin with atorvastatin as *major*, with the enzyme path behind it. Open the flag to see the source.
4. **Circle**: Meena has not acknowledged the change. Slide the time warp 13 hours: a reminder for Meena, then an escalation to Ravi, each exactly once.
5. **Graph**: watch the circle assemble, click the clarithromycin node and the red line: both explain themselves in words. Open **Inspect the graph** below it for the cards **What the record hangs on** and **What belongs together**: PageRank, betweenness, groups and paths on this circle's own graph (for developers and judges).
6. Point an agent at it: [Connect your agent stack](docs/DETAILS.md#connect-your-agent-stack). The full 90-second script is [The demo story](docs/DETAILS.md#the-demo-story-90-seconds).

## What it looks like

Taken from the live app at laptop width, with the synthetic demo circle (`scripts/take_screenshots.py` makes them again).

**Add a medicine.** A label is read by OCR, the exact line each entry came from is quoted, and nothing is saved until a person confirms it.

![Add screen: the text read from a sample label, the quoted line with a "quote verified" badge, and the proposed entry to confirm](docs/img/ui-add.png)

**Every flag shows its source.** The pair, how severe the source rates it, which source, and the graph pattern behind it. Enzyme paths come from the FDA table and are shown separately.

![Flags with their sources: a major pair, moderate pairs and enzyme paths, each with its source and the pattern in the graph](docs/img/ui-flags.png)

**The circle as a graph, as stored in FalkorDB.** Carers, entries, medicines and the enzyme; the coral line is the major pair, the dashed blue one an enzyme path.

![The circle as a graph: Ravi and Meena, Asha, five medicines, a major interaction in coral and an enzyme path in blue](docs/img/ui-graph.png)

Click anything and it explains itself in plain words, with the line it was read from:

![A selected entry: who recorded it, from what, and the quoted line checked against the source text](docs/img/ui-graph-explain.png)

**Who has seen what.** Every change is shown to every carer; until someone acknowledges it they count as behind, and a medicine only one carer knows about is called out.

![Circle screen: medicines only one carer knows about, and each carer's unseen changes](docs/img/ui-circle.png)

**History.** Nothing is overwritten: slide back to see what the record and its flags said at any earlier moment, or read what happened in order, with the line each entry was read from.

![History screen: the look-back slider with the flags as they were then, and a timeline of changes with the quoted line and a link to the text it was read from](docs/img/ui-history.png)

## Connect an agent

The same memory is open to any agent: `POST /mcp` on the live address (Streamable HTTP, `Authorization: Bearer <key>`), or the stdio server `python -m graphmem.mcp_server`, or the LangChain and LlamaIndex tools in `integrations/`. Keys carry scopes (`read`, `write`, `admin`) that are enforced before every operation. Setup, tool list and examples: [Connect your agent stack](docs/DETAILS.md#connect-your-agent-stack).

On the question this memory exists to answer ("which carer has not seen which change?") on 20 generated circles: Care Circle 20/20, Mem0 7/20, a model given every event 10/20; and in a race of ten callers for one dose slot Care Circle accepts one, Mem0 all ten. Tiny circles, one question, untuned baselines: read the limits in `docs/BENCHMARKS.md` (B6) before quoting it.

## Safety by design
- **No advice.** A scanner (`carecircle/safety.py`) rejects outgoing text that tells someone to take, stop, skip or change a dose. Messages are
  templates whose facts (drug, hours, carer) are checked before sending.
- **Refuses to judge.** States are `no_data`, `partial`, `flags` or `no_known_conflict`; the last always says "this is not a statement of safety".
- **Quote and verify.** The model only structures text the OCR/ASR already read. Each quote must appear in that text; otherwise the entry stays
  *pending* and never reaches the regimen or the checks until a person confirms it. Every proposal needs a person's confirmation.
- **Unknown stays unknown.** 26% of DDInter pairs have severity "Unknown": shown as *unrated*.

## Limits, stated plainly
- Severity weights (minor .1, moderate .3, major .7) and staleness half-life are **assumptions**, not clinical values. Sources can disagree; flags are for discussion with a prescriber or pharmacist, and **no flag is never a statement that nothing interacts.**
- **The enzyme layer is small**: 63 of the 1,833 medicines in the reference graph; a medicine outside it gets interaction flags only from the DDInter pairs.
- **Which model.** The optional structuring model is Amazon Nova Pro. Claude models can be called from a developer login on this AWS account but not yet from the server's role, so the live site cannot use them. On synthetic labels no model beat the rules alone. A model's output is only kept if its quote is found in the text that was read, and the photo itself is never sent to it.
- **Not evaluated with real families**, and the helper's refusal rules are keyword-based and can miss an unusual phrasing (every answer is also scanned for advice). WhatsApp and SMS are not built. The interface is English and Hindi.
- **Data limits where it can be used.** Severities are US/EU-centred, many Indian brands are combinations the data has never heard of, and recalls are US-only. DDInter is CC BY-NC-SA, so **not for commercial use as it stands**; a service would need licensed data, clinician review and the regulatory steps for health data.
- **A demo deployment**: one server in one availability zone, snapshots only (a hard crash can lose up to a minute), per-process rate limiting. The rollback step of the deploy has not been run on the live site. All of it, with the reasons: [Limits in full](docs/DETAILS.md#limits-in-full).

## Data and licences
Interaction data: **DDInter 2.0**, CC BY-NC-SA 4.0 (**non-commercial** use; attribution required), downloaded by `scripts/fetch_reference.py`, not stored in this repository.
Enzyme data: the FDA "Drug Development and Drug Interactions" substrates/inhibitors/inducers table. A snapshot of the FDA table (US government work) is bundled in `carecircle/snapshot/` as a fallback when the FDA site blocks scripted downloads. Demo circles, labels and people are synthetic.

## AI use disclosure
This project was built with help from Claude (Anthropic) via Claude Code: design discussion, code, tests and docs were written with
AI assistance and reviewed and run by the author. At runtime, an optional Amazon Bedrock model (Amazon Nova Pro by default; `CC_MODEL` can name another) only turns OCR/transcript text into
proposed fields; it never decides interactions or doses.

## Run it
Deployed on one AWS EC2 instance (t3.large, Docker Compose, Caddy for HTTPS, Bedrock through the instance role, only ports 80/443 open): `deploy/docker-compose.prod.yml`. Settings and secrets are kept in AWS Parameter Store and written to the instance at deploy time (`deploy/render_env.sh`); containers have memory limits and rotating logs; an outside health check raises an alarm that emails when the site stops answering; and the whole stack (instance, network rules, role, address, backup bucket, daily disk snapshots, alarms) is one CloudFormation template, `deploy/infra/carecircle.yaml`, which was tested by building a second copy from nothing, running the live checks against it and deleting it again (its optional restore-from-backup step was not exercised). Operations, in full: [`docs/DETAILS.md`](docs/DETAILS.md#operations).

```bash
# everything: FalkorDB (append-only volume) + app. First start downloads the public reference data and loads it (a few minutes).
GRAPHMEM_ADMIN_KEY=change-me docker compose up -d --build
open http://localhost:8000          # press "Start a demo circle"     (FalkorDB Browser: http://localhost:3000)
```

Without Docker, settings (Cognito, model, cookie sessions, database password, reminders, Telegram) and how to look inside the graph: [Running it and settings](docs/DETAILS.md#running-it-and-settings).

## More detail

The full write-up is [`docs/DETAILS.md`](docs/DETAILS.md) (where FalkorDB fits, the graph model, queries and algorithms, agents, what is in each screen, the 90-second demo, measurements, operations). Also: [`docs/HAZARDS.md`](docs/HAZARDS.md) (what can go wrong and the test behind each), [`docs/REVIEW_PROBES.md`](docs/REVIEW_PROBES.md) (the review's own probes, run again), [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md), [`docs/SCENARIOS.md`](docs/SCENARIOS.md), [`docs/API.md`](docs/API.md), [`docs/TRACK02.md`](docs/TRACK02.md). How many tests and scenarios there are right now: `python scripts/counts.py` (produced, not typed here).
