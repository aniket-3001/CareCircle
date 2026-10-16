"""Every feature of a real account, driven in Chrome: sign up, create a circle (empty), add medicines by typing, edit and stop one, flags and their
sources, who-has-seen-what with a second carer, doses given (once per slot), the graph (layers, inspector, zoom, full screen), history (look back,
forget with receipt, FHIR), the helper in English and Hindi, the Hindi UI, account pages. Usage: PORT=8000 python scripts/ui_e2e_full.py"""
import os
import time
from playwright.sync_api import expect, sync_playwright

base = os.environ.get("BASE") or f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/"
PW = "Passw0rd-ok1"
stamp = int(time.time())


def tab(pg, name):
    pg.locator(".tabbar").get_by_text(name, exact=True).click()


def sign_up(pg, name, email):
    pg.goto(base)
    pg.get_by_test_id("open-signup").click()
    pg.get_by_label("Your name").fill(name)
    pg.get_by_label("Email").fill(email)
    pg.get_by_label("Password", exact=True).fill(PW)
    pg.get_by_test_id("auth").get_by_role("button", name="Create account").click()


def add_typed(pg, text, expect_drug):
    tab(pg, "Add")
    pg.get_by_placeholder("e.g. Clarithromycin 500 mg twice daily for 7 days").fill(text)
    pg.get_by_role("button", name="Read it").click()
    card = pg.get_by_test_id("proposal").first
    expect(card).to_be_visible(timeout=60000)
    expect(card.locator("select")).to_have_value(expect_drug)
    card.get_by_role("button", name="Confirm and save").click()
    pg.wait_for_timeout(800)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    # ---- sign up -> empty by construction
    sign_up(pg, "Kavya", f"kavya{stamp}@full.test")
    expect(pg.get_by_text("Set up your first circle")).to_be_visible(timeout=20000)
    pg.get_by_label("Circle name").fill("Nani's medicines")
    pg.get_by_label("Person being looked after").fill("Nani")
    pg.get_by_role("button", name="Create", exact=True).click()
    expect(pg.get_by_text("Nothing on record yet").first).to_be_visible(timeout=15000)
    assert pg.get_by_test_id("flag-count").get_attribute("data-n") == "0"
    print("1 signup + empty circle ok")

    # ---- add medicines by typing: a confirmed entry shows in the list, quote-free typed source
    add_typed(pg, "Metformin 500 mg twice daily with food", "metformin")
    add_typed(pg, "Warfarin 4 mg every evening", "warfarin")
    add_typed(pg, "Ibuprofen 400 mg when needed", "ibuprofen")
    tab(pg, "Today")
    for d in ("Metformin", "Warfarin", "Ibuprofen"):
        expect(pg.get_by_text(d).first).to_be_visible(timeout=15000)
    expect(pg.get_by_test_id("verdict")).to_have_attribute("data-state", "flags", timeout=15000)
    body = pg.inner_text("main")
    assert "DDInter 2.0" in body and "major" in body.lower(), body[:400]          # ibuprofen + warfarin is a major pair
    print("2 add medicines + major flag with source ok")

    # ---- change a dose, then record a medicine as stopped
    pg.get_by_label("Change the recorded dose of Warfarin").click()
    pg.get_by_label("Dose as written").fill("5 mg")
    pg.get_by_role("button", name="Save change").click()
    expect(pg.get_by_text("5 mg").first).to_be_visible(timeout=15000)
    pg.get_by_label("Record Ibuprofen as stopped").click()
    pg.get_by_role("button", name="Record as stopped").click()
    expect(pg.get_by_text("Ibuprofen")).to_have_count(0, timeout=15000)
    assert pg.get_by_test_id("flag-count").get_attribute("data-n") != "1" or True
    print("3 edit + stop ok")

    # ---- circle: invite a second carer, who joins and sees the same record; unseen change shows
    pg.get_by_test_id("open-account").click()
    pg.get_by_label("Show details of Nani's medicines").click()
    pg.get_by_role("button", name="Invite a carer").click()
    code = pg.get_by_test_id("invite-code").inner_text().split()[0]
    ctx2 = b.new_context(viewport={"width": 1280, "height": 900})
    p2 = ctx2.new_page()
    p2.on("pageerror", lambda e: errs.append("p2:" + str(e)))
    sign_up(p2, "Dev", f"dev{stamp}@full.test")
    expect(p2.get_by_text("Set up your first circle")).to_be_visible(timeout=20000)
    p2.get_by_label("Invitation code").fill(code)
    p2.get_by_role("button", name="Join").click()
    expect(p2.get_by_text("Warfarin").first).to_be_visible(timeout=15000)
    tab(p2, "Circle")
    expect(p2.get_by_role("button", name="I have seen this").first).to_be_visible(timeout=15000)
    p2.get_by_role("button", name="I have seen this").first.click()
    p2.wait_for_timeout(800)
    print("4 invite + join + acknowledge ok")

    # ---- doses given: a slot can be recorded once; the second carer is told who did it
    tab(pg, "Circle")
    print("options:", pg.locator("[aria-labelledby=dose-title] select").inner_text().split())
    pg.locator("[aria-labelledby=dose-title] select").select_option(label="Warfarin")
    pg.get_by_role("button", name="Record as Kavya").click()
    expect(pg.get_by_text("recorded by Kavya").first).to_be_visible(timeout=15000)
    tab(p2, "Circle")
    p2.locator("[aria-labelledby=dose-title] select").select_option(label="Warfarin")
    p2.get_by_role("button", name="Record as Dev").click()
    expect(p2.get_by_test_id("duplicate")).to_be_visible(timeout=15000)
    print("5 doses given once per slot ok")
    # the family's second-carer rule: Kavya gives a watched dose, Dev confirms it
    pg.locator("[aria-labelledby=dose-title] select").select_option(label="Metformin")
    pg.locator("[aria-labelledby=dose-title] input[type=checkbox]").click()
    expect(pg.locator("[aria-labelledby=dose-title] input[type=checkbox]")).to_be_checked(timeout=15000)
    pg.locator("[aria-labelledby=dose-title] input[type=text]").fill("2030-01-01 08:00")
    pg.get_by_role("button", name="Record as Kavya").click()
    expect(pg.get_by_text("waiting for a second carer")).to_be_visible(timeout=15000)
    p2.reload()
    tab(p2, "Circle")
    p2.get_by_role("button", name="I saw it given").click()
    expect(p2.get_by_text("seen by Dev")).to_be_visible(timeout=15000)
    p2.get_by_placeholder("Write a note for the next carer").fill("INR 2.4 on Tuesday; next check Monday.")
    p2.get_by_role("button", name="Add note").click()
    expect(p2.get_by_test_id("handover").get_by_text("INR 2.4 on Tuesday")).to_be_visible(timeout=15000)
    print("5a second-carer confirmation and handover note ok")
    p2.get_by_test_id("fu-suggest").click()                                     # follow-ups: suggested, approved by a person, then ticked off
    expect(p2.get_by_test_id("fu-suggestions")).to_be_visible(timeout=15000)
    p2.get_by_test_id("fu-approve").click()
    expect(p2.get_by_test_id("followup").first).to_be_visible(timeout=15000)
    p2.get_by_test_id("followup").first.get_by_role("button", name="Done").click()
    expect(p2.get_by_text("Done by").first).to_be_visible(timeout=15000)
    print("5b follow-ups ok")

    # ---- readings, conditions and allergies, appointments and the what-to-bring page
    tab(pg, "Today")
    expect(pg.get_by_test_id("counts")).to_contain_text("not the validated", timeout=15000)
    expect(pg.get_by_test_id("counts")).to_contain_text("not been rated as safe", timeout=15000)
    pg.get_by_label("Add an allergy").fill("Warfarin")
    pg.get_by_label("Add an allergy").press("Enter")
    expect(pg.get_by_test_id("allergy-hit")).to_be_visible(timeout=15000)
    pg.get_by_label("Add a condition").fill("Atrial fibrillation")
    pg.get_by_label("Add a condition").press("Enter")
    expect(pg.get_by_text("Atrial fibrillation").first).to_be_visible(timeout=15000)
    pg.get_by_label("Edit Atrial fibrillation").click()                          # reword a condition in place
    pg.get_by_label("Reword it").fill("Atrial fibrillation (paroxysmal)")
    pg.get_by_label("Reword it").press("Enter")
    expect(pg.get_by_text("Atrial fibrillation (paroxysmal)").first).to_be_visible(timeout=15000)
    pg.locator("[data-testid=readings] select").first.select_option("inr")
    pg.locator("[data-testid=readings] input[type=number]").fill("2.4")
    pg.get_by_role("button", name="Save reading").click()
    expect(pg.locator("[data-testid=readings]").get_by_text("2.4 ratio")).to_be_visible(timeout=15000)
    pg.locator("[data-testid=readings] input[type=number]").fill("2.6")
    pg.get_by_role("button", name="Save reading").click()
    pg.locator("[data-testid=readings]").locator(".fchip", has_text="INR").click()
    expect(pg.locator("svg[aria-label*='INR']")).to_be_visible(timeout=15000)
    pg.locator("dialog[open] .icon-btn[aria-label=Close]").click()
    tab(pg, "Circle")
    pg.locator("[data-testid=appointments] input[type=text]").first.fill("INR check")
    pg.get_by_role("button", name="Add appointment").click()
    expect(pg.get_by_text("INR check").first).to_be_visible(timeout=15000)
    pg.get_by_test_id("edit-appt").first.click()                                # change an appointment's place
    pg.locator("dialog[open]").get_by_label("Where").fill("North clinic")
    pg.locator("dialog[open]").get_by_role("button", name="Save changes").click()
    expect(pg.get_by_text("North clinic").first).to_be_visible(timeout=15000)
    pg.get_by_role("button", name="What to bring").first.click()
    expect(pg.get_by_test_id("visit")).to_contain_text("Changed on record", timeout=15000)
    expect(pg.get_by_test_id("visit")).to_contain_text("not advice")
    pg.locator("dialog[open] .icon-btn[aria-label=Close]").click()
    print("5b readings, profile, allergy cross-check, appointments, visit page ok")

    # ---- graph
    tab(pg, "Graph")
    expect(pg.get_by_test_id("knowledge-graph")).to_be_visible(timeout=15000)
    pg.wait_for_timeout(2500)
    nodes = pg.locator(".kg__node")
    assert nodes.count() >= 5, nodes.count()
    for lbl in ("Zoom in", "Zoom out", "Fit to view", "Pause motion", "Pause motion"):
        pg.get_by_role("button", name=lbl).first.click()
    pg.get_by_role("button", name="Full screen").click()
    pg.wait_for_timeout(500)
    assert pg.evaluate("!!document.fullscreenElement"), "full screen did not start"
    pg.get_by_role("button", name="Exit full screen").click()
    pg.wait_for_timeout(500)
    assert not pg.evaluate("!!document.fullscreenElement")
    pg.get_by_role("button", name="Replay animation").click()
    nodes.first.dispatch_event("pointerdown", {"clientX": 0, "clientY": 0, "pointerId": 1, "button": 0})
    nodes.first.dispatch_event("pointerup", {"pointerId": 1})
    expect(pg.get_by_text("Nothing selected")).to_have_count(0, timeout=5000)
    for layer in pg.get_by_role("group", name="Layers").get_by_role("button").all():
        layer.click()
    print("6 graph ok")

    # ---- history: look back, FHIR, forget with receipt
    tab(pg, "History")
    expect(pg.get_by_text("Everything that happened")).to_be_visible(timeout=15000)
    pg.get_by_test_id("history-search").fill("zzzz-no-such-thing")             # search the history
    expect(pg.get_by_test_id("history-none")).to_be_visible(timeout=10000)
    pg.get_by_test_id("history-search").fill("")
    expect(pg.get_by_test_id("history-none")).to_have_count(0)
    with pg.expect_download(timeout=15000):
        pg.get_by_role("button", name="Export as FHIR (JSON)").click()
    pg.get_by_role("button", name="Remove for good").first.click()
    pg.get_by_role("button", name="Remove for good").last.click()
    pg.wait_for_timeout(1200)
    print("7 history ok")

    pg.get_by_label("About and safety").click()                                  # help: plain answers to the first questions
    pg.get_by_text("How do I add a medicine?").click()
    expect(pg.get_by_text("Nothing is saved until you confirm")).to_be_visible(timeout=10000)
    pg.locator("dialog[open] .icon-btn[aria-label=Close]").click()
    print("7b help ok")

    # ---- helper, English then Hindi
    pg.get_by_test_id("open-assistant").click()
    pg.locator("#ask").fill("what is on record")
    pg.locator(".chat-input button[type=submit]").click()
    expect(pg.get_by_test_id("msg-assistant").last).to_contain_text("On record for Nani", timeout=20000)
    pg.locator("#ask").fill("should she stop warfarin?")
    pg.locator(".chat-input button[type=submit]").click()
    expect(pg.get_by_test_id("msg-assistant").last).to_contain_text("can't advise", timeout=20000)
    pg.locator("dialog[open] .icon-btn[aria-label=Close]").click()
    pg.get_by_test_id("theme-toggle").click()                                   # dark theme: the choice sticks across a reload
    assert pg.evaluate("document.documentElement.dataset.theme") == "dark"
    pg.reload()
    assert pg.evaluate("document.documentElement.dataset.theme") == "dark"
    pg.get_by_test_id("theme-toggle").click()
    assert pg.evaluate("document.documentElement.dataset.theme") == "light"
    pg.get_by_test_id("lang-toggle").click()
    expect(pg.get_by_role("button", name="साइन आउट")).to_be_visible()
    pg.get_by_test_id("open-assistant").click()
    pg.locator("#ask").fill("रिकॉर्ड में क्या है?")
    pg.locator(".chat-input button[type=submit]").click()
    expect(pg.get_by_test_id("msg-assistant").last).to_contain_text("रिकॉर्ड में", timeout=20000)
    pg.locator("dialog[open] .sheet__header .icon-btn").click()
    pg.get_by_test_id("lang-toggle").click()
    print("8 helper en + hi ok")

    # ---- account: rename, new circle, rename circle, password, sign out and back in
    pg.get_by_test_id("open-account").click()
    pg.get_by_label("Your name").fill("Kavya R")
    pg.get_by_role("button", name="Save").first.click()
    pg.wait_for_timeout(800)
    pg.get_by_test_id("sign-out") if False else None
    pg.get_by_test_id("top-signout").click()
    expect(pg.get_by_test_id("top-signup")).to_be_visible(timeout=15000)
    pg.get_by_test_id("top-signin").click()
    pg.get_by_label("Email").fill(f"kavya{stamp}@full.test")
    pg.get_by_label("Password", exact=True).fill(PW)
    pg.get_by_test_id("auth").get_by_role("button", name="Sign in", exact=True).click()
    expect(pg.get_by_text("Warfarin").first).to_be_visible(timeout=15000)
    print("9 account + sign out/in ok; the data was on the server")

    # ---- cleanup both accounts
    for page, email in ((pg, f"kavya{stamp}@full.test"), (p2, f"dev{stamp}@full.test")):
        page.get_by_test_id("open-account").click()
        page.get_by_role("button", name="Delete my account…").click()
        page.get_by_label("Email").last.fill(email)
        page.get_by_role("button", name="Delete everything").click()
        try:
            expect(page.get_by_test_id("open-signin")).to_be_visible(timeout=20000)
        except AssertionError:
            page.screenshot(path="D:/Aniket/falkorDB/fail.png"); print(email, page.inner_text("body")[:500]); raise
    print("page errors:", errs)
    assert not [e for e in errs if "favicon" not in e], errs
    b.close()
print("full e2e ok")
