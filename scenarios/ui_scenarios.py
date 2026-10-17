"""Scenarios played in a real browser, the way a person (or a careless one, or a hostile one) would use the app.

  SCENARIO_URL=http://localhost:8099 python scenarios/ui_scenarios.py [prefix]
"""
import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
from harness import PW, User, World, rid  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

BASE = harness.BASE
RESULTS = []
ONLY = sys.argv[1] if len(sys.argv) > 1 else None
TABS = ["Today", "Add", "Circle", "Graph", "History"]


class Run(harness.Run):
    pass


def tab(pg, name):
    pg.locator(".tabbar").get_by_text(name, exact=True).click()
    if name == "Circle":                                         # the Circle screen keeps its secondary cards in one fold: open it
        pg.get_by_test_id("circle-more").wait_for(timeout=15000)
        pg.get_by_test_id("circle-more").evaluate("e => { e.open = true; }")
    if name == "Today":                                          # the reading aids sit in one fold below the verdict: open it
        pg.get_by_test_id("today-more").wait_for(timeout=20000)
        pg.get_by_test_id("today-more").evaluate("e => { e.open = true; }")


def new_page(browser, width=1280, height=900, errs=None, tz=None):
    ctx = browser.new_context(viewport={"width": width, "height": height}, **({"timezone_id": tz} if tz else {}))
    pg = ctx.new_page()
    pg.set_default_timeout(15000)
    if errs is not None:
        pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
        pg.on("dialog", lambda d: (errs.append(f"dialog: {d.message}"), d.dismiss()))
    return ctx, pg


def ui_signup(pg, name, email, pw=PW):
    pg.goto(BASE)
    pg.get_by_test_id("open-signup").click()
    pg.get_by_label("Your name").fill(name)
    pg.get_by_label("Email").fill(email)
    pg.get_by_label("Password", exact=True).fill(pw)
    pg.get_by_test_id("auth").get_by_role("button", name="Create account").click()


def ui_signin(pg, email, pw=PW):
    pg.goto(BASE)
    pg.get_by_test_id("open-signin").click()
    pg.get_by_label("Email").fill(email)
    pg.get_by_label("Password", exact=True).fill(pw)
    pg.get_by_test_id("auth").get_by_role("button", name="Sign in", exact=True).click()


def ui_circle(pg, circle="Mum's medicines", person="Mum"):
    expect(pg.get_by_text("Set up your first circle")).to_be_visible()
    pg.get_by_label("Circle name").fill(circle)
    pg.get_by_label("Person being looked after").fill(person)
    pg.get_by_role("button", name="Create").click()
    expect(pg.get_by_text("Nothing on record yet")).to_be_visible()


def api_user(w, email, name="Someone"):
    r = w.http.post("/v1/auth/signin", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    j = r.json()
    return User(w, name, email, w._token(r), j["account"]["id"])


def circle_of(u):
    return u.get("/v1/account/circles").json()[0]["id"]


SCEN = []


def scenario(sid, title):
    def deco(fn):
        fn.sid, fn.title = sid, title
        SCEN.append(fn)
        return fn
    return deco


# --------------------------------------------------------------------------------------------------------------------------------------------
@scenario("U1", "Hostile text typed into every field is shown as text and never runs")
def u1(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    pg.add_init_script("window.__pwned = 0;")
    evil = "<img src=x onerror=window.__pwned=1>"
    evil2 = "</script><script>window.__pwned=2</script>"
    email = f"u1-{rid()}@scenario.test"
    ui_signup(pg, evil, email)
    pg.get_by_label("Circle name").fill(f"Circle {evil}")
    pg.get_by_label("Person being looked after").fill(f"Mum {evil2}")
    pg.get_by_role("button", name="Create").click()
    expect(pg.get_by_text("Nothing on record yet")).to_be_visible()
    u = api_user(w, email, evil)
    c = circle_of(u)
    person = u.get("/v1/account/circles").json()[0]["person"]
    u.ok(c, "care_record", person=person, drug=f"warfarin{evil}", dose_text=f"4 mg {evil}", freq_text=evil2)
    u.ok(c, "care_condition_add", person=person, name=evil)
    u.ok(c, "care_allergy_add", person=person, text=evil2)
    u.ok(c, "care_handover", person=person, text=evil)
    u.ok(c, "care_appoint", person=person, title=evil, at=int(time.time() * 1000) + 86_400_000, place=evil2, bring=evil)
    u.ok(c, "care_measure", person=person, kind="weight", value=70, note=evil)
    pg.reload()
    for t in TABS:
        tab(pg, t)
        pg.wait_for_timeout(500)
    pg.get_by_test_id("open-assistant").click()
    box = pg.get_by_label("Your question")
    box.fill(evil)
    box.press("Enter")
    pg.wait_for_timeout(1500)
    pg.keyboard.press("Escape")
    r.check(pg.evaluate("window.__pwned") == 0, "no injected script or event handler ran anywhere", pg.evaluate("window.__pwned"))
    r.check(not errs, "no dialog, no uncaught error", errs[:3])
    tab(pg, "Circle")
    text = pg.inner_text("#main")
    r.check("<img src=x" in text, "the hostile text is visible as plain text (escaped, not dropped silently or run)", text[:200])
    ctx.close()


@scenario("U2", "Double-clicking save buttons does not create duplicates")
def u2(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u2-{rid()}@scenario.test"
    ui_signup(pg, "Dee", email)
    ui_circle(pg)
    tab(pg, "Add")
    pg.get_by_placeholder("e.g. Clarithromycin").fill("Warfarin 5 mg once daily")
    pg.get_by_role("button", name="Read it").click()
    card = pg.locator("[data-testid=proposal]").first
    expect(card).to_be_visible(timeout=60000)
    card.get_by_role("button", name="Confirm and save").dblclick()
    pg.wait_for_timeout(2000)
    u = api_user(w, email)
    c = circle_of(u)
    reg = u.ok(c, "care_regimen", person="mum")
    tl = [e for e in u.ok(c, "care_timeline", person="mum") if e["kind"] == "record"]
    r.check(len(reg) == 1 and len(tl) == 1, "one medicine and one history line after a double-click on Confirm", (len(reg), len(tl)))
    tab(pg, "Circle")
    pg.get_by_placeholder("Write a note for the next carer").fill("Only once please")
    pg.get_by_role("button", name="Add note").dblclick()
    pg.wait_for_timeout(1500)
    r.check(len(u.ok(c, "care_handovers", person="mum")) == 1, "one note after a double-click on Add note", len(u.ok(c, "care_handovers", person="mum")))
    r.check(not errs, "no errors", errs[:3])
    ctx.close()


@scenario("U3", "Reload keeps you signed in and where you were; signing out then going Back shows nothing private")
def u3(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u3-{rid()}@scenario.test"
    ui_signup(pg, "Rae", email)
    ui_circle(pg, "Gran's meds", "Gran")
    tab(pg, "Circle")
    pg.reload()
    expect(pg.get_by_test_id("open-account")).to_be_visible()
    r.check("circle" in pg.url.lower(), "after a reload you are still on the Circle tab", pg.url)
    pg.get_by_test_id("open-account").click()
    pg.get_by_test_id("top-signout").click()
    expect(pg.get_by_test_id("open-signin")).to_be_visible()
    pg.go_back()
    pg.wait_for_timeout(1000)
    body = pg.inner_text("body")
    r.check("Gran" not in body and "Nothing on record" not in body, "pressing Back after signing out shows no private data", body[:160])
    r.check(pg.get_by_test_id("open-signin").count() > 0 or pg.get_by_test_id("top-signin").count() > 0, "and offers sign-in")
    r.check(not errs, "no errors", errs[:3])
    ctx.close()


@scenario("U4", "Two carers: one adds a medicine, the other sees it is unseen, marks it seen, and the first sees that")
def u4(w, b, r):
    errs = []
    pe, oe = f"u4p-{rid()}@scenario.test", f"u4o-{rid()}@scenario.test"
    ctxp, pp = new_page(b, errs=errs)
    ui_signup(pp, "Pia", pe)
    ui_circle(pp)
    pu = api_user(w, pe)
    c = circle_of(pu)
    ctxo, po = new_page(b, errs=errs)
    ui_signup(po, "Ola", oe)
    expect(po.get_by_text("Set up your first circle")).to_be_visible()
    ou = api_user(w, oe)
    w.join(pu, c, ou)
    tab(pp, "Add")
    pp.get_by_placeholder("e.g. Clarithromycin").fill("Warfarin 5 mg once daily")
    pp.get_by_role("button", name="Read it").click()
    pp.locator("[data-testid=proposal]").first.get_by_role("button", name="Confirm and save").click()
    expect(pp.get_by_text("Warfarin").first).to_be_visible()
    po.goto(BASE)
    expect(po.get_by_text("Warfarin").first).to_be_visible(timeout=20000)
    tab(po, "Circle")
    expect(po.get_by_role("button", name="I have seen this").first).to_be_visible(timeout=15000)
    r.check(True, "Ola sees the medicine and a way to say she has seen it")
    po.get_by_role("button", name="I have seen this").first.click()
    pp.reload()
    tab(pp, "Circle")
    expect(pp.locator(".person", has_text="Ola")).to_contain_text("Up to date", timeout=15000)
    r.check(True, "Pia now sees Ola as up to date")
    r.check(not errs, "no errors in either browser", errs[:3])
    ctxp.close()
    ctxo.close()


@scenario("U5", "The session dies while the page is open: the next action asks to sign in, nothing breaks")
def u5(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u5-{rid()}@scenario.test"
    ui_signup(pg, "Sia", email)
    ui_circle(pg)
    pg.wait_for_timeout(2500)                                                                             # the first screen finishes loading (it sets the time zone) before the session dies
    api_user(w, email).post("/v1/account/signout-all")
    try:
        tab(pg, "History")                                                                                # this screen asks the server afresh
    except Exception:                                                                                     # the page may already have noticed and gone back to sign-in: also fine
        pass
    pg.wait_for_timeout(3000)
    body = pg.inner_text("body")
    signed_out = pg.get_by_test_id("open-signin").count() > 0 or pg.get_by_test_id("top-signin").count() > 0
    r.check(signed_out or "sign in" in body.lower() or "expired" in body.lower(), "the page returns to sign-in (or says the session ended), instead of a blank or broken screen", body[:200])
    r.check(not [e for e in errs if e.startswith("pageerror")], "with no uncaught errors", errs[:3])
    ctx.close()


@scenario("U6", "The network fails: the page says so and recovers, it does not spin forever")
def u6(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u6-{rid()}@scenario.test"
    ui_signup(pg, "Neo", email)
    ui_circle(pg)
    ctx.route("**/v1/**", lambda route: route.abort())
    tab(pg, "History")
    pg.wait_for_timeout(5000)
    body = pg.inner_text("#main")
    r.check(any(k in body.lower() for k in ("could not", "try again", "failed", "offline", "error", "check your connection")), "a failed load says so in words", body[:200])
    r.check(pg.locator(".skeleton").count() == 0, "and no loading placeholder is left spinning", pg.locator(".skeleton").count())
    ctx.unroute("**/v1/**")
    tab(pg, "Today")
    tab(pg, "History")
    pg.wait_for_timeout(1500)
    r.check("What did we know" in pg.inner_text("#main") or "Everything that happened" in pg.inner_text("#main"), "once the network is back it loads", pg.inner_text("#main")[:120])
    r.check(not [e for e in errs if e.startswith("pageerror")], "no uncaught errors", errs[:3])
    ctx.close()


@scenario("U7", "Very long names and notes do not break the layout on a phone-sized screen")
def u7(w, b, r):
    errs = []
    ctx, pg = new_page(b, width=360, height=780, errs=errs)
    email = f"u7-{rid()}@scenario.test"
    ui_signup(pg, "N" * 60, email)
    ui_circle(pg, "C" * 80, "P" * 60)
    u = api_user(w, email)
    c = circle_of(u)
    person = "p" * 40                                    # the longest name a circle can hold for the person (the form cuts it there)
    u.ok(c, "care_record", person=person, drug="d" * 80, dose_text="9" * 80, freq_text="f" * 80)
    u.ok(c, "care_handover", person=person, text="x" * 400)
    u.ok(c, "care_condition_add", person=person, name="c" * 80)
    u.ok(c, "care_appoint", person=person, title="t" * 80, at=int(time.time() * 1000) + 86_400_000, place="p" * 100, bring="b" * 200)
    pg.reload()
    for t in TABS:
        tab(pg, t)
        pg.wait_for_timeout(600)
        over = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        r.check(over <= 1, f"{t}: nothing forces sideways scrolling on a 360px screen", f"{over}px too wide")
    r.check(not errs, "no errors", errs[:3])
    ctx.close()


@scenario("U8", "Keyboard and screen-reader basics: sign in with the keyboard alone, Escape closes sheets, every control has a name")
def u8(w, b, r):
    errs = []
    user = w.user("Kay")
    ctx, pg = new_page(b, errs=errs)
    pg.goto(BASE)
    pg.get_by_test_id("open-signin").focus()
    pg.keyboard.press("Enter")
    pg.get_by_label("Email").focus()
    pg.keyboard.type(user.email)
    pg.keyboard.press("Tab")
    pg.keyboard.type(PW)
    pg.keyboard.press("Enter")
    expect(pg.get_by_test_id("open-account")).to_be_visible(timeout=15000)
    r.check(True, "sign-in completed from the keyboard alone")
    c = w.circle(user)
    pg.reload()
    for t in TABS:
        tab(pg, t)
        pg.wait_for_timeout(500)
        nameless = pg.evaluate("""() => [...document.querySelectorAll('button, a[href], input, select, textarea, [role=button]')]
            .filter(e => !e.closest('[hidden]') && e.offsetParent !== null && e.checkVisibility())
            .filter(e => !(e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || (e.innerText || '').trim() || e.getAttribute('title') || (e.labels && e.labels.length) || e.getAttribute('placeholder') || e.type === 'hidden'))
            .map(e => e.outerHTML.slice(0, 80))""")
        r.check(nameless == [], f"{t}: every visible control has an accessible name", nameless[:2])
    pg.get_by_label("About and safety").click()
    expect(pg.get_by_role("dialog")).to_be_visible()
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(500)
    r.check(pg.locator("dialog[open]").count() == 0, "Escape closes the About sheet")
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    del c
    ctx.close()


@scenario("U9", "Language and theme choices stay across reloads and sign-out")
def u9(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    pg.goto(BASE)
    pg.get_by_test_id("lang-toggle").click()
    pg.get_by_test_id("theme-toggle").click()
    theme = pg.evaluate("document.documentElement.dataset.theme")
    pg.reload()
    r.check(pg.evaluate("document.documentElement.dataset.theme") == theme, "the theme survives a reload", theme)
    r.check(pg.get_by_test_id("lang-toggle").inner_text().strip() == "EN", "the language (Hindi) survives a reload", pg.get_by_test_id("lang-toggle").inner_text())
    body = pg.inner_text("body")
    r.check(any("ऀ" <= ch <= "ॿ" for ch in body), "the page is actually in Hindi", body[:100])
    email = f"u9-{rid()}@scenario.test"
    pg.get_by_test_id("top-signup").click()
    pg.locator("[data-testid=auth] input[type=email]").fill(email)
    pg.locator("[data-testid=auth] input[type=password]").fill(PW)
    pg.get_by_test_id("auth").locator("button[type=submit]").click()
    pg.wait_for_timeout(2500)
    r.check(pg.evaluate("document.documentElement.dataset.theme") == theme and pg.get_by_test_id("lang-toggle").inner_text().strip() == "EN", "and they are still set after signing up", "")
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U10", "Sign-up form: bad email, weak password and a wrong password are explained in words, and no account is made by mistake")
def u10(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    posts = []
    pg.on("request", lambda q: posts.append(q.url) if "/v1/auth/signup" in q.url else None)
    pg.goto(BASE)
    pg.get_by_test_id("open-signup").click()
    pg.get_by_label("Email").fill("someone@gmail")
    pg.get_by_label("Password", exact=True).fill(PW)
    pg.get_by_test_id("auth").get_by_role("button", name="Create account").click()
    pg.wait_for_timeout(800)
    body = pg.inner_text("[data-testid=auth]")
    r.check("incomplete" in body.lower() or "mistyped" in body.lower() or "valid" in body.lower(), "an incomplete email is explained", body[:160])
    pg.get_by_label("Email").fill("someone@gmial.com")
    pg.get_by_test_id("auth").get_by_role("button", name="Create account").click()
    pg.wait_for_timeout(500)
    r.check("gmail.com" in pg.inner_text("[data-testid=auth]"), "a common typo suggests the fix", pg.inner_text("[data-testid=auth]")[:160])
    pg.get_by_label("Email").fill(f"ok-{rid()}@scenario.test")
    pg.get_by_label("Password", exact=True).fill("short")
    pg.get_by_test_id("auth").get_by_role("button", name="Create account").click()
    pg.wait_for_timeout(1200)
    r.check("8" in pg.inner_text("[data-testid=auth]") or "password" in pg.inner_text("[data-testid=auth]").lower(), "a weak password says what is needed", pg.inner_text("[data-testid=auth]")[:200])
    r.check(len(posts) <= 1, "mistakes that can be caught on the page are not sent to the server", posts)
    r.check(pg.locator("[data-testid=pw-eye]").count() >= 1, "the password field has a show/hide button")
    pg.get_by_label("Password", exact=True).fill("abc12345")
    pg.get_by_test_id("pw-eye").first.click()
    r.check(pg.get_by_label("Password", exact=True).get_attribute("type") == "text", "the eye shows what was typed")
    ctx.close()


@scenario("U11", "The one-click demo works end to end and can be reset")
def u11(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    pg.goto(BASE)
    pg.get_by_role("button", name="Start a demo circle").first.click()
    expect(pg.get_by_text("Metformin").first).to_be_visible(timeout=30000)
    r.check(True, "the demo circle loads with data")
    pg.reload()
    expect(pg.get_by_text("Metformin").first).to_be_visible(timeout=20000)
    r.check(True, "and survives a reload (it is on the server)")
    tab(pg, "Graph")
    pg.wait_for_selector(".kg__node", timeout=20000)
    r.check(pg.locator(".kg__node").count() > 3, "the graph draws its nodes", pg.locator(".kg__node").count())
    tab(pg, "History")
    expect(pg.get_by_text("Everything that happened")).to_be_visible()
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U12", "A combination brand is read as all its ingredients, and an unknown medicine is kept, marked as not checked")
def u12(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u12-{rid()}@scenario.test"
    ui_signup(pg, "Combo", email)
    ui_circle(pg, "Mum's medicines", "Mum")
    expect(pg.get_by_text("Nothing on record yet")).to_be_visible()
    tab(pg, "Add")
    pg.get_by_placeholder("e.g. Clarithromycin 500 mg twice daily for 7 days").fill("Telma-AM 40 mg once daily" + chr(10) + "Becosules 1 daily")
    pg.get_by_role("button", name="Read it").click()
    expect(pg.get_by_test_id("proposal")).to_have_count(3, timeout=20000)
    r.check(pg.get_by_test_id("combination-note").count() == 2, "both ingredients say they come from one combination product")
    r.check("telmisartan + amlodipine" in pg.get_by_test_id("combination-note").first.inner_text().lower(), "and name every ingredient", pg.get_by_test_id("combination-note").first.inner_text())
    r.check(pg.get_by_test_id("unchecked-note").count() == 1, "the medicine the data does not know says it will not be checked")
    for _ in range(3):
        pg.get_by_role("button", name="Confirm and save").first.click()
        pg.wait_for_timeout(900)
    u = api_user(w, email)
    c = circle_of(u)
    reg = {x["drug"] for x in u.ok(c, "care_regimen", person="mum")}
    r.check({"telmisartan", "amlodipine", "becosules"} <= reg, "all three are on the record, none dropped", reg)
    chk = u.ok(c, "care_check", person="mum")
    r.check("becosules" in chk["not_in_reference"] and chk["judgement"]["state"] == "partial", "and the verdict says one of them was not checked", chk["judgement"])
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U13", "Today's doses: set the times from the label, mark one given, and a second carer is told who did")
def u13(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u13-{rid()}@scenario.test"
    ui_signup(pg, "Dosey", email)
    ui_circle(pg, "Mum's medicines", "Mum")
    expect(pg.get_by_text("Nothing on record yet")).to_be_visible()
    u = api_user(w, email)
    c = circle_of(u)
    u.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="twice daily")
    pg.reload()
    expect(pg.get_by_test_id("unscheduled")).to_be_visible(timeout=20000)
    r.check("The label says twice a day" in pg.get_by_test_id("unscheduled").inner_text(), "a medicine with no times says what its label says", pg.get_by_test_id("unscheduled").inner_text())
    pg.get_by_test_id("set-times").first.click()
    inputs = pg.get_by_test_id("time-input")
    expect(inputs).to_have_count(2, timeout=10000)                                    # the sheet fills its times a moment after it opens
    r.check(inputs.count() == 2 and inputs.nth(0).input_value() == "08:00" and inputs.nth(1).input_value() == "20:00", "the suggested times are offered, editable", inputs.count())
    inputs.nth(1).fill("21:00")
    pg.get_by_test_id("save-times").click()
    expect(pg.get_by_test_id("slot")).to_have_count(2, timeout=15000)
    r.check(pg.get_by_test_id("slot").nth(1).inner_text().startswith("21:00") or "21:00" in pg.get_by_test_id("slot").nth(1).inner_text(), "the times a person confirmed are the ones on the checklist")
    r.check(pg.get_by_test_id("slot").nth(0).get_attribute("data-state") in ("given", "due", "not_marked", "upcoming", "before"), "each slot says where it stands")
    pg.get_by_test_id("give-slot").first.click()
    expect(pg.get_by_test_id("slot").first).to_have_attribute("data-state", "given", timeout=15000)
    reg = u.ok(c, "care_today", person="mum")
    r.check([i["state"] for i in reg["items"]].count("given") == 1, "exactly one slot is recorded as given", reg["counts"])
    first = reg["items"][0]
    again = u.ok(c, "care_give_slot", person="mum", dose_id=first["dose_id"], time=first["time"])
    r.check(again["given"] is False and again.get("already_given_by"), "a second try on the same slot is refused and names who gave it", again)
    pg.reload()
    expect(pg.get_by_test_id("checklist")).to_be_visible(timeout=20000)
    pg.get_by_test_id("packs").locator("summary").click()                                  # count the pack: 9 doses at two a day is about 4 days
    pg.get_by_test_id("pack-input").first.fill("9")
    pg.get_by_test_id("pack-save").first.click()
    expect(pg.get_by_test_id("pack-left").first).to_contain_text("9", timeout=15000)
    r.check("about 4" in pg.get_by_test_id("pack-left").first.inner_text(), "a counted pack says how many days it lasts, as an estimate", pg.get_by_test_id("pack-left").first.inner_text())
    tab(pg, "Circle")
    pg.get_by_test_id("outcomes").locator("summary").click()
    expect(pg.get_by_test_id("out-given")).to_contain_text("doses due were marked as given", timeout=15000)      # the numbers depend on the hour the scenario runs: a slot still inside its window is not due yet
    r.check("doses due were marked as given" in pg.get_by_test_id("out-given").inner_text(), "the week in counts shows doses marked against doses due", pg.get_by_test_id("out-given").inner_text())
    r.check(pg.locator("[aria-labelledby=dose-title] input[type=text]").count() == 0, "the dose card has no free-text slot box")
    times = pg.get_by_test_id("dose-time").locator("option").all_inner_texts()
    r.check(len(times) == 2 and times[0].startswith("08:00") and times[1].startswith("21:00"), "it offers the confirmed times of the medicine instead", times)
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U14", "The same ingredient from two products: a second doctor's Telma-AM next to plain amlodipine is flagged as a possible duplicate")
def u14(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u14-{rid()}@scenario.test"
    ui_signup(pg, "Dup", email)
    ui_circle(pg, "Mum's medicines", "Mum")
    expect(pg.get_by_text("Nothing on record yet")).to_be_visible()
    u = api_user(w, email)
    c = circle_of(u)
    u.ok(c, "care_record", person="mum", drug="amlodipine", dose_text="5 mg", freq_text="once daily")
    tab(pg, "Add")
    pg.get_by_placeholder("e.g. Clarithromycin 500 mg twice daily for 7 days").fill("Telma-AM 40 mg once daily")
    pg.get_by_role("button", name="Read it").click()
    expect(pg.get_by_test_id("proposal")).to_have_count(2, timeout=20000)
    for _ in range(2):
        pg.get_by_role("button", name="Confirm and save").first.click()
        pg.wait_for_timeout(900)
    expect(pg.get_by_test_id("duplicate-flag")).to_be_visible(timeout=20000)
    txt = pg.get_by_test_id("duplicate-flag").inner_text().lower()
    r.check("amlodipine" in txt and "telma-am" in txt and "may be the same medicine from two sources" in txt, "the flag names the ingredient and both sources", txt)
    r.check("duplicate" in pg.get_by_test_id("verdict").inner_text().lower(), "and the verdict says a possible duplicate was found", pg.get_by_test_id("verdict").inner_text()[:120])
    reg = u.ok(c, "care_regimen", person="mum")
    r.check(sorted((x["drug"], x["product"]) for x in reg) == [("amlodipine", ""), ("amlodipine", "telma-am"), ("telmisartan", "telma-am")], "both amlodipine entries are kept, not one replacing the other", reg)
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


def main():
    w = World()
    total = failed = 0
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        for fn in SCEN:
            if ONLY and not fn.sid.startswith(ONLY):
                continue
            run = Run(fn.sid, fn.title)
            t0 = time.perf_counter()
            try:
                fn(w, b, run)
            except Exception as e:
                run.check(False, "the scenario ran to the end", f"{type(e).__name__}: {str(e)[:200]} @ {traceback.format_exc().splitlines()[-3].strip()[:100]}")
            bad = [c for c in run.checks if not c["ok"]]
            total += len(run.checks)
            failed += len(bad)
            print(f"[{'PASS' if not bad else 'FAIL'}] {run.sid:<4} {run.title}  ({len(run.checks)} checks, {time.perf_counter() - t0:.0f}s)")
            for c in bad:
                print(f"        x expected: {c['expect']}\n          got: {c['got']}")
        b.close()
    print(f"\n{len(SCEN) if not ONLY else '-'} browser scenarios, {total} checks, {failed} failed")
    return failed


@scenario("U15", "The medicine picker can search the whole list, not only the best three guesses")
def u15(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u15-{rid()}@scenario.test"
    ui_signup(pg, "Seeker", email)
    ui_circle(pg, "Mum's medicines", "Mum")
    expect(pg.get_by_text("Nothing on record yet")).to_be_visible()
    tab(pg, "Add")
    pg.get_by_placeholder("e.g. Clarithromycin 500 mg twice daily for 7 days").fill("Warfarin 5 mg at bedtime")
    pg.get_by_role("button", name="Read it").click()
    expect(pg.get_by_test_id("proposal")).to_have_count(1, timeout=20000)
    pg.get_by_test_id("drug-search").fill("simvast")
    expect(pg.get_by_test_id("proposal").locator("option", has_text="Simvastatin")).to_have_count(1, timeout=10000)
    r.check(True, "typing part of a name offers it from the whole list")
    pg.get_by_test_id("proposal").locator("select").select_option(label="Simvastatin")
    pg.get_by_role("button", name="Confirm and save").first.click()
    pg.wait_for_timeout(1500)
    u = api_user(w, email)
    c = circle_of(u)
    reg = {x["drug"] for x in u.ok(c, "care_regimen", person="mum")}
    r.check(reg == {"simvastatin"}, "the searched medicine, not the first guess, is what was saved", reg)
    tab(pg, "History")
    pg.get_by_test_id("show-source").first.click()
    expect(pg.get_by_test_id("source-text").first).to_contain_text("Typed in by hand", timeout=10000)
    r.check(True, "an entry typed in says it has no photo or document behind it")
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U16", "The person's say: a carer writes down their answer, and the view written for them lists what is kept and makes no promise of safety")
def u16(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u16-{rid()}@scenario.test"
    ui_signup(pg, "Consen", email)
    ui_circle(pg, "Mum's medicines", "Mum")
    expect(pg.get_by_text("Nothing on record yet")).to_be_visible()
    u = api_user(w, email)
    c = circle_of(u)
    u.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="twice daily")
    tab(pg, "Circle")
    pg.get_by_test_id("consent").locator("summary").click()
    expect(pg.get_by_test_id("consent-status")).to_contain_text("Not asked yet", timeout=15000)
    pg.get_by_test_id("consent-answer").select_option("agreed")
    pg.get_by_test_id("consent-save").click()
    expect(pg.get_by_test_id("consent-status")).to_contain_text("Noted as agreed", timeout=15000)
    r.check(True, "the answer is written down with who gave it")
    pg.get_by_test_id("patient-view-toggle").click()
    expect(pg.get_by_test_id("patient-view")).to_be_visible(timeout=15000)
    text = pg.get_by_test_id("patient-view").inner_text().lower()
    r.check("metformin" in text and "does not give advice" in text and "who can see it" in text, "the view for the person lists the medicines, who sees them, and says it gives no advice", text[:200])
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U17", "A pharmacist link: the owner makes it, someone with no account reads it and leaves a note, the owner closes it and it stops working")
def u17(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u17-{rid()}@scenario.test"
    ui_signup(pg, "Sharer", email)
    ui_circle(pg, "Mum's medicines", "Mum")
    expect(pg.get_by_text("Nothing on record yet")).to_be_visible()
    u = api_user(w, email)
    c = circle_of(u)
    u.ok(c, "care_record", person="mum", drug="clarithromycin", dose_text="500 mg", freq_text="twice daily")
    u.ok(c, "care_record", person="mum", drug="atorvastatin", dose_text="20 mg", freq_text="at bedtime")
    pg.get_by_test_id("open-account").click()
    pg.get_by_role("button", name="Show details of Mum's medicines").click()
    pg.get_by_test_id("pharmacist-link").locator("summary").click()
    pg.get_by_test_id("share-make").click()
    expect(pg.get_by_test_id("share-url")).to_be_visible(timeout=15000)
    url = pg.get_by_test_id("share-url").locator("input").input_value()
    r.check("/share/ps_" in url, "a link is made and shown", url[:40])
    ctx2, other = new_page(b, errs=[])                                             # a different browser with no sign-in at all
    other.goto(url)
    expect(other.locator("h1")).to_contain_text("Medicines on record", timeout=15000)
    body = other.locator("body").inner_text()
    r.check("Clarithromycin" in body and "Atorvastatin" in body and "major" in body.lower(), "someone with no account sees the medicines and the flag", body[:160])
    r.check("not a statement that anything is safe" in body, "and is told it is not a statement of safety")
    other.locator("#n").fill("Dr. Rao")
    other.locator("#t").fill("Please ask about the pair")
    other.get_by_role("button", name="Send").click()
    expect(other.locator("#m")).to_contain_text("Thank you", timeout=10000)
    ctx2.close()
    pg.reload()                                                                    # the owner comes back to the Account page
    expect(pg.get_by_test_id("open-account")).to_be_visible(timeout=15000)
    pg.get_by_test_id("open-account").click()
    expect(pg.get_by_role("button", name="Show details of Mum's medicines")).to_be_visible(timeout=15000)
    pg.get_by_role("button", name="Show details of Mum's medicines").click()
    pg.get_by_test_id("pharmacist-link").locator("summary").click()
    expect(pg.get_by_test_id("share-rows")).to_contain_text("1 views", timeout=15000)
    expect(pg.get_by_test_id("share-reviews")).to_contain_text("Dr. Rao", timeout=15000)
    r.check("not verified" in pg.get_by_test_id("share-reviews").inner_text(), "the note comes back labelled as unverified")
    pg.get_by_role("button", name="Close it").click()
    ctx3, again = new_page(b, errs=[])
    resp = again.goto(url)
    r.check(resp.status == 404, "a closed link stops working", resp.status)
    ctx3.close()
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U18", "The history fingerprint: a kept line matches at once and still matches after a later entry is added")
def u18(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u18-{rid()}@scenario.test"
    ui_signup(pg, "Finger", email)
    ui_circle(pg, "Mum's medicines", "Mum")
    expect(pg.get_by_text("Nothing on record yet")).to_be_visible()
    u = api_user(w, email)
    c = circle_of(u)
    u.ok(c, "care_record", person="mum", drug="warfarin", dose_text="5 mg", freq_text="at bedtime")
    u.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="twice daily")
    tab(pg, "History")
    pg.get_by_test_id("fingerprint").locator("summary").click()
    expect(pg.get_by_test_id("fingerprint-line")).to_contain_text("2:", timeout=15000)
    kept = pg.get_by_test_id("fingerprint-line").inner_text().strip()
    pg.get_by_test_id("fingerprint-input").fill(kept)
    pg.get_by_test_id("fingerprint-check").click()
    expect(pg.get_by_test_id("fingerprint-verdict")).to_contain_text("exactly as they were", timeout=15000)
    r.check(True, "a kept fingerprint matches right away")
    u.ok(c, "care_record", person="mum", drug="amlodipine", dose_text="5 mg", freq_text="once daily")      # a later entry does not disturb it
    pg.get_by_test_id("fingerprint-check").click()
    expect(pg.get_by_test_id("fingerprint-verdict")).to_contain_text("exactly as they were", timeout=15000)
    r.check(True, "and still matches after a later entry is added")
    pg.get_by_test_id("chain-check").click()
    expect(pg.get_by_test_id("chain-verdict")).to_contain_text("unbroken", timeout=15000)
    r.check("3 entries" in pg.get_by_test_id("chain-verdict").inner_text(), "the stored log is unbroken and holds all three entries", pg.get_by_test_id("chain-verdict").inner_text())
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U19", "In Hindi, every screen reads in Hindi: no English sentence is left in the markup")
def u19(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u19-{rid()}@scenario.test"
    ui_signup(pg, "Hindi", email)
    ui_circle(pg, "Mum's medicines", "Mum")
    u = api_user(w, email)
    c = circle_of(u)
    for d, dose, f in (("warfarin", "5 mg", "at bedtime"), ("metformin", "500 mg", "twice daily"), ("clarithromycin", "500 mg", "twice daily")):
        u.ok(c, "care_record", person="mum", drug=d, dose_text=dose, freq_text=f)
    pg.get_by_test_id("lang-toggle").click()
    STOP = {"the", "and", "to", "of", "is", "a", "this", "with", "for", "you", "your", "not", "are", "be", "on", "in", "it", "or", "that", "from", "has", "have", "can", "will"}
    DATA = ".print-only, [data-testid=quote], .quote, [data-testid=timeline], [data-testid=cypher], pre, code, input, textarea, svg, [data-testid=graph-canvas]"
    left = []
    for t in ("today", "add", "circle", "graph", "history", "account"):
        pg.goto(f"{BASE}/#/{t}")
        pg.reload()
        pg.wait_for_timeout(1800)
        for d in ("today-more", "circle-more"):
            if pg.get_by_test_id(d).count():
                pg.get_by_test_id(d).evaluate("e => { e.open = true; }")
        texts = pg.evaluate("""(sel) => {
            const bad = document.querySelectorAll(sel), out = [];
            const w = document.createTreeWalker(document.querySelector('#root') || document.body, NodeFilter.SHOW_TEXT);
            for (let n = w.nextNode(); n; n = w.nextNode()) {
              const e = n.parentElement; if (!e || e.closest(sel)) continue;
              const s = n.textContent.replace(/\s+/g, ' ').trim(); if (s) out.push(s);
            }
            for (const e of document.querySelectorAll('[placeholder],[aria-label],[title]')) for (const a of ['placeholder', 'aria-label', 'title']) if (e.getAttribute(a)) out.push(e.getAttribute(a));
            return out; }""", DATA)
        for s in texts:
            words = [x.lower() for x in re.findall(r"[A-Za-z']+", s)]
            if len(words) >= 3 and sum(x in STOP for x in words) >= 2 and not re.search(r"[ऀ-ॿ]", s):
                left.append(f"{t}: {s[:400]}")
    if left and os.getenv("U19_DUMP"):
        open(os.getenv("U19_DUMP"), "w", encoding="utf-8").write(chr(10).join(dict.fromkeys(left)))
    r.check(not left, f"no English sentence is left on any screen in Hindi ({len(left)} found)", left[:6])
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U20", "A carer in New Jersey sets up the circle for a parent in Pune: the circle's time zone is asked for, not taken from the first browser, and can be changed")
def u20(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs, tz="America/New_York")
    email = f"u20-{rid()}@scenario.test"
    ui_signup(pg, "Child abroad", email)
    ui_circle(pg, "Mum's medicines", "Mum")
    u = api_user(w, email)
    c = circle_of(u)
    e = u.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="twice daily")
    u.ok(c, "care_schedule_set", dose_id=e["id"], times=["08:00", "20:00"])
    pg.goto(f"{BASE}/#/today")
    pg.reload()
    pg.get_by_test_id("checklist").wait_for(timeout=20000)
    r.check(pg.get_by_test_id("tz-prompt").is_visible(), "the app asks which time zone the parent is in, since this browser is elsewhere")
    r.check("Asia/Kolkata" in pg.get_by_test_id("checklist-zone").inner_text() and "not set yet" in pg.get_by_test_id("checklist-zone").inner_text(),
            "until someone answers, the list says it is on India time and that this is not set", pg.get_by_test_id("checklist-zone").inner_text())
    r.check(u.ok(c, "care_timezone")["set"] is False, "opening Today did not set the circle's time zone to the browser's")
    pg.get_by_test_id("tz-keep").click()
    pg.wait_for_timeout(1500)
    r.check(u.ok(c, "care_timezone") == {"tz": "Asia/Kolkata", "set": True}, "answering 'keep' records India time for the circle")
    r.check(pg.get_by_test_id("tz-prompt").count() == 0, "the question is not asked again")
    pg.goto(f"{BASE}/#/account")
    pg.reload()
    pg.get_by_test_id("circle-timezone").wait_for(timeout=20000)
    pg.get_by_test_id("tz-select").select_option("Asia/Dubai")
    pg.get_by_test_id("tz-save").click()
    pg.wait_for_timeout(1500)
    r.check(u.ok(c, "care_timezone")["tz"] == "Asia/Dubai", "the Account screen can change the circle's time zone")
    r.check(not [x for x in errs if x.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U21", "One tablet of a combination is one row with its name and strength, one tick, one set of times")
def u21(w, b, r):
    errs = []
    ctx, pg = new_page(b, errs=errs)
    email = f"u21-{rid()}@scenario.test"
    ui_signup(pg, "Combo", email)
    ui_circle(pg, "Mum's medicines", "Mum")
    u = api_user(w, email)
    c = circle_of(u)
    ids = [u.ok(c, "care_record", person="mum", drug=d, freq_text="once daily", product="Telma-AM", product_strength="40/5 mg")["id"] for d in ("telmisartan", "amlodipine")]
    pg.goto(f"{BASE}/#/today")
    pg.reload()
    pg.get_by_test_id("unscheduled").wait_for(timeout=20000)
    r.check(pg.get_by_test_id("unscheduled").locator(".item").count() == 1, "the combination is one row to set times for, not two")
    txt = pg.get_by_test_id("unscheduled").inner_text()
    r.check("Telma-AM" in txt and "40/5 mg" in txt, "the row carries the product's name and printed strength", txt)
    pg.get_by_test_id("set-times").click()
    r.check("Telma-AM" in pg.locator("dialog[open]").inner_text(), "the times sheet says 'Times for Telma-AM'", pg.locator("dialog[open]").inner_text()[:80])
    pg.get_by_test_id("save-times").click()
    pg.get_by_test_id("slot").first.wait_for(timeout=20000)
    r.check(pg.get_by_test_id("slot").count() == 1, "one row for the tablet, with both ingredients under it", pg.get_by_test_id("slot").count())
    r.check("telmisartan" in pg.get_by_test_id("slot-ingredients").first.inner_text().lower() and "amlodipine" in pg.get_by_test_id("slot-ingredients").first.inner_text().lower(),
            "the ingredients are named under the tablet")
    pg.get_by_test_id("give-slot").first.click()
    pg.wait_for_timeout(1500)
    r.check(pg.get_by_test_id("slot").first.get_attribute("data-state") == "given", "one tick marks the whole tablet as given")
    got = [x for x in u.ok(c, "care_gives", person="mum")]
    r.check(sorted(g["drug"] for g in got) == ["amlodipine", "telmisartan"], "both ingredients are recorded as given", got)
    r.check(not [e for e in errs if e.startswith("pageerror")], "no errors", errs[:3])
    ctx.close()


@scenario("U22", "A handoff: one carer writes a note about an entry and addresses it to the other, who accepts it; a change to the entry marks the note")
def u22(w, b, r):
    errs = []
    pe, oe = f"u22p-{rid()}@scenario.test", f"u22o-{rid()}@scenario.test"
    ctxp, pp = new_page(b, errs=errs)
    ui_signup(pp, "Pia", pe)
    ui_circle(pp)
    pu = api_user(w, pe)
    c = circle_of(pu)
    ctxo, po = new_page(b, errs=errs)
    ui_signup(po, "Ola", oe)
    expect(po.get_by_text("Set up your first circle")).to_be_visible()
    ou = api_user(w, oe)
    w.join(pu, c, ou)
    e = pu.ok(c, "care_record", person="mum", drug="warfarin", dose_text="5 mg", freq_text="at bedtime")
    ou.ok(c, "care_ack", dose_id=e["id"])                                                       # Ola has acted, so she is a carer in the record
    pp.goto(f"{BASE}/#/circle")
    pp.reload()
    tab(pp, "Circle")
    pp.get_by_test_id("handover").wait_for(timeout=20000)
    pp.get_by_label("Write a note for the next carer").fill("The warfarin dose went down tonight")
    pp.get_by_test_id("handover-about").select_option(value=e["id"])
    pp.get_by_test_id("handover-to").select_option(index=1)
    pp.get_by_test_id("handover-add").click()
    row = pp.get_by_test_id("handover-row").first
    expect(row).to_contain_text("waiting to be accepted", timeout=15000)
    r.check("Warfarin" in row.inner_text(), "the note shows which entry it is about and who it is for", row.inner_text())
    po.goto(f"{BASE}/#/circle")
    po.reload()
    tab(po, "Circle")
    po.get_by_test_id("handover-accept").wait_for(timeout=20000)
    r.check(pp.get_by_test_id("handover-accept").count() == 0, "the sender is not offered an Accept button")
    po.get_by_test_id("handover-accept").click()
    expect(po.get_by_test_id("handover-row").first).to_contain_text("accepted by", timeout=15000)
    r.check(po.get_by_test_id("handover-accept").count() == 0, "after accepting, the button is gone")
    pu.ok(c, "care_record", person="mum", drug="warfarin", dose_text="3 mg", freq_text="at bedtime")        # the entry the note is about changes
    pp.reload()
    tab(pp, "Circle")
    expect(pp.get_by_test_id("handover-row").first).to_contain_text("the entry has changed since", timeout=15000)
    r.check(True, "once the entry changes, the note says so")
    r.check(not [x for x in errs if x.startswith("pageerror")], "no errors in either browser", errs[:3])
    ctxp.close()
    ctxo.close()


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
