"""Take the desktop screenshots used in the README, from a running server with the demo on.

  PORT=8099 python scripts/take_screenshots.py          (writes docs/img/ui-*.png)

It opens the one-click demo circle, adds the sample label so the circle has a real flag, and captures each screen at laptop width (1440 px) in the light theme.
The floating controls (the round buttons and the bottom tab bar) are hidden while capturing, because in a still picture they sit on top of the content; every
frame is cropped to the part that shows one idea. Everything shown is the synthetic demo data. Needs Playwright with system Chrome, like the other browser scripts.
"""
import os
import pathlib

from playwright.sync_api import expect, sync_playwright

PORT = os.environ.get("PORT", "8099")
BASE = os.environ.get("BASE", f"http://localhost:{PORT}")
OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "img"
W = 1440


def tab(pg, name):
    pg.evaluate("n => { window.location.hash = '#/' + n.toLowerCase(); }", name)           # the tab bar is hidden, so go by the address the app already supports
    pg.wait_for_timeout(1500)


def shot(pg, name, height, top=0):
    """The page from `top` for `height` px at full width, taken as one image (the page is scrolled by the screenshot itself, so nothing is cut)."""
    pg.wait_for_timeout(600)
    pg.screenshot(path=str(OUT / name), full_page=True, clip={"x": 0, "y": top, "width": W, "height": height})
    print("wrote", name)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    ctx = b.new_context(viewport={"width": W, "height": 1000}, device_scale_factor=1, color_scheme="light")
    pg = ctx.new_page()
    pg.goto(BASE)
    pg.evaluate("localStorage.clear()")
    pg.goto(BASE)
    pg.add_style_tag(content=".tabbar, .fabs { display: none !important; }")
    shot(pg, "ui-welcome.png", 900)
    pg.click("[data-testid=start-demo]")
    expect(pg.locator("[data-testid=verdict]")).to_be_visible(timeout=60000)
    pg.add_style_tag(content=".tabbar, .fabs { display: none !important; }")
    pg.wait_for_timeout(1500)

    # Add: a label is read by OCR, the exact line it came from is quoted, and nothing is saved until a person confirms
    tab(pg, "Add")
    pg.get_by_role("button", name="Sample label").click()
    card = pg.locator("[data-testid=proposal]").first
    expect(card).to_be_visible(timeout=90000)
    expect(card).to_contain_text("quote verified")
    shot(pg, "ui-add.png", 960)
    pg.get_by_role("button", name="Confirm and save").first.click()
    pg.wait_for_timeout(2500)

    # Today: the day's doses, then the verdict with the flag; and every flag with its source
    tab(pg, "Today")
    expect(pg.locator("[data-testid=verdict]")).to_be_visible()
    pg.wait_for_timeout(1500)
    shot(pg, "ui-today.png", 1280)
    flags = pg.locator("section", has=pg.get_by_text("Flags, with their sources")).first
    box = flags.bounding_box()
    shot(pg, "ui-flags.png", 672, top=int(box["y"]) - 16)

    # Circle: who has seen what
    tab(pg, "Circle")
    shot(pg, "ui-circle.png", 690)

    # Graph: the circle as a graph, the clarithromycin entry explained in words
    tab(pg, "Graph")
    pg.wait_for_selector(".kg__node", timeout=30000)
    pg.wait_for_timeout(3500)
    shot(pg, "ui-graph.png", 1000)                                                            # the whole circle first, nothing selected
    node = pg.locator(".kg__node[aria-label*='clarithromycin' i]").first
    if node.count():
        node.dispatch_event("pointerdown", {"clientX": 0, "clientY": 0, "pointerId": 1, "button": 0})
        node.dispatch_event("pointerup", {"clientX": 0, "clientY": 0, "pointerId": 1, "button": 0})
        pg.wait_for_timeout(1500)
    shot(pg, "ui-graph-explain.png", 1000)

    # History: the timeline with the line each entry was read from
    tab(pg, "History")
    shot(pg, "ui-history.png", 1000)
    b.close()
