"""Core record scenarios against a deployed server, using the anonymous demo circle (the production site signs people in with Cognito, so scenario accounts cannot
be created there, but the demo circle gives two real carers with real keys). Everything is done to a throwaway person inside a throwaway circle.

  python scenarios/live_demo.py https://3-228-70-117.sslip.io
"""
import sys
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://3-228-70-117.sslip.io").rstrip("/")
H = 3_600_000
now = lambda: int(time.time() * 1000)  # noqa: E731
http = httpx.Client(base_url=BASE, timeout=60)
fails = []
checks = 0


def check(cond, what, got=""):
    global checks
    checks += 1
    if not cond:
        fails.append((what, str(got)[:200]))
    print(f"  {'ok ' if cond else 'FAIL'} {what}" + ("" if cond else f"   <- {str(got)[:120]}"))


d = http.post("/demo/start").json()
c = d["circle"]
ravi, meena = ({"Authorization": f"Bearer {d['keys'][k]}"} for k in ("ravi", "meena"))
P = "livetest"


def op(h, name, **a):
    r = http.post(f"/v1/tenants/{c}/{name}", json=a, headers=h)
    try:
        b = r.json()
    except Exception:
        b = r.text
    return r.status_code, (b.get("result") if isinstance(b, dict) and "result" in b else b)


def ok(h, name, **a):
    s, b = op(h, name, **a)
    assert s == 200, f"{name} {a} -> {s} {str(b)[:120]}"
    return b


print(f"server {BASE}, throwaway demo circle {c}, person {P!r}")
print("timeline: back-dating, forgetting, stopping")
t = now()
ok(ravi, "care_record", person=P, drug="metformin", dose_text="1000 mg", freq_text="twice daily", at=t - 2 * H)
ok(ravi, "care_record", person=P, drug="metformin", dose_text="500 mg", freq_text="twice daily", at=t - 30 * 24 * H)
reg = ok(ravi, "care_regimen", person=P)
check(len(reg) == 1 and reg[0]["dose_text"] == "1000 mg", "a back-dated entry does not replace the current one", reg)
b = ok(ravi, "care_record", person=P, drug="warfarin", dose_text="40 mg", freq_text="daily", at=t - 1 * H)
ok(ravi, "care_record", person=P, drug="warfarin", dose_text="4 mg", freq_text="daily", at=t - 5 * H)
ok(ravi, "care_forget", dose_id=b["id"], reason="typo")
w = [x for x in ok(ravi, "care_regimen", person=P) if x["drug"] == "warfarin"]
check(len(w) == 1 and w[0]["dose_text"] == "4 mg", "forgetting a typo brings back the earlier dose", w)
s, _ = op(ravi, "care_record", person=P, drug="neverrecorded", action="stop")
check(s == 404, "stopping something never recorded is refused", s)
check(op(ravi, "care_record", person=P, drug="", dose_text="1 mg")[0] in (400, 422), "a blank medicine name is refused")
print("who has seen what")
div = ok(meena, "care_divergence", person=P)
mine = [v for k, v in div["carers"].items() if k.startswith("meena")]
check(mine and len(mine[0]["unacknowledged"]) == 2, "Meena is behind on both medicines (one each, not one per change)", mine)
print("giving doses")
slot = time.strftime("%Y-%m-%d", time.gmtime()) + " 08:00"
check(ok(ravi, "care_give", person=P, drug="metformin", slot=slot)["given"] is True, "a real slot for a medicine on record is accepted")
check(ok(meena, "care_give", person=P, drug="metformin", slot=slot)["given"] is False, "the same slot from the other carer is refused politely")
for bad in ("garbage", "2026-13-45 08:00", "2099-01-01 08:00"):
    check(op(ravi, "care_give", person=P, drug="metformin", slot=bad)[0] in (400, 422), f"slot {bad!r} is refused")
check(op(ravi, "care_give", person=P, drug="neverrecorded", slot=slot)[0] in (400, 404, 422), "a medicine not on record cannot be given")
print("text safety")
check(op(ravi, "care_handover", person=P, text="a\u0000b")[0] in (400, 422), "a NUL character is a clean 4xx, not a crash")
check(op(ravi, "care_handover", person=P, text="x" * 5000)[0] in (400, 422), "an oversized note is refused, not cut short")
print("helper")
s, a = op(ravi, "care_chat_ask", person=P, question="Should she stop the warfarin?")
check(s == 200 and a["source"] == "refusal", "advice is declined", a)
s, a = op(ravi, "care_chat_ask", person=P, question="why does she feel dizzy after the tablets")
check(s == 200 and "prescriber or pharmacist" in a["text"], "a symptom question is pointed to a pharmacist", a)
s, a = op(ravi, "care_chat_ask", person=P, question="add metformin 500mg twice daily and atorvastatin 20 mg at night")
check(s == 200 and len(a.get("proposals", [])) == 2, "two medicines in one sentence are two proposals", len(a.get("proposals", [])))
print("export and erase")
fhir = ok(ravi, "care_export_fhir", person=P)
meds = [e["resource"] for e in fhir["entry"] if e["resource"]["resourceType"] == "MedicationStatement"]
names = sorted(m["medicationCodeableConcept"]["text"].lower() for m in meds)
active = sorted(m["medicationCodeableConcept"]["text"].lower() for m in meds if m["status"] == "active")
check(names == ["metformin", "metformin", "warfarin"] and active == ["metformin", "warfarin"], "the export has one statement per period (metformin's earlier dose ended, its current one and warfarin active)", (names, active))
res = ok(ravi, "care_forget_person", person=P, confirm=P)
check(res["forgotten"] is True, "the person can be erased")
check(ok(ravi, "care_regimen", person=P) == [] and ok(ravi, "care_gives", person=P) == [], "and nothing of theirs remains")
print("outsider")
check(http.post(f"/v1/tenants/{c}/care_regimen", json={"person": P}, headers={"Authorization": "Bearer cs_" + "a" * 43}).status_code == 401, "an invalid key is refused")
check(http.get("/healthz").status_code == 200, "the server is healthy at the end")
print(f"\n{checks} checks, {len(fails)} failed")
for what, got in fails:
    print(f"  FAILED: {what}: {got}")
sys.exit(1 if fails else 0)
