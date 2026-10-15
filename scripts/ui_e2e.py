"""End-to-end browser check of the web app (needs the server running and Chrome).
Usage: PORT=8000 python scripts/ui_e2e.py      (set CC_SHOTS=<dir> to keep screenshots)"""
import os
import tempfile

from playwright.sync_api import sync_playwright

out = os.environ.get("CC_SHOTS", tempfile.gettempdir())
base = f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/"


def shot(pg, name, **kw):
    pg.screenshot(path=os.path.join(out, name), **kw)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    pg = b.new_page(viewport={"width": 420, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(base)
    pg.click("#start")
    pg.wait_for_selector("text=On record for")
    shot(pg, "1_today.png")
    pg.click("[data-t=add]")
    pg.click("#sample")
    pg.wait_for_selector("#props .card", timeout=90000)
    assert "quote verified" in pg.inner_text("#props")
    shot(pg, "2_add.png")
    pg.click(".ok-btn")
    pg.wait_for_timeout(1500)
    pg.click("[data-t=today]")
    pg.wait_for_selector("text=Flags, with sources")
    assert "major" in pg.inner_text("#app")
    shot(pg, "3_flags.png", full_page=True)
    pg.click("[data-t=circle]")
    pg.wait_for_selector("text=Who is out of date")
    pg.evaluate("document.querySelector('#warp').value=13; document.querySelector('#warp').dispatchEvent(new Event('change'))")
    pg.wait_for_selector("text=sent once")
    shot(pg, "4_circle.png", full_page=True)
    pg.click("[data-t=graph]")
    pg.wait_for_selector("svg.graph")
    shot(pg, "5_graph.png", full_page=True)
    pg.click("[data-t=history]")
    pg.wait_for_selector("text=What did we know then")
    pg.click("[data-t=doses]")
    pg.wait_for_selector("#gg")
    pg.click("#gg")
    pg.wait_for_timeout(800)
    pg.click("#gg")
    pg.wait_for_selector("text=Already recorded")
    assert not errs, errs
    print("ui e2e ok")
    b.close()
