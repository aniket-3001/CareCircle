"""End-to-end browser check of the web app (needs the server running and Chrome).
Usage: PORT=8000 python scripts/ui_e2e.py      (or BASE=https://host/ ; set CC_SHOTS=<dir> to keep screenshots)
Walks the demo story and asserts what a person would see at each step."""
import os
import tempfile

from playwright.sync_api import expect, sync_playwright

out = os.environ.get("CC_SHOTS", tempfile.gettempdir())
base = os.environ.get("BASE") or f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/"


def shot(pg, name, **kw):
    pg.screenshot(path=os.path.join(out, name), **kw)


def tab(pg, name):
    pg.locator(".tabbar").get_by_text(name, exact=True).click()


def click_node(pg, label):
    n = pg.locator(f".kg__node[aria-label*='{label}']").first
    n.dispatch_event("pointerdown", {"clientX": 0, "clientY": 0, "pointerId": 1, "button": 0})
    n.dispatch_event("pointerup", {"pointerId": 1})


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    # welcome -> demo circle
    pg.goto(base)
    pg.click("[data-testid=start-demo]")
    expect(pg.locator("[data-testid=verdict]")).to_be_visible()
    assert "Clarithromycin" not in pg.inner_text("#main")                                   # the baseline regimen does not include it yet
    shot(pg, "1_today.png")

    # a photo is read, quoted and verified; saving needs a click
    tab(pg, "Add")
    pg.get_by_role("button", name="Sample label").click()
    card = pg.locator("[data-testid=proposal]").first
    expect(card).to_be_visible(timeout=90000)
    expect(card).to_contain_text("quote verified")
    expect(card.locator("select")).to_have_value("clarithromycin")
    expect(card.locator("input").nth(1)).to_have_value("500 mg")
    shot(pg, "2_add.png")
    card.get_by_role("button", name="Confirm and save").click()

    # the major flag appears with its source
    expect(pg.locator("[data-testid=flag-count]")).to_be_visible(timeout=20000)
    assert pg.locator("[data-testid=verdict]").get_attribute("data-state") == "flags"
    body = pg.inner_text("#main")
    assert "Atorvastatin + Clarithromycin" in body and "DDInter 2.0" in body and "enzyme path" in body
    shot(pg, "3_flags.png", full_page=True)

    # knowledge graph: nodes drawn, a click opens plain-language metadata
    tab(pg, "Graph")
    pg.wait_for_selector("[data-testid=knowledge-graph] .kg__node")
    assert pg.locator(".kg__node").count() >= 10
    pg.wait_for_timeout(2500)
    click_node(pg, "current entry: Clarithromycin 500 mg")
    insp = pg.locator("[data-testid=inspector]")
    expect(insp).to_contain_text("read from a photo")
    expect(insp).to_contain_text("Line it was read from")
    expect(insp).to_contain_text("Acknowledged by")
    click_node(pg, "medicine: Clarithromycin")
    expect(insp).to_contain_text("Interaction pairs in the reference data")
    shot(pg, "4_graph.png")
    pg.locator(".kg__hit").first.dispatch_event("click")              # a line can be inspected too
    expect(insp).to_contain_text("Ends of this line")
    pg.get_by_label("Pause motion").click()
    pg.get_by_text("Replay animation").click()

    # the graph algorithms, asked of this circle's own graph (computed by FalkorDB on the server, Cypher shown)
    expect(pg.locator("[data-testid=ag-influence] .item").first).to_be_visible(timeout=15000)
    expect(pg.locator("[data-testid=ag-influence]")).to_contain_text("Person")
    expect(pg.locator("[data-testid=ag-groups] .item").first).to_contain_text("Dose")
    expect(pg.locator("[data-testid=ask-graph]")).to_contain_text("algo.WCC")
    pg.get_by_label("Bridges").check(force=True)                                    # exact betweenness, computed by the server
    expect(pg.locator("[data-testid=ag-computed]")).to_be_visible(timeout=15000)
    expect(pg.locator("[data-testid=ag-influence] .item").first).to_be_visible()
    pg.get_by_label("PageRank").check(force=True)
    expect(pg.locator("[data-testid=ag-find]")).to_be_disabled()
    pg.select_option("[data-testid=ag-from]", index=1)
    pg.select_option("[data-testid=ag-to]", index=2)
    pg.click("[data-testid=ag-find]")
    expect(pg.locator("[data-testid=ag-result], [data-testid=ag-none]").first).to_be_visible(timeout=15000)

    # circle: who has not seen the change; time warp shows a reminder
    tab(pg, "Circle")
    expect(pg.get_by_text("Who has seen what")).to_be_visible()
    pg.locator(".seg label", has_text="+13 h").click()
    expect(pg.get_by_text("is not yet acknowledged").first).to_be_visible(timeout=15000)
    shot(pg, "5_circle.png", full_page=True)
    pg.locator(".seg label", has_text="Now").click()

    # a dose slot can be recorded once, by whoever gets there first
    pg.get_by_role("button", name="Record as Ravi").click()
    expect(pg.get_by_text("Nothing recorded yet.")).to_have_count(0, timeout=10000)
    pg.locator(".actor", has_text="Meena").click()
    pg.get_by_role("button", name="Record as Meena").click()
    expect(pg.locator("[data-testid=duplicate]")).to_contain_text("Already recorded by Ravi")

    # history: sentences, FHIR export, forgetting with a receipt
    tab(pg, "History")
    expect(pg.get_by_text("recorded Clarithromycin 500 mg twice daily, read from a photo").first).to_be_visible()
    with pg.expect_download() as dl:
        pg.get_by_role("button", name="Export as FHIR (JSON)").click()
    assert dl.value.suggested_filename.endswith("-fhir.json")
    pg.get_by_role("button", name="Remove for good").first.click()
    pg.get_by_role("dialog").get_by_role("button", name="Remove for good").click()
    expect(pg.get_by_text("rcpt_", exact=False).first).to_be_visible(timeout=15000)
    shot(pg, "6_history.png", full_page=True)

    # small screen, dark mode: still usable
    m = b.new_context(viewport={"width": 390, "height": 800}, color_scheme="dark").new_page()
    m.goto(base)
    m.click("[data-testid=start-demo]")
    expect(m.locator("[data-testid=verdict]")).to_be_visible()
    tab(m, "Graph")
    m.wait_for_selector(".kg__node")
    click_node(m, "medicine: Metformin")
    expect(m.get_by_role("dialog")).to_be_visible()
    shot(m, "7_mobile_sheet.png")

    assert not errs, errs
    print("ui e2e ok")
    b.close()
