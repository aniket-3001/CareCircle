"""Accounts, sessions, circles, invitations and who may do what."""
import json
import urllib.parse

from harness import PW, World, rid, scenario


def q(s):
    return urllib.parse.quote(s, safe="")


@scenario("A1", "Sign up and sign in: email is case-insensitive and trimmed, duplicates refused, weak passwords refused")
def a1(w: World, r):
    tag = rid()
    email = f"Mixed.Case-{tag}@Scenario.Test"
    s = w.http.post("/v1/auth/signup", json={"email": f"  {email}  ", "password": PW, "name": "  Asha  "})
    r.check(s.status_code == 200, "signup with spaces around a mixed-case email works", s.text)
    r.check(s.json()["account"]["name"] == "Asha", "the name is trimmed", s.json()["account"])
    r.check(s.json()["account"]["email"] == email.lower(), "the email is stored lower-case", s.json()["account"])
    for variant in (email.upper(), email.lower(), f" {email} "):
        x = w.http.post("/v1/auth/signin", json={"email": variant, "password": PW})
        r.check(x.status_code == 200, f"sign in with {variant!r}", x.text)
    dup = w.http.post("/v1/auth/signup", json={"email": email.upper(), "password": PW, "name": "Again"})
    r.check(dup.status_code == 409, "the same email in another case is a duplicate (409)", dup.status_code)
    for pw in ("short1", "alllettersnodigit", "12345678901", "", " " * 10):
        x = w.http.post("/v1/auth/signup", json={"email": f"weak-{rid()}@scenario.test", "password": pw, "name": "W"})
        r.check(x.status_code == 400, f"password {pw!r} is refused with a 400", f"{x.status_code} {x.text[:80]}")
    for bad in ("not-an-email", "a@b", "a@b.", "@b.com", "a b@c.com", "a@@b.com", ""):
        x = w.http.post("/v1/auth/signup", json={"email": bad, "password": PW, "name": "B"})
        r.check(x.status_code in (400, 422), f"email {bad!r} is refused", f"{x.status_code}")
    x = w.http.post("/v1/auth/signup", json={"email": f"long-{rid()}@scenario.test", "password": "a1" * 120, "name": "L"})
    r.check(x.status_code in (400, 422), "an oversized password is refused, not hashed forever", x.status_code)
    x = w.http.post("/v1/auth/signup", json={"email": f"{'x' * 300}@scenario.test", "password": PW, "name": "L"})
    r.check(x.status_code in (400, 422), "an oversized email is refused", x.status_code)


@scenario("A2", "A wrong password never says which half was wrong; repeated failures are throttled")
def a2(w: World, r):
    u = w.user("Throttle")
    wrong = w.http.post("/v1/auth/signin", json={"email": u.email, "password": "wrong-pass9"})
    ghost = w.http.post("/v1/auth/signin", json={"email": f"nobody-{rid()}@scenario.test", "password": "wrong-pass9"})
    r.check(wrong.status_code == 401 and ghost.status_code == 401 and wrong.json() == ghost.json(),
            "a wrong password and an unknown email give the same answer", (wrong.text, ghost.text))
    codes = [w.http.post("/v1/auth/signin", json={"email": u.email, "password": f"wrong-{i}x1"}).status_code for i in range(14)]
    r.check(429 in codes, "after a run of failures the account is throttled (429)", codes)
    r.check(all(c in (401, 429) for c in codes), "nothing but 401/429 while guessing", codes)


@scenario("A3", "Sessions: sign-out ends only that session; odd headers are handled; a deleted account's token is dead")
def a3(w: World, r):
    u = w.user("Sess")
    second = w._token(w.http.post("/v1/auth/signin", json={"email": u.email, "password": PW}))
    r.check(w.http.get("/v1/account", headers={"Authorization": f"Bearer {second}"}).status_code == 200, "a second device is signed in")
    w.http.post("/v1/auth/signout", headers=u.h)
    r.check(u.get("/v1/account").status_code == 401, "the signed-out token is dead")
    r.check(w.http.get("/v1/account", headers={"Authorization": f"Bearer {second}"}).status_code == 200, "the other device stays signed in")
    for hdr in ({}, {"Authorization": "Bearer"}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer cs_" + "a" * 43}, {"Authorization": "bearer " + second}):
        x = w.http.get("/v1/account", headers=hdr)
        r.check(x.status_code in (200, 401), f"odd header {hdr} gives 200 or 401, not a crash", x.status_code)
    x = w.http.get("/v1/account", headers={"Authorization": "Bearer " + "x" * 5000})
    r.check(x.status_code in (401, 431, 400), "a 5,000 character token is refused", x.status_code)
    v = w.user("Gone")
    w.circle(v)
    d = v.delete("/v1/account", {"confirm": v.email})
    r.check(d.status_code == 200, "an account can delete itself with its email as confirmation", d.text)
    r.check(v.get("/v1/account").status_code == 401, "the deleted account's token is dead")
    r.check(w.http.post("/v1/auth/signin", json={"email": v.email, "password": PW}).status_code == 401, "and so is its password")
    again = w.http.post("/v1/auth/signup", json={"email": v.email, "password": PW, "name": "Gone"})
    r.check(again.status_code == 200, "the email can be used again after deletion", again.text)
    r.check(w.http.get("/v1/account/circles", headers={"Authorization": f"Bearer {w._token(again)}"}).json() == [], "and the new account starts empty (no old circle comes back)")


@scenario("C1", "Creating circles: odd names, many circles, two circles with the same name")
def c1(w: World, r):
    u = w.user("Maker")
    ids = []
    for name, person in (("Mum's meds", "Mum"), ("Mum's meds", "Mum"), ("日本語の薬", "おばあちゃん"), ("Emoji 💊", "Nan 🌸"), ("a" * 80, "p" * 60)):
        x = u.post("/v1/account/circles", {"name": name, "person": person})
        r.check(x.status_code == 200, f"circle {name[:20]!r}/{person[:10]!r} is created", f"{x.status_code} {x.text[:80]}")
        if x.status_code == 200:
            ids.append(x.json()["id"])
    r.check(len(set(ids)) == len(ids), "every circle has its own id, even with the same name", ids)
    for name, person in (("", "Mum"), ("Name", ""), ("a" * 81, "Mum"), ("Name", "p" * 61), ("   ", "Mum")):
        x = u.post("/v1/account/circles", {"name": name, "person": person})
        r.check(x.status_code in (400, 422), f"circle {name[:10]!r}/{person[:10]!r} is refused", f"{x.status_code}")
    mine = u.get("/v1/account/circles").json()
    r.check(len(mine) == len(ids) and all(c["role"] == "owner" for c in mine), "all the circles are listed, all owned", mine)


@scenario("C2", "Invitations: single use, wrong code, own circle, not the owner, and joining twice")
def c2(w: World, r):
    priya, omar, mallory = w.user("Priya"), w.user("Omar"), w.user("Mallory")
    c = w.circle(priya)
    r.check(omar.post(f"/v1/circles/{c}/invites").status_code == 403, "someone outside the circle cannot make an invitation")
    code = priya.post(f"/v1/circles/{c}/invites").json()["code"]
    r.check(mallory.post("/v1/join", {"code": "WRONGCODE"}).status_code in (400, 404), "a wrong code is refused")
    own = priya.post("/v1/join", {"code": code})
    r.check(own.status_code in (400, 409), "the owner cannot join their own circle with their own code", f"{own.status_code} {own.text[:80]}")
    first = omar.post("/v1/join", {"code": code})
    r.check(first.status_code == 200 and first.json()["id"] == c, "the code was not used up by that mistake: a real carer can still join with it", first.text)
    r.check(mallory.post("/v1/join", {"code": code}).status_code in (400, 404), "a used code does not work a second time")
    code2 = priya.post(f"/v1/circles/{c}/invites").json()["code"]
    again = omar.post("/v1/join", {"code": code2})
    r.check(again.status_code in (400, 409), "joining a circle you are already in is refused, not duplicated", f"{again.status_code} {again.text[:80]}")
    r.check(len(priya.get(f"/v1/circles/{c}/members").json()) == 2, "the circle still has exactly two members", priya.get(f"/v1/circles/{c}/members").json())
    third = mallory.post("/v1/join", {"code": code2})
    r.check(third.status_code == 200, "and that refused attempt did not burn the code: Mallory can use it", third.text)
    x = mallory.post("/v1/join", {"code": ""})
    r.check(x.status_code in (400, 404, 422), "an empty code is refused", x.status_code)
    code3 = priya.post(f"/v1/circles/{c}/invites").json()["code"]
    for variant in (code3.lower(), f" {code3[:3]}-{code3[3:]} "):
        y = w.user("Variant").post("/v1/join", {"code": variant})
        r.check(y.status_code in (200, 400, 404), f"code variant {variant!r} is handled (no crash)", y.status_code)
        if y.status_code == 200:
            code3 = priya.post(f"/v1/circles/{c}/invites").json()["code"]


@scenario("C3", "An outsider with a real account cannot touch someone else's circle in any way")
def c3(w: World, r):
    priya, omar, mallory, c = w.team()
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily")
    ops = [("care_regimen", {"person": "mum"}), ("care_check", {"person": "mum"}), ("care_timeline", {"person": "mum"}), ("care_export_fhir", {"person": "mum"}),
           ("care_people", {}), ("care_handovers", {"person": "mum"}), ("care_followups", {"person": "mum"}), ("care_measures", {"person": "mum"}),
           ("care_appointments", {"person": "mum"}), ("care_profile", {"person": "mum"}), ("care_receipts", {}), ("care_chat_history", {}),
           ("care_record", {"person": "mum", "drug": "x", "dose_text": "1 mg"}), ("care_forget_person", {"person": "mum", "confirm": "mum"}),
           ("history", {"session": "s"}), ("stats", {}), ("add_episode", {"session": "s", "role": "user", "content": "x"})]
    for op, args in ops:
        s, b = mallory.op(c, op, **args)
        r.check(s == 403, f"Mallory calling {op} on Priya's circle is refused (403)", f"{s} {str(b)[:100]}")
    for method, path, body in (("get", f"/v1/circles/{c}/members", None), ("post", f"/v1/circles/{c}/invites", None), ("post", f"/v1/circles/{c}/leave", None),
                               ("delete", f"/v1/circles/{c}", {"confirm": "Mum's medicines"}), ("patch", f"/v1/circles/{c}", {"name": "mine now"})):
        if method == "get":
            x = mallory.get(path)
        elif method == "post":
            x = mallory.post(path, body)
        elif method == "delete":
            x = mallory.delete(path, body)
        else:
            x = w.http.patch(path, json=body, headers=mallory.h)
        r.check(x.status_code in (403, 404), f"Mallory: {method.upper()} {path.split(c)[1] or '/'} is refused", f"{x.status_code} {x.text[:80]}")
    r.check(c not in [x["id"] for x in mallory.get("/v1/account/circles").json()], "the circle is not in Mallory's list")
    r.check(priya.ok(c, "care_regimen", person="mum")[0]["drug"] == "warfarin", "and nothing changed for the real members")
    s, _ = mallory.op("tt-does-not-exist", "care_regimen", person="mum")
    r.check(s in (403, 404), "a circle id that does not exist is refused, not created", s)
    for evil in ("../ctl", "mem__x", "A B", "x" * 200, "x;MATCH (n) DETACH DELETE n", "%00", "ctl"):
        s, _ = mallory.op(q(evil), "care_regimen", person="mum")
        r.check(s in (400, 403, 404, 422), f"a hostile circle id {evil[:20]!r} is refused", s)


@scenario("C4", "Leaving, removing and ownership: the right people keep the right powers")
def c4(w: World, r):
    priya, omar, mallory, c = w.team()
    r.check(omar.delete(f"/v1/circles/{c}/members/{priya.agent}").status_code == 403, "a carer cannot remove the owner")
    r.check(priya.delete(f"/v1/circles/{c}/members/{omar.agent}").status_code == 200, "the owner can remove a carer")
    s, _ = omar.op(c, "care_regimen", person="mum")
    r.check(s == 403, "a removed carer loses access at once", s)
    r.check(c not in [x["id"] for x in omar.get("/v1/account/circles").json()], "and the circle leaves their list")
    w.join(priya, c, omar)
    left = priya.post(f"/v1/circles/{c}/leave")
    r.check(left.status_code == 200 and not left.json()["deleted_circle"], "the owner leaves a circle that still has a carer: it is not deleted", left.text)
    r.check(omar.get("/v1/account/circles").json()[0]["role"] == "owner", "ownership passes to the remaining carer", omar.get("/v1/account/circles").text)
    s, _ = priya.op(c, "care_regimen", person="mum")
    r.check(s == 403, "the former owner no longer has access", s)
    r.check(omar.delete(f"/v1/circles/{c}", {"confirm": "wrong"}).status_code == 400, "deleting needs the circle name")
    last = omar.post(f"/v1/circles/{c}/leave")
    r.check(last.status_code == 200 and last.json()["deleted_circle"], "the last member leaving deletes the circle and its data", last.text)
    s, _ = omar.op(c, "care_regimen", person="mum")
    r.check(s in (403, 404), "a deleted circle answers nothing", s)


@scenario("C5", "Rename and delete rules, and a removed carer's footprint")
def c5(w: World, r):
    priya, omar, mallory, c = w.team()
    r.check(w.http.patch(f"/v1/circles/{c}", json={"name": "Hijack"}, headers=omar.h).status_code == 403, "a carer cannot rename the circle")
    for bad in ("", "  ", "x" * 81):
        r.check(w.http.patch(f"/v1/circles/{c}", json={"name": bad}, headers=priya.h).status_code in (400, 422), f"rename to {bad[:10]!r} is refused")
    r.check(w.http.patch(f"/v1/circles/{c}", json={"name": "Renamed 💊"}, headers=priya.h).status_code == 200, "the owner can rename")
    r.check(any(x["name"] == "Renamed 💊" for x in omar.get("/v1/account/circles").json()), "the carer sees the new name")
    r.check(omar.delete(f"/v1/circles/{c}", {"confirm": "Renamed 💊"}).status_code == 403, "a carer cannot delete the circle even knowing its name")
    omar.ok(c, "care_chat_ask", person="mum", question="what is on record")
    r.check(len(omar.ok(c, "care_chat_history")) > 0, "Omar has a conversation with the helper")
    priya.delete(f"/v1/circles/{c}/members/{omar.agent}")
    w.join(priya, c, omar)
    r.check(omar.ok(c, "care_chat_history") == [], "his old conversation is gone after he was removed and re-joined (it goes with him)")
    r.check(priya.delete(f"/v1/circles/{c}", {"confirm": "renamed 💊"}).status_code == 200, "the owner deletes the circle (name match ignores case)")


@scenario("S1", "Hostile text everywhere is stored and returned as plain data")
def s1(w: World, r):
    priya, omar, mallory, c = w.team()
    nasty = ['<script>alert(1)</script>', "'; MATCH (n) DETACH DELETE n; //", '" OR 1=1 --', "\\", "{{7*7}}", "${jndi:ldap://x}", "‮ RTL", "line1\nline2", "💊" * 40]
    for text in nasty:
        s, b = priya.op(c, "care_handover", person="mum", text=text)
        r.check(s in (200, 400, 422), f"handover note {text[:18]!r} is accepted or cleanly refused", f"{s} {str(b)[:80]}")
        s, b = priya.op(c, "care_condition_add", person="mum", name=text)
        r.check(s in (200, 400, 422), f"condition {text[:18]!r} is accepted or cleanly refused", f"{s} {str(b)[:80]}")
        s, b = priya.op(c, "care_record", person="mum", drug=text, dose_text=text, freq_text=text)
        r.check(s in (200, 400, 422), f"medicine {text[:18]!r} is accepted or cleanly refused", f"{s} {str(b)[:80]}")
    notes = priya.ok(c, "care_handovers", person="mum")
    r.check(any("<script>" in n["text"] for n in notes), "the script tag comes back as text, unchanged (the page must escape it)", [n["text"] for n in notes][:3])
    r.check(priya.ok(c, "care_regimen", person="mum") is not None, "the circle still works afterwards")
    x = w.http.post(f"/v1/tenants/{c}/care_handover", content=b"x" * 3_000_000, headers={**priya.h, "content-type": "application/json"})
    r.check(x.status_code in (400, 413, 422), "a 3 MB request body is refused", x.status_code)
    x = w.http.post(f"/v1/tenants/{c}/care_handover", content=b"{not json", headers={**priya.h, "content-type": "application/json"})
    r.check(x.status_code in (400, 422), "malformed JSON is a clean 4xx", x.status_code)
    x = w.http.post(f"/v1/tenants/{c}/care_handover", json=["a", "list"], headers=priya.h)
    r.check(x.status_code in (400, 422), "a JSON list where an object is expected is a clean 4xx", x.status_code)
    x = w.http.post(f"/v1/tenants/{c}/not_an_operation", json={}, headers=priya.h)
    r.check(x.status_code in (400, 404), "an unknown operation is a clean 4xx", x.status_code)
    x = w.http.post(f"/v1/tenants/{c}/care_regimen", json={"person": "mum", "extra": 1}, headers=priya.h)
    r.check(x.status_code in (400, 422), "an unexpected argument is refused", x.status_code)
    x = w.http.post("/admin/agents", json={"agent": "evil"}, headers=priya.h)
    r.check(x.status_code in (401, 403, 503), "a user's session cannot reach the admin plane", x.status_code)


@scenario("S2", "Text the database cannot hold (NUL, broken Unicode) is a clean 400 in every place text is accepted")
def s2(w: World, r):
    priya, omar, mallory, c = w.team()
    for v in ("a\x00b", "x\ud800y"):
        label = ascii(v)
        raw = json.dumps(v)                                                  # the wire form: \u0000 and a lone \ud800 escape
        x = w.http.post("/v1/auth/signup", content=('{"email":"nul-%s@scenario.test","password":"%s","name":%s}' % (rid(), PW, raw)).encode(), headers={"content-type": "application/json"})
        r.check(x.status_code in (400, 422), f"sign-up name {label} is refused cleanly", f"{x.status_code}")
        x = w.http.post("/v1/account/circles", content=('{"name":%s,"person":"Mum"}' % raw).encode(), headers={**priya.h, "content-type": "application/json"})
        r.check(x.status_code in (400, 422), f"circle name {label} is refused cleanly", f"{x.status_code}")
        x = w.http.patch(f"/v1/circles/{c}", content=('{"name":%s}' % raw).encode(), headers={**priya.h, "content-type": "application/json"})
        r.check(x.status_code in (400, 422), f"rename to {label} is refused cleanly", f"{x.status_code}")
        x = w.http.patch("/v1/account", content=('{"name":%s}' % raw).encode(), headers={**priya.h, "content-type": "application/json"})
        r.check(x.status_code in (400, 422), f"profile name {label} is refused cleanly", f"{x.status_code}")
        for op, args in (("care_handover", {"person": "mum", "text": raw}), ("care_allergy_add", {"person": "mum", "text": raw}), ("care_appoint", {"person": "mum", "title": raw, "at": 4_000_000_000_000}),
                         ("care_measure", {"person": "mum", "kind": "weight", "value": 70, "note": raw}), ("care_chat_ask", {"person": "mum", "question": raw}),
                         ("care_record", {"person": raw, "drug": "warfarin"}), ("care_give", {"person": "mum", "drug": "warfarin", "slot": raw})):
            body = "{" + ",".join(f'"{k}":{v_ if k in ("text", "title", "note", "question", "slot", "person") and isinstance(v_, str) else json.dumps(v_)}' for k, v_ in args.items()) + "}"
            x = w.http.post(f"/v1/tenants/{c}/{op}", content=body.encode(), headers={**priya.h, "content-type": "application/json"})
            r.check(x.status_code in (400, 422), f"{op} with {label} is refused cleanly", f"{x.status_code} {x.text[:80]}")
    r.check(priya.ok(c, "care_regimen", person="mum") == [], "nothing was stored by any of those")
