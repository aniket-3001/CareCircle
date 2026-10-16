"""Browser walk-through of the account features against a server using local (email and password) accounts: sign up, an empty circle, adding a medicine,
the helper, invitations, a second carer seeing the same server-side data, sign-out and sign-in, and deleting the account.
Usage: PORT=8000 python scripts/ui_e2e_accounts.py       (not for a Cognito deployment: that needs a real inbox)"""
import os
import tempfile
import time

from playwright.sync_api import expect, sync_playwright

out = os.environ.get("CC_SHOTS", tempfile.gettempdir())
base = os.environ.get("BASE") or f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/"
stamp = str(int(time.time()))
PW = "playwright-pass1"


def shot(pg, name, **kw):
    pg.screenshot(path=os.path.join(out, name), **kw)


def tab(pg, name):
    pg.locator(".tabbar").get_by_text(name, exact=True).click()


def sign_up(pg, name, email):
    pg.goto(base)
    pg.get_by_test_id("open-signup").click()
    pg.get_by_label("Your name").fill(name)
    pg.get_by_label("Email").fill(email)
    pg.get_by_label("Password", exact=True).fill(PW)
    pg.get_by_test_id("auth").get_by_role("button", name="Create account").click()


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "401" not in m.text else None)

    # ---- a new account starts with nothing: no sample data anywhere
    sign_up(pg, "Priya Rao", f"priya{stamp}@e2e.test")
    expect(pg.get_by_text("Set up your first circle")).to_be_visible(timeout=15000)
    shot(pg, "a1_onboarding.png")
    pg.get_by_label("Circle name").fill("Mum's medicines")
    pg.get_by_label("Person being looked after").fill("Mum")
    pg.get_by_role("button", name="Create").click()
    expect(pg.get_by_text("Nothing on record yet")).to_be_visible(timeout=15000)
    assert "Metformin" not in pg.inner_text("#main")                              # nothing was invented for this account
    shot(pg, "a2_empty_today.png")

    # ---- add by typing; it is saved on the server
    tab(pg, "Add")
    pg.get_by_placeholder("e.g. Clarithromycin").fill("Warfarin 5 mg once daily")
    pg.get_by_role("button", name="Read it").click()
    card = pg.locator("[data-testid=proposal]").first
    expect(card).to_be_visible(timeout=60000)
    card.get_by_role("button", name="Confirm and save").click()
    expect(pg.get_by_text("Warfarin").first).to_be_visible(timeout=15000)

    # ---- the helper answers from the record, refuses to advise, and the chat is on the server
    pg.get_by_test_id("open-assistant").click()
    box = pg.get_by_label("Your question")
    box.fill("What is on record?")
    box.press("Enter")
    expect(pg.get_by_test_id("msg-assistant").last).to_contain_text("Warfarin 5 mg once daily", timeout=20000)
    box.fill("Should she stop the warfarin?")
    box.press("Enter")
    expect(pg.get_by_test_id("msg-assistant").last).to_contain_text("prescriber or pharmacist", timeout=20000)
    shot(pg, "a3_assistant.png")
    pg.reload()                                                                     # a fresh page: only the token is local
    expect(pg.get_by_text("Nothing on record yet")).to_have_count(0)
    pg.get_by_test_id("open-assistant").click()
    expect(pg.get_by_test_id("msg-user").first).to_contain_text("What is on record?", timeout=15000)
    pg.keyboard.press("Escape")

    # ---- invite a second carer
    pg.get_by_test_id("open-account").click()
    expect(pg.get_by_role("heading", name="Priya Rao")).to_be_visible()
    pg.get_by_label("Show details of Mum's medicines").click()
    pg.get_by_role("button", name="Invite a carer").click()
    code = pg.get_by_test_id("invite-code").locator("b").inner_text()
    assert len(code) == 9
    pg.get_by_role("button", name="Link Telegram").click()
    expect(pg.get_by_test_id("tg-code")).to_contain_text("/link ")
    shot(pg, "a4_account.png", full_page=True)

    # ---- the second carer joins and sees the same record, read from the server
    ctx2 = b.new_context(viewport={"width": 1280, "height": 900})
    p2 = ctx2.new_page()
    p2.on("pageerror", lambda e: errs.append(str(e)))
    sign_up(p2, "Omar Khan", f"omar{stamp}@e2e.test")
    expect(p2.get_by_text("Set up your first circle")).to_be_visible(timeout=15000)
    p2.get_by_label("Invitation code").fill(code)
    p2.get_by_role("button", name="Join").click()
    expect(p2.get_by_text("Warfarin").first).to_be_visible(timeout=15000)
    p2.locator(".tabbar").get_by_text("Circle", exact=True).click()
    expect(p2.get_by_text("Who has seen what")).to_be_visible()
    expect(p2.locator(".person", has_text="Omar")).to_contain_text("1")              # Omar has not seen Priya's entry
    expect(p2.get_by_text("Time warp")).to_have_count(0)                              # demo-only tool: not offered in a real circle
    p2.get_by_role("button", name="I have seen this").click()
    expect(p2.locator(".person", has_text="Omar")).to_contain_text("Up to date", timeout=15000)
    shot(p2, "a5_second_carer.png", full_page=True)
    pg.reload()
    pg.locator(".tabbar").get_by_text("Circle", exact=True).click()
    expect(pg.get_by_text("Who has seen what")).to_be_visible()
    expect(pg.locator(".person", has_text="Omar")).to_contain_text("Up to date")      # Priya's screen reads Omar's acknowledgement from the server

    # ---- sign out, sign in again: everything is still there
    pg.get_by_test_id("open-account").click()
    pg.get_by_test_id("top-signout").click()
    pg.get_by_test_id("open-signin").click()
    pg.get_by_label("Email").fill(f"priya{stamp}@e2e.test")
    pg.get_by_label("Password", exact=True).fill(PW)
    pg.get_by_test_id("auth").get_by_role("button", name="Sign in", exact=True).click()
    expect(pg.get_by_text("Warfarin").first).to_be_visible(timeout=15000)
    pg.get_by_test_id("open-account").click()
    pg.get_by_label("Show details of Mum's medicines").click()
    expect(pg.get_by_test_id("members")).to_contain_text("Omar")

    # ---- change password: eye button shows what was typed; the new password works and the old one does not
    card = pg.get_by_test_id("password-card")
    cur = card.get_by_label("Current password")
    assert cur.get_attribute("type") == "password"
    card.get_by_test_id("pw-eye").first.click()
    assert cur.get_attribute("type") == "text"
    cur.fill(PW)
    card.get_by_label("New password").fill(PW + "x2")
    card.get_by_role("button", name="Change password").click()
    expect(pg.get_by_text("Password changed")).to_be_visible(timeout=15000)
    with pg.expect_download(timeout=20000) as dl:                               # everything held for the account, as one file
        pg.get_by_test_id("download-all").click()
    assert dl.value.suggested_filename.startswith("care-circle-my-data-")
    # deleting a circle needs its name typed first (its details are already open)
    pg.get_by_test_id("delete-circle").click()
    expect(pg.get_by_test_id("delete-circle-go")).to_be_disabled()
    pg.locator("dialog[open]").get_by_label("Circle name").fill("Mum's medicines")
    expect(pg.get_by_test_id("delete-circle-go")).to_be_enabled()
    pg.locator("dialog[open] .icon-btn[aria-label=Close]").click()
    pg.get_by_test_id("display").get_by_label("Larger").dispatch_event("click")       # text size is a per-device setting that sticks
    assert pg.evaluate("document.documentElement.dataset.text") == "larger"
    pg.reload()
    assert pg.evaluate("document.documentElement.dataset.text") == "larger"
    pg.get_by_test_id("open-account").click()
    pg.get_by_test_id("display").get_by_label("Normal").dispatch_event("click")
    assert pg.evaluate("document.documentElement.dataset.text") == "normal"
    pg.get_by_test_id("signout-all").click()                                    # signs out every device, this one included
    expect(pg.get_by_test_id("open-signin")).to_be_visible(timeout=15000)
    pg.get_by_test_id("open-signin").click()
    pg.get_by_label("Email").fill(f"priya{stamp}@e2e.test")
    pg.get_by_label("Password", exact=True).fill(PW)
    pg.get_by_test_id("auth").get_by_role("button", name="Sign in", exact=True).click()
    expect(pg.get_by_text("do not match")).to_be_visible(timeout=15000)
    pg.get_by_label("Password", exact=True).fill(PW + "x2")
    pg.get_by_test_id("auth").get_by_role("button", name="Sign in", exact=True).click()
    expect(pg.get_by_text("Warfarin").first).to_be_visible(timeout=15000)
    pg.get_by_test_id("open-account").click()

    # ---- an incomplete email is stopped before anything is sent
    pg.get_by_test_id("top-signout").click()
    pg.get_by_test_id("open-signup").click()
    pg.get_by_label("Email").fill("someone@gmail")
    pg.get_by_label("Password", exact=True).fill(PW)
    pg.get_by_test_id("auth").get_by_role("button", name="Create account").click()
    expect(pg.get_by_text("looks incomplete")).to_be_visible(timeout=10000)
    pg.get_by_label("Email").fill("someone@gmial.com")
    pg.get_by_test_id("auth").get_by_role("button", name="Create account").click()
    expect(pg.get_by_text("Did you mean someone@gmail.com")).to_be_visible(timeout=10000)
    pg.goto(base)
    pg.get_by_test_id("open-signin").click()
    pg.get_by_label("Email").fill(f"priya{stamp}@e2e.test")
    pg.get_by_label("Password", exact=True).fill(PW + "x2")
    pg.get_by_test_id("auth").get_by_role("button", name="Sign in", exact=True).click()
    expect(pg.get_by_text("Warfarin").first).to_be_visible(timeout=15000)
    pg.get_by_test_id("open-account").click()

    # ---- a demo account is a normal account whose circle is demo data (and so has the demo-only tools)
    ctx3 = b.new_context(viewport={"width": 1280, "height": 900})
    p3 = ctx3.new_page()
    p3.goto(base)
    p3.get_by_test_id("demo-ravi").click()
    p3.get_by_test_id("auth").get_by_role("button", name="Sign in", exact=True).click()
    expect(p3.get_by_text("Metformin").first).to_be_visible(timeout=15000)
    p3.locator(".tabbar").get_by_text("Circle", exact=True).click()
    expect(p3.get_by_text("Time warp (demo only)")).to_be_visible()

    # ---- delete the account: it is really gone
    pg.get_by_role("button", name="Delete my account…").click()
    pg.get_by_label("Email").last.fill(f"priya{stamp}@e2e.test")
    pg.get_by_role("button", name="Delete everything").click()
    expect(pg.get_by_test_id("open-signin")).to_be_visible(timeout=15000)
    pg.get_by_test_id("open-signin").click()
    pg.get_by_label("Email").fill(f"priya{stamp}@e2e.test")
    pg.get_by_label("Password", exact=True).fill(PW)
    pg.get_by_test_id("auth").get_by_role("button", name="Sign in", exact=True).click()
    expect(pg.get_by_text("do not match")).to_be_visible(timeout=15000)
    # Omar, now the owner of the shared circle, still has the data
    p2.reload()
    tab(p2, "Today")
    expect(p2.get_by_text("Warfarin").first).to_be_visible(timeout=15000)
    # clean up Omar
    p2.get_by_test_id("open-account").click()
    p2.get_by_role("button", name="Delete my account…").click()
    p2.get_by_label("Email").last.fill(f"omar{stamp}@e2e.test")
    p2.get_by_role("button", name="Delete everything").click()
    expect(p2.get_by_test_id("open-signin")).to_be_visible(timeout=15000)

    assert not errs, errs
    print("accounts e2e ok")
    b.close()
