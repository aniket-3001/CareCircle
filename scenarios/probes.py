"""The principal review's own probes, run again against a server, one line each: what the review did, what the review saw, what happens now.

  python scenarios/probes.py https://3-228-70-117.sslip.io          (anonymous demo circle only; a probe that needs the admin key is skipped and says so)
  PROBE_ADMIN_KEY=... python scenarios/probes.py http://127.0.0.1:8099   (all of them, against a local server)

Everything is done to a throwaway demo circle. A probe prints PASS when the server now refuses or corrects what the review showed it accepting, and FAIL when
the review's result still reproduces. The same probes have unit tests (named in the last column); this runs them end to end over HTTP on the deployed build.
"""
import os
import sys
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://3-228-70-117.sslip.io").rstrip("/")
ADMIN = os.getenv("PROBE_ADMIN_KEY", "")
http = httpx.Client(base_url=BASE, timeout=60)
rows: list[tuple[str, str, str, str, str]] = []      # id, probe, review saw, now, verdict
now = lambda: int(time.time() * 1000)  # noqa: E731


def record(pid, probe, saw, got, ok, test):
    rows.append((pid, probe, saw, got, "PASS" if ok else "FAIL", test))
    print(f"  {'PASS' if ok else 'FAIL'}  {pid}  {probe}  ->  {got}")


def skipped(pid, probe, saw, why, test):
    rows.append((pid, probe, saw, "skipped: " + why, "SKIP", test))
    print(f"  SKIP  {pid}  {probe}  ({why})")


d = http.post("/demo/start").json()
C = d["circle"]
ravi, meena = ({"Authorization": f"Bearer {d['keys'][k]}"} for k in ("ravi", "meena"))
P = "asha"


def op(h, name, **a):
    r = http.post(f"/v1/tenants/{C}/{name}", json=a, headers=h)
    try:
        b = r.json()
    except Exception:
        b = r.text
    return r.status_code, (b.get("result") if isinstance(b, dict) and "result" in b else b)


print(f"server {BASE}, throwaway demo circle {C}")

# 1. A read-only key consumed every reminder (care_nudges was authorised as a read).
ah = {"Authorization": f"Bearer {ADMIN}"}
if ADMIN:
    key = http.post("/admin/agents", json={"agent": "probe-ro-" + C[-6:]}, headers=ah).json().get("api_key", "")
    http.post("/admin/grants", json={"agent": "probe-ro-" + C[-6:], "tenant": C, "scopes": ["read"]}, headers=ah)
    s, _ = op({"Authorization": f"Bearer {key}"}, "care_nudges", person=P)
    s2, _ = op({"Authorization": f"Bearer {key}"}, "care_record", person=P, drug="x", dose_text="1 mg")
    record("P1", "read-only key calls care_nudges", "403 on care_record, then 200 on care_nudges; reminders consumed", f"care_nudges {s}, care_record {s2}", s == 403 and s2 == 403,
           "tests/test_scope_enforced.py")
else:
    skipped("P1", "read-only key calls care_nudges", "200 on care_nudges; reminders consumed", "needs the admin key to make a read-only key", "tests/test_scope_enforced.py")

# 2. A model answer of 1000 mg, three times daily on the line "METFORMIN 500 MG TABLETS" was shown as verified.
text = "CITY PHARMACY\nMETFORMIN 500 MG TABLETS\nTake ONE tablet twice daily"
r = http.post(f"/v1/tenants/{C}/intake", data={"text": text}, headers=ravi).json()
met = [x for x in r.get("proposals", []) if x["drug_candidates"] and x["drug_candidates"][0]["name"] == "metformin"]
good = len(met) == 1 and "1000" not in met[0]["dose_text"] and "three" not in met[0]["freq_text"]
record("P2", "label line METFORMIN 500 MG TABLETS", "dose 1000 mg / three times daily shown 'quote verified'", f"proposal dose {met[0]['dose_text']!r}, freq {met[0]['freq_text']!r}" if met else "no proposal", good,
       "tests/test_carecircle.py::test_a_model_cannot_attach_a_dose_the_quoted_line_does_not_say (the model path itself is mocked there)")

# 3. A typed call could claim source_type=photo and supply its own source_text.
s, b = op(ravi, "care_record", person=P, drug="warfarin", dose_text="5 mg", source_type="photo", source_text="WARFARIN 5 MG", quote="WARFARIN 5 MG", confirm=True)
verified = isinstance(b, dict) and b.get("verified")
record("P3", "forged source_type=photo with the caller's own source_text", "entry stored as photo-verified", f"status {s}, verified={verified}", s in (400, 422) or not verified, "tests/test_carecircle.py (source stored server-side)")

# 4. 21:00 and 21:15 by two carers on the same dose both got given: true.
op(ravi, "care_record", person=P, drug="ramipril", dose_text="5 mg", freq_text="once daily", source_type="typed")
day = time.strftime("%Y-%m-%d", time.gmtime())
s1, g1 = op(ravi, "care_give", person=P, drug="ramipril", slot=f"{day} 21:00")
s2, g2 = op(meena, "care_give", person=P, drug="ramipril", slot=f"{day} 21:15")
record("P4", "two carers give the same dose at 21:00 and 21:15", "both got given: true", f"first {g1.get('given') if isinstance(g1, dict) else g1}, second {g2.get('given') if isinstance(g2, dict) else (s2, g2)}",
       isinstance(g2, dict) and g2.get("given") is False or s2 in (400, 422) and isinstance(g1, dict) and g1.get("given") is True, "tests/test_care_schedule.py")

# 5. Any carer could permanently delete another carer's entry. (Both demo carers are owners, so this needs a plain carer: made with the admin key.)
if ADMIN:
    name = "probe-carer-" + C[-6:]
    ckey = http.post("/admin/agents", json={"agent": name}, headers=ah).json().get("api_key", "")
    http.post("/admin/grants", json={"agent": name, "tenant": C, "scopes": ["read", "write"]}, headers=ah)
    carer = {"Authorization": f"Bearer {ckey}"}
    s, e = op(ravi, "care_record", person=P, drug="losartan", dose_text="50 mg", source_type="typed")
    eid = e["id"] if isinstance(e, dict) else ""
    s2, _ = op(carer, "care_forget", dose_id=eid, reason="probe")
    s3, _ = op(carer, "care_mark_mistake", dose_id=eid, reason="probe")
    still = any(x["drug"] == "losartan" for x in (op(ravi, "care_regimen", person=P)[1] or []))
    record("P5", "a plain carer permanently erases another carer's entry", "deleted", f"care_forget -> {s2}; care_mark_mistake -> {s3}; entry kept in the record: {still or s3 == 200}", s2 == 403 and s3 == 200,
           "tests/test_mistake_and_forget.py")
else:
    skipped("P5", "a plain carer permanently erases another carer's entry", "deleted", "needs the admin key to make a plain carer (both demo carers are owners)", "tests/test_mistake_and_forget.py")

# 6. The shared demo accounts could be renamed and their password changed.
cfg = http.get("/v1/auth/config").json()
da = (cfg.get("demo_accounts") or [None])[0]
if da:
    r = http.post("/v1/auth/signin", json={"email": da["email"], "password": da["password"]})
    if r.status_code == 200 and r.json().get("token"):
        h = {"Authorization": "Bearer " + r.json()["token"]}
        a = http.patch("/v1/account", json={"name": "Hacked"}, headers=h).status_code
        b = http.post("/v1/account/password", json={"old": da["password"], "new": "another-pass-1"}, headers=h).status_code
        again = http.post("/v1/auth/signin", json={"email": da["email"], "password": da["password"]}).status_code
        record("P6", "rename / change password of a shared demo account", "both accepted; next visitor locked out", f"rename {a}, password {b}, next sign-in {again}", a == 403 and b == 403 and again == 200,
               "tests/test_accounts.py::test_the_shared_demo_accounts_cannot_be_renamed_or_have_their_password_changed")
    else:
        skipped("P6", "rename / change password of a shared demo account", "both accepted", f"demo sign-in answered {r.status_code} (cookie sessions or Cognito)", "tests/test_accounts.py")
else:
    skipped("P6", "rename / change password of a shared demo account", "both accepted", "this server publishes no shared demo accounts", "tests/test_accounts.py")

# 7. A free `person` argument created a second patient ("ashaa").
s, b = op(ravi, "care_record", person="ashaa", drug="metformin", dose_text="500 mg", source_type="typed")
record("P7", "person='ashaa' (a typo of the patient)", "a second patient was created", f"status {s}", s in (400, 404, 422), "tests/test_one_patient.py")

# 9. Shelcal swallowed into a neighbour's quote; combination brands dropped an ingredient.
r = http.post(f"/v1/tenants/{C}/intake", data={"text": "Telma-AM 40/5 once daily\nShelcal 500 once daily"}, headers=ravi).json()
names = [c["name"] for x in r.get("proposals", []) for c in x["drug_candidates"][:1]]
quotes = [x["quote"] for x in r.get("proposals", [])]
tel = "telmisartan" in names and "amlodipine" in names
shel = any("shelcal" in (x["quote"] or "").lower() for x in r.get("proposals", []))
record("P9", "'Telma-AM' and 'Shelcal' on a label", "Telma-AM reduced to one ingredient; Shelcal absorbed into the line above", f"ingredients {names}; Shelcal has its own proposal: {shel}", tel and shel, "tests/test_brands.py")

# 8. /demo/start unauthenticated and unthrottled; a loop rotated other visitors' circles out.
if ADMIN:
    codes = [http.post("/demo/start").status_code for _ in range(14)]
    record("P8", "/demo/start in a loop", "unthrottled; rotated other visitors out", f"{codes.count(200)} accepted, {codes.count(429)} refused (429)", 429 in codes, "tests/test_demo_cap.py")
else:
    skipped("P8", "/demo/start in a loop", "unthrottled", "not looped against a shared live site (it would use its demo allowance); covered by tests/test_demo_cap.py", "tests/test_demo_cap.py")

print()
print("| Probe | What it does | What the review saw | Now | Result | Test |")
print("|---|---|---|---|---|---|")
for pid, probe, saw, got, v, test in rows:
    print(f"| {pid} | {probe} | {saw} | {got} | {v} | {test} |")
bad = [r for r in rows if r[4] == "FAIL"]
print(f"\n{len(rows)} probes, {len([r for r in rows if r[4] == 'PASS'])} pass, {len([r for r in rows if r[4] == 'SKIP'])} skipped, {len(bad)} still reproduce")
sys.exit(1 if bad else 0)
