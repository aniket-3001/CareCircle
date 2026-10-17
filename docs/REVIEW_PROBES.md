# The principal review's probes, run again

The review made nine claims it had reproduced. `scenarios/probes.py` repeats each one end to end over HTTP, against a throwaway demo circle, and prints PASS when the server now refuses or corrects what the review saw it accepting. It was run on 17 October 2026 against a local server with the admin key (all nine) and against the deployed site (the five that can be done without the admin key; the others are skipped there, with the reason in the table). Each row names the unit test that holds the rule.

| Probe | What it does | What the review saw | Now (live site) | Live | Local (admin key) | Test |
|---|---|---|---|---|---|---|
| P1 | read-only key calls care_nudges | 200 on care_nudges; reminders consumed | skipped: needs the admin key to make a read-only key | SKIP | PASS (403 / 403) | tests/test_scope_enforced.py |
| P2 | label line METFORMIN 500 MG TABLETS | dose 1000 mg / three times daily shown 'quote verified' | proposal dose '500 MG', freq 'twice daily' | PASS | PASS | tests/test_carecircle.py::test_a_model_cannot_attach_a_dose_the_quoted_line_does_not_say (the model path itself is mocked there) |
| P3 | forged source_type=photo with the caller's own source_text | entry stored as photo-verified | status 200, verified=False | PASS | PASS | tests/test_carecircle.py (source stored server-side) |
| P4 | two carers give the same dose at 21:00 and 21:15 | both got given: true | first True, second False | PASS | PASS | tests/test_care_schedule.py |
| P5 | a plain carer permanently erases another carer's entry | deleted | skipped: needs the admin key to make a plain carer (both demo carers are owners) | SKIP | PASS (403; marked as a mistake instead, entry kept) | tests/test_mistake_and_forget.py |
| P6 | rename / change password of a shared demo account | both accepted | skipped: demo sign-in answered 404 (cookie sessions or Cognito) | SKIP | PASS (403 / 403, next sign-in 200) | tests/test_accounts.py |
| P7 | person='ashaa' (a typo of the patient) | a second patient was created | status 422 | PASS | PASS | tests/test_one_patient.py |
| P9 | 'Telma-AM' and 'Shelcal' on a label | Telma-AM reduced to one ingredient; Shelcal absorbed into the line above | ingredients ['telmisartan', 'amlodipine', 'calcium carbonate', 'cholecalciferol']; Shelcal has its own proposal: True | PASS | PASS | tests/test_brands.py |
| P8 | /demo/start in a loop | unthrottled | skipped: not looped against a shared live site (it would use its demo allowance); covered by tests/test_demo_cap.py | SKIP | PASS (11 accepted, 3 refused (429)) | tests/test_demo_cap.py |

## What this found

- **P4 still reproduced when I first ran it** (21:00 and 21:15 by two carers both returned `given: true`). The Today screen was already safe because it only offers the confirmed times, but the plain `care_give` operation (API, MCP tool, Telegram `/gave`) still took any typed time. It now moves a typed time to the nearest confirmed one (within 90 minutes, otherwise refused with the list), and with no times set treats a give within an hour of an earlier one as the same dose. Test: `tests/test_care_schedule.py::test_a_dose_given_at_21_00_and_21_15_is_one_dose_whether_or_not_times_are_set`. The cost: a genuine second dose of an as-needed medicine within an hour is refused, with a note saying who recorded the earlier one.
- **P5 as first written was a mistake in the probe**: both demo carers are owners, so one could erase the other's entry by design. The probe now uses a plain carer made with the admin key.
- **Not covered by a probe**: the model path of P2 (the model's own answer is only mocked in the unit test; the live server answers through a model, whose wrong answer cannot be forced there), blocking Telegram I/O, the production configuration and the `care_divergence` path split (unit and compose tests).
- Nothing here is clinical evidence. It shows that nine specific, previously reproduced failures no longer reproduce.
