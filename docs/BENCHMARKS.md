# Benchmarks (Care Circle)

Single runs on one laptop (Windows, Docker Desktop, FalkorDB 6.0.2), seeded, no LLM. Reproduce: `PYTHONPATH=. python bench/care_bench.py`.
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
unacknowledged changes for every carer in **40/40** circles. Baseline "only track each carer's most recent change" is exact in **0/40**.
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
