# Scenario testing

Unit tests check that a function does what its author meant. A scenario checks that the *product* behaves when a person (or a careless or hostile one) does what people really do: type the same thing twice, back-date an entry, leave a circle, lose their network, paste a hundred characters with no spaces, ask the helper to bend its rules. Each scenario signs up real accounts and uses the real HTTP API or a real browser, then states what must be true afterwards. Failures are collected, not raised, so one run shows every problem.

```
python -m graphmem.api &                                   # a server on :8000 (or set SCENARIO_URL)
SCENARIO_URL=http://localhost:8000 python scenarios/run.py            # 47 scenarios through the API (about 685 checks)
SCENARIO_URL=http://localhost:8000 python scenarios/ui_scenarios.py   # 25 scenarios in Chrome (125 checks)
python scenarios/run.py M                                  # only the scenarios whose id starts with M
```

They run in CI on every push (`.github/workflows/tests.yml`).

The cast: **Priya** owns a circle for Mum, **Omar** is a second carer, **Mallory** has an account but no part in it.

## What is covered

| Id | Feature | What the scenario does |
|---|---|---|
| A1 | Sign up and in | Mixed-case and padded emails, duplicates in another case, weak and oversized passwords, malformed emails |
| A2 | Sign-in safety | Wrong password vs unknown email give the same answer; a run of failures is throttled |
| A3 | Sessions | Sign-out ends one session only; odd or oversized auth headers; a deleted account's token and password are dead; the email can be reused and the old circle does not come back |
| C1 | Circles | Emoji, Japanese and 80-character names; two circles with the same name; blank and oversized names refused |
| C2 | Invitations | Wrong, empty, reused and own-circle codes; joining twice; a refused attempt must not use up the code |
| C3 | An outsider | Mallory tries 17 operations and 5 circle endpoints on Priya's circle, and 7 hostile circle ids |
| C4 | Membership | Carer cannot remove the owner; removal revokes access at once; ownership passes on; the last member leaving deletes the circle |
| C5 | Rename and delete | Only the owner; the circle name must be typed; a removed carer's conversation goes with them |
| S1, S2 | Hostile input | Script tags, Cypher, SQL, template and Log4j strings, NUL bytes, broken Unicode, 3 MB bodies, malformed JSON, unknown operations and arguments, the admin plane |
| M1 | Pending entries | Not on the record, not checked, nobody "behind" until a person confirms |
| M2 | Changing a dose | One current entry, history kept, as-of looks back |
| M3 | Stop and restart | Flags go with the medicine; stopping something never recorded is refused; restart brings back the new dose |
| M4 | Same medicine typed three ways | One entry; re-typing the same dose is not a new change |
| M5 | Dose text | mcg to mg and hundredfold slips are flagged, odd formats kept as typed, blank or oversized names refused |
| M6 | Back-dating | An older prescription typed in late must not replace the current one; future-dated entries appear on their date |
| M7 | Forgetting | After forgetting a typo, the earlier dose is current again; the receipt keeps nothing |
| M8 | Interactions | Order does not matter; unknown medicines are listed, not "safe"; nothing is called safe |
| D1 | Who has seen what | A dose changed twice before anyone looked is one thing to catch up on; acknowledging the current entry covers older ones; a stop is also news |
| D2 | Joining and leaving | A new carer has seen nothing yet; a removed carer is not counted as behind |
| D3 | Reminders | Not early, once, escalate later, never about a replaced or seen entry; held for quiet hours then sent |
| D4 | Only one carer knows | Listed when true, gone once shared |
| G1 | Giving doses | Once per slot however the name is typed; garbage, empty and far-future slots refused; a medicine not on record, or stopped, refused |
| G2 | A race | Twelve simultaneous gives from two carers: exactly one recorded, nobody gets an error |
| G3 | Second-carer confirmation | Giver cannot witness; outsider cannot; unknown slot is a 404; unwatching |
| R1, R2 | Readings | Slips refused (1200 mmHg, NaN, true, text, future); other people's readings never mixed in; trend never uses judging words |
| P1 | Appointments | Ordering, lazy expiry, edit, cancel, ranges, empty "what to bring" page |
| L1 | Allergies | Hits appear when a related medicine is added, clear when the allergy is reworded, removed or the medicine stopped; no "stop", no "safe" |
| F1 | Follow-ups | Suggested, approved, not repeated, stale when the record moves on, dismissed ones stay dismissed |
| H1 | Handover notes | Append-only, attributed, kept when a carer leaves, oversized refused |
| E1 | Erasing a person | Every kind of record gone (checked by counting each kind in the graph), the other person in the circle untouched, receipt keeps nothing |
| E2 | Exports | FHIR has one statement per period of a medicine (a stop ends the earlier one, it is not a second one); the account export has the circle and no secrets |
| X1 | Advice requests | 34 phrasings, English, Hindi and Hinglish: all declined with the pharmacist pointer, none advise, none propose |
| X2 | Emergencies | Ten phrasings point to emergency services and name 112 and 911 |
| X3 | Answers about the record | Correct, and still correct after a stop or an acknowledgement |
| X4 | Manipulation | 14 attempts (ignore instructions, role-play, "system:", code fences, translate, poems, "school project") |
| X5 | Adding by chat | Only proposes; several medicines in one sentence; injection text writes nothing |
| X6, X7 | Chat input and history | Empty, huge, emoji, script tags; daily limit; each carer's conversation is their own and clearable |
| N1 | Races: sign-up | Ten sign-ups for one email at once: exactly one account |
| N2 | Races: invitation | One code used by ten people at once: exactly one gets in |
| N3 | Races: edits | Twelve edits to one medicine from two carers at once: one current entry, all thirteen stored, history unbroken, the latest-dated entry wins |
| N4 | Races: acknowledge and give | Fifteen acknowledgements and 32 gives across 16 slots: one record per slot |
| N5 | Uploads | Empty, fake, executable, 13 MB, path-in-name and silent-audio files: clean answers, anything proposed still needs a person |
| N6 | Rate limit | A flood from one carer is slowed (429); another carer is unaffected |
| N7 | Telegram codes | New code each time, sign-in required, nothing linked until the bot confirms |
| U1 | Browser: hostile text | A script/event-handler string in the name, circle, person, medicine, condition, allergy, note, appointment, reading and chat: shown as text, nothing runs |
| U2 | Browser: double-click | One entry, one note |
| U3 | Browser: reload and Back | Same tab, still signed in; after sign-out, Back shows nothing private |
| U4 | Browser: two carers | One adds, the other sees it unseen, marks it seen, the first sees that |
| U5 | Browser: session dies | Returns to sign-in with an explanation |
| U6 | Browser: no network | Says so in words, no endless spinner, recovers |
| U7 | Browser: long text on a phone | No sideways scrolling at 360 px on any tab |
| U8 | Browser: keyboard | Sign in with the keyboard only, Escape closes sheets, every control has an accessible name |
| U9, U10, U11 | Browser: preferences, form messages, demo | Theme and language persist; bad email and weak password are explained; the demo works end to end |

## What these scenarios found (and what was done)

Every row was found by a scenario, fixed, and is now pinned by it.

| Found | Fix |
|---|---|
| Joining a circle you were already in (including the owner using their own code) succeeded and used up the invitation | Refused with a clear message; the code is left for the person it was meant for |
| A NUL character in any text field was a 500 | One check (`graphmem/textcheck.py`) for every request body and operation: a clear 400 |
| "Stop" for a medicine that was never recorded created a phantom entry | Refused: nothing to stop |
| Re-typing an unchanged dose made every other carer "behind" again | An identical entry is recognised and nothing is added |
| A dose changed twice before a carer looked counted as two things to catch up on | One per medicine, the current entry |
| A blank or 300-character medicine name was accepted | 1 to 80 characters |
| A back-dated entry replaced the current one | A medicine's entries are laid out by date as one timeline (`_care_rechain`); an older entry slots into history |
| Forgetting the latest entry removed the medicine from the record | The timeline is laid out again, so the earlier dose is current |
| A "dose given" could be recorded with a garbage slot, a slot years ahead, or for a medicine not on record or already stopped | The slot must be a real date and time, and the medicine must have been on record then |
| Long text (a dose instruction, a handover note, an appointment) was silently cut off | Refused with the limit named: never shortened without telling anyone |
| A yes/no value was accepted as a weight | Refused |
| A follow-up someone dismissed was suggested again | Dismissed ones are not suggested again |
| The FHIR export listed a stopped medicine twice (once for the dose, once for the stop) | One statement per period on a medicine: a stop ends the earlier statement |
| "Add metformin 500 mg and atorvastatin 20 mg" became one merged proposal | One proposal per medicine, each with its exact quote |
| "Why does she feel dizzy after the tablets?" and "can I crush the tablet?" got a flat "I can't answer" with no pointer | They get the same prescriber-or-pharmacist pointer as other advice requests, in English and Hindi |
| When a session ended (signed out elsewhere, password changed, expired) the page kept looking signed in with broken sections | Any 401 returns to sign-in with a plain explanation |
| A very long unbroken name or note widened the page past a phone screen | Text wraps inside its box; the header cannot widen the page |
| Ten simultaneous sign-ups for one email crashed some of them (500) | The database's own uniqueness rule decides: one account, the losers get a clean 409 and leave nothing behind |
| A push-notification address could be any web address, and the server later sends a request to it | Only browsers' own push services are accepted (Chrome, Firefox, Safari, Edge); anything else, including internal addresses and look-alike hosts, is refused |

Earlier probing of the memory engine itself (handing a task to an agent with no access, empty or oversized events, bad limits) is in `docs/TRACK02.md`.

## Running against the live site

- It also runs against the live site: set `SCENARIO_URL` and `SCENARIO_COGNITO=<pool id>:<app client id>` and every user becomes a throwaway Cognito user (a made-up `@scenario.test` address) that is removed at the end. On 17 Oct 2026 this ran 42 scenarios against production: all passed except one that signs up with the app's own passwords, which a Cognito site does not offer (skipped), and a rate-limit scenario that sent its requests one at a time (too slow over the internet to reach the per-minute limit; now parallel, and passing live).
