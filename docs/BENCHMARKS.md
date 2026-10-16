# Benchmarks (Care Circle)

One laptop (Windows, Docker Desktop, 12 logical CPUs, FalkorDB 4.22.1), seeded, no LLM. The first set of numbers below came from single runs on FalkorDB 6.0.2; the section "Repeated runs" at the end repeats B1-B5 and the load test 7 times on the pinned 4.22.1 and reports median and range. Reproduce: `PYTHONPATH=. python bench/care_bench.py`, or `PYTHONPATH=. python bench/repeat.py care_bench --runs 7`.
Data: DDInter 2.0 (CC BY-NC-SA 4.0, non-commercial) and FDA's CYP index table (index drugs only; the page says it is not exhaustive).

## B1 Enzyme-path rule vs DDInter (two independent public sources)
The graph rule: *X inhibits/induces enzyme E, Y is a substrate of E* (a two-step traversal) flags X-Y even with no direct interaction row.

| Substrate source | Enzyme-path pairs | Also listed in DDInter | Listed as moderate or major |
|---|---|---|---|
| FDA index substrates | 38 | 31 (82%) | 31 |
| Curated substrates (unverified) | 39 | 33 (85%) | 32 |

Recall: between the same drug sets DDInter lists 145 moderate/major pairs; the rule recovers 61 (42%). So the rule is **precise but narrow**,
limited by the small FDA index table, and it supplements, never replaces, the direct DDInter lookup. 26% of DDInter pairs have severity "Unknown";
they are shown as unrated, never as safe. Caveat: "also listed" cross-checks agreement between sources, it is not a clinical validation.

## B2 Carer-staleness query vs an independent oracle
40 generated circles (3 carers, 3-8 changes, random acknowledgements). The Cypher-based query returns exactly the oracle's set of
unacknowledged changes for every carer in **40/40** circles. Baseline "only track each carer's most recent change" is exact in **4/40**.
The oracle states the rule independently of the code: a carer is behind on a medicine when the entry that stands now (by date) is someone else's and they have not seen it. Entries typed again unchanged record nothing, and a medicine can only be stopped once it is on the record. (The benchmark was re-run after the scenario fixes, which tightened these rules; it had gone out of date, and the oracle was brought in line with the rules as documented in `docs/SCENARIOS.md`, not with whatever the code returned.)
This shows correctness of the graph query against an independently written oracle; it does not show clinical benefit.

## B3 Double-dose guard
100 rounds of 10 concurrent claims on one dose slot from two carers: exactly one winner in **100/100** rounds (single MERGE claim).

## B4 Intake on real photos and speech (small, hand-checked, rules path with no model)
5 real photographs of medicine bottles from Wikimedia Commons (CC licences, used for testing only, not stored in the repo) and 1 synthetic-speech recording
(Windows speech synthesizer, played into Chrome's microphone and transcribed by Whisper `base`).

| Input | What OCR/ASR read | Result |
|---|---|---|
| Generic Truvada bottle | "Emtricitabine and / Tenofovir / Disoproxil Fumarate ... 200 mg/300 mg" | emtricitabine found; the strength was attached to a wrong second candidate ("diroximel fumarate"): a person must pick |
| AcipHex sample bottle | "AcipHex / rabeprazolesodium / 20mg" | rabeprazole 20mg, quote verified |
| Anastrozole bottle | "ANASTROZOLE ... TABLETS" | anastrozole (no strength legible) |
| Advil bottle | "Advil LIQUI-GELS" | ibuprofen via the brand list (no strength legible) |
| Aspirin bottle | "GENUINE ASPIRIN ..." | acetylsalicylic acid via the brand list |
| Voice, "chlorythromycin 500 mg twice daily" | Whisper spelled the drug "chlorythromycin" | clarithromycin 500 mg after single-word fuzzy matching |

Drug named correctly as a candidate in 5/5 photos and the voice note; strength captured correctly in 2 of the 3 inputs that show one. One wrong candidate
shown beside a right one. n is tiny and these are clean product shots, not curved, creased or blurry home photos, so this shows the pipeline works on real pixels and real speech, not its accuracy in a kitchen.

## Not measured
OCR/ASR accuracy at scale or on home-quality photos and varied accents, interaction-severity accuracy against clinical truth, any patient outcome.

## Comparing two runs: `bench/gate.py`
`python bench/care_bench.py --out run.json` writes the numbers with the seed, the parameters, a fingerprint of the machine, the FalkorDB version and the commit. `python bench/gate.py bench/baselines/care_bench.json run.json` then compares two such files and prints every check.

- It **refuses** (exit 2, nothing judged) when the runs are not alike: a different benchmark, seed or parameters, or a metric present in only one.
- Counts that come from the data or the design must be identical (`exact`); counts of things done right must not fall (`higher`); a latency may rise by 25% plus a 2 ms noise floor (`lower`), and is judged only when both runs ran on the same machine.
- Exit 1 means something got worse. In CI the gate runs on every push with the B1 numbers skipped (they depend on the downloaded reference data) and latency skipped automatically (a different machine from the baseline).
- Checked by breaking the code on purpose: letting a carer count their own entry as unseen turned B2 from 40/40 to 0/40 and the gate exited 1.

## Repeated runs (7 each, FalkorDB 4.22.1, one laptop)

`bench/repeat.py` runs a benchmark several times one after another and reports median, min and max. It exits 1 if any run failed its own checks or an exact result differed between runs (`tests/test_bench_repeat.py`).

**B1-B5 (`bench/repeat.py care_bench --runs 7`).** Every exact result was identical in all 7 runs: B1 counts (FDA: 38 path pairs, 31 also in DDInter, 31 moderate or major; recall 61 of 145), B2 40/40 against the oracle (baseline 4/40), B3 one winner in 100/100 rounds. Interaction check, 10 medicines, warm: p50 median 16.3 ms (11.9-17.5), p95 median 20.3 ms (15.7-23.8).

**Load test (`bench/repeat.py track02_stress --runs 7`, in-process, default scale of 30 agents and 30 tenants).** All audits passed in all 7 runs, zero request errors.

| Phase | Requests per second, median (min-max) | p95 latency, median (min-max) |
|---|---|---|
| A write storm, 30 agents on one session | 406 (309-435) | add_episode 115 ms (90-166) |
| B mixed, 20 writers + 10 readers | 266 (221-293) | add_episode 117 ms (99-162); recall 182 ms (161-255) |
| C claim race | 405 (322-452) | claim_task 157 ms (136-200) |
| D 30 tenants at once | 319 (305-399) | add_episode 118 ms (100-178) |
| E one request per event | 304 events/s (255-423) | |
| E batches of 20 | 5,299 events/s (3,862-6,146) | |

Read the ranges, not only the medians: throughput moved by up to 30% between identical runs on this laptop (a shared machine with Docker Desktop), so differences smaller than that are noise. These are laptop figures, not capacity planning for the live server.

## B4b Intake on 150 rendered labels at three levels of damage (`bench/intake_bench.py`)

The B4 sample above is five photos. This is the same pipeline (RapidOCR, then the rule-based reader, no model) on 150 medicine names drawn at random from the reference graph (seed 7), each printed on a synthetic label with a strength, a frequency line and distracting text, in random fonts, then damaged at three levels (moderate: slight tilt, blur, noise, JPEG 60; harsh: tilt up to 8 degrees, half-resolution, heavy blur and noise, JPEG 35). 450 images.

| Damage | Right medicine first | Right medicine in top 3 | Strength copied right | Strength left blank | A different number | Nothing proposed | Wrong extra suggestions |
|---|---|---|---|---|---|---|---|
| None | 150/150 | 150/150 | 145/150 | 5 | 0 | 0 | 0 |
| Moderate | 150/150 | 150/150 | 150/150 | 0 | 0 | 0 | 0 |
| Harsh | 139/150 | 140/150 | 129/150 | 10 | 1 | 10 | 0 |

What it showed. The first run found a real bug: a strength read with a stray full stop or colon from OCR (`40:mg`, `50.mg`) was dropped, leaving the strength blank; the reader now accepts that punctuation (`tests/test_carecircle.py`), which moved the moderate level from 148 to 150 of 150. The remaining blanks are a strength OCR split over lines (`0.5 / mg`), and at the harsh level a strength whose digits were lost (`TSmcg` for `75mcg`). One harsh image read `05mg` for 0.5 mg (the decimal point lost): a different number. **Every proposal is still shown to the person with its quoted line and needs their confirmation**, so these are cases where the person types the strength or corrects it, not silent errors; but a lost decimal point is exactly the kind of mistake a reader must catch, and this benchmark cannot show how often it happens on real labels.

What it does not show. The labels are synthetic, flat, horizontal, generic-name only and in Latin script: no brand names, curved bottles, glare, handwriting, other languages or hands. Real photographs will do worse, and the 5-photo B4 sample is still the only real-photo evidence. Speech was not repeated at scale.
