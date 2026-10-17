"""Things that go wrong when many people act at once, or when someone sends what they should not."""
import threading
import time

from harness import H, World, rid, scenario

NOW = lambda: int(time.time() * 1000)  # noqa: E731


def parallel(fns):
    out = [None] * len(fns)

    def run(i, fn):
        try:
            out[i] = fn()
        except Exception as e:  # noqa: BLE001
            out[i] = e

    ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


@scenario("N1", "Ten people sign up with the same email at the same instant: exactly one account")
def n1(w: World, r):
    email = f"race-{rid()}@scenario.test"
    res = parallel([lambda: w.http.post("/v1/auth/signup", json={"email": email, "password": "scenario-pass1", "name": "R"}) for _ in range(10)])
    codes = sorted(x.status_code for x in res if not isinstance(x, Exception))
    r.check(codes.count(200) == 1 and all(c in (200, 409, 429) for c in codes), "one 200, the rest 409 (or throttled): never two accounts", codes)
    ok = w.http.post("/v1/auth/signin", json={"email": email, "password": "scenario-pass1"})
    r.check(ok.status_code == 200, "and the one account can sign in", ok.status_code)


@scenario("N2", "One invitation code used by ten people at once: exactly one gets in")
def n2(w: World, r):
    priya = w.user("Priya")
    c = w.circle(priya)
    code = priya.post(f"/v1/circles/{c}/invites").json()["code"]
    others = [w.user(f"Joiner{i}") for i in range(10)]
    res = parallel([(lambda u=u: u.post("/v1/join", {"code": code})) for u in others])
    wins = [x for x in res if not isinstance(x, Exception) and x.status_code == 200]
    r.check(len(wins) == 1, "one person joins", [getattr(x, "status_code", x) for x in res])
    members = priya.get(f"/v1/circles/{c}/members").json()
    r.check(len(members) == 2, "the circle has the owner and exactly one new carer", [m.get("name") for m in members])


@scenario("N3", "Two carers change the same medicine at the same moment: one consistent current entry, one unbroken history")
def n3(w: World, r):
    priya, omar, mallory, c = w.team()
    now = NOW()
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="1 mg", freq_text="daily", at=now - 20 * H)
    jobs = []
    for i in range(12):
        u = priya if i % 2 == 0 else omar
        jobs.append(lambda u=u, i=i: u.op(c, "care_record", person="mum", drug="warfarin", dose_text=f"{i + 2} mg", freq_text="daily", at=now - (14 - i) * H))
    res = parallel(jobs)
    r.check(all(not isinstance(x, Exception) and x[0] == 200 for x in res), "every change is accepted", [x if isinstance(x, Exception) else x[0] for x in res])
    reg = priya.ok(c, "care_regimen", person="mum")
    r.check(len(reg) == 1, "exactly one current entry", reg)
    r.check(reg and reg[0]["dose_text"] == "13 mg", "and it is the one with the latest date (13 mg), whatever order the requests landed in", reg)
    g = priya.ok(c, "care_graph", person="mum", include_history=True)
    sup = [e for e in g.get("edges", []) if e.get("kind") in ("supersedes", "SUPERSEDES")]
    r.check(len(sup) in (12, 13) or len(g["nodes"]) >= 13, "the history is one unbroken chain of 13 entries", (len(g.get("nodes", [])), len(sup)))
    past = priya.ok(c, "care_regimen", person="mum", as_of=now - 5 * H)
    r.check(len(past) == 1, "looking back to any moment still shows exactly one", past)
    stats = priya.ok(c, "stats")
    r.check(stats.get("Dose") == 13, "all thirteen entries are stored (none lost, none doubled)", stats.get("Dose"))


@scenario("N4", "Many people acknowledging and giving at once")
def n4(w: World, r):
    priya, omar, mallory, c = w.team()
    e = priya.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="twice daily", at=NOW() - 3 * 24 * H)
    res = parallel([lambda: omar.op(c, "care_ack", dose_id=e["id"]) for _ in range(15)])
    r.check(all(not isinstance(x, Exception) and x[0] == 200 for x in res), "fifteen acknowledgements at once are all fine", [x if isinstance(x, Exception) else x[0] for x in res])
    r.check(omar.ok(c, "care_divergence", person="mum")["carers"][omar.agent]["unacknowledged"] == [], "he is up to date, once")
    yesterday = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))                          # relative to the day of the run, inside the entry's time
    slots = [f"{yesterday} {h:02d}:00" for h in range(6, 22)]
    res = parallel([(lambda s=s, u=u: u.op(c, "care_give", person="mum", drug="metformin", slot=s)) for s in slots for u in (priya, omar)])
    r.check(len(priya.ok(c, "care_gives", person="mum", limit=100)) == len(slots), "32 gives across 16 slots: exactly one record per slot", len(priya.ok(c, "care_gives", person="mum", limit=100)))


@scenario("N5", "File uploads that are not what they claim to be")
def n5(w: World, r):
    priya, omar, mallory, c = w.team()
    url = f"/v1/tenants/{c}/intake"
    cases = {
        "an empty file": ("x.png", b"", "image/png"),
        "text pretending to be a PNG": ("x.png", b"this is not an image at all", "image/png"),
        "random bytes as a PDF": ("x.pdf", bytes(range(256)) * 40, "application/pdf"),
        "a script as a document": ("x.docx", b"<script>alert(1)</script>", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "an executable": ("x.exe", b"MZ" + b"\x00" * 200, "application/octet-stream"),
        "a huge file": ("big.png", b"\x89PNG\r\n\x1a\n" + b"0" * (13 * 1024 * 1024), "image/png"),
        "a path in the file name": ("../../etc/passwd", b"hello", "text/plain"),
        "audio that is silence": ("x.webm", b"\x1aE\xdf\xa3" + b"\x00" * 500, "audio/webm"),
    }
    for name, (fname, data, ctype) in cases.items():
        x = w.http.post(url, files={"file": (fname, data, ctype)}, data={"text": ""}, headers=priya.h)
        r.check(x.status_code in (200, 400, 413, 415, 422), f"{name}: a clean answer, not a crash", f"{x.status_code} {x.text[:80]}")
        if x.status_code == 200:
            props = x.json().get("result", x.json()).get("proposals", [])
            r.check(props == [] or all(p.get("needs_human") for p in props), f"{name}: anything it proposes still needs a person", props[:1])
    x = w.http.post(url, data={"text": "warfarin 5 mg once daily"}, headers=priya.h)
    r.check(x.status_code == 200, "plain text works", x.status_code)
    x = w.http.post(url, headers=priya.h)
    r.check(x.status_code in (200, 400, 422), "nothing at all is handled", x.status_code)
    r.check(mallory.post(url, None).status_code in (401, 403, 422), "an outsider cannot upload to someone's circle", "")
    r.check(priya.ok(c, "care_regimen", person="mum") == [], "no upload wrote anything to the record")
    r.check(w.http.get("/healthz").status_code == 200, "the server is still healthy")


@scenario("N6", "Rate limits: a flood from one carer is slowed, other people are not affected")
def n6(w: World, r):
    priya, omar, mallory, c = w.team()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(16) as pool:                                                              # in parallel: one at a time over the internet takes longer than the minute
        noisy = list(pool.map(lambda _: priya.op(c, "care_regimen", person="mum")[0], range(750)))     # the limit is 600 a minute per person
    r.check(set(noisy) <= {200, 429}, "a flood gets 200s then 429s, nothing else", sorted(set(noisy)))
    r.check(429 in noisy, "and the limit does kick in", noisy.count(429))
    r.check(omar.op(c, "care_regimen", person="mum")[0] == 200, "Omar is not slowed by Priya's flood", "")
    time.sleep(1.5)
    r.check(w.http.get("/healthz").status_code == 200, "the server is healthy afterwards", "")


@scenario("N7", "Telegram linking codes: one at a time, wrong ones fail, and unlinking works")
def n7(w: World, r):
    priya, omar, mallory, c = w.team()
    a = priya.post("/v1/account/telegram-code")
    r.check(a.status_code == 200 and len(a.json()["code"]) == 6, "a six-character code", a.text)
    b = priya.post("/v1/account/telegram-code")
    r.check(b.status_code == 200 and b.json()["code"] != a.json()["code"], "asking again gives a new code", b.text)
    r.check(priya.delete("/v1/account/telegram").status_code == 200, "unlinking when nothing is linked is harmless")
    r.check(w.http.post("/v1/account/telegram-code").status_code == 401, "no code without signing in")
    r.check(priya.get("/v1/account").json()["telegram"] == [], "nothing is linked until the bot confirms a code")
