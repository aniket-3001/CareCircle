"""Scenarios played in a real browser, the way a person (or a careless one, or a hostile one) would use the app.

  SCENARIO_URL=http://localhost:8099 python scenarios/ui_scenarios.py [prefix]
"""
import os
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


def new_page(browser, width=1280, height=900, errs=None):
    ctx = browser.new_context(viewport={"width": width, "height": height})
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
    return User(w, name, email, j["token"], j["account"]["id"])


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
    api_user(w, email).post("/v1/account/signout-all")
    tab(pg, "History")                                                                                    # this screen asks the server afresh
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
            .filter(e => !e.closest('[hidden]') && e.offsetParent !== null)
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


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
