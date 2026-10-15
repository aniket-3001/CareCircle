"""Drive the real UI in system Chrome (playwright, no browser download) against a live API and assert what each tab shows.
Usage: PYTHONPATH=. python scripts/ui_check.py http://127.0.0.1:8000 ADMIN_KEY [repo_for_code_tab] ; screenshots go to ./ui_shots"""
import json, os, subprocess, sys, urllib.request

from playwright.sync_api import sync_playwright

base, admin = sys.argv[1:3]
repo = sys.argv[3] if len(sys.argv) > 3 else None
here = os.path.dirname(os.path.abspath(__file__))
env = {**os.environ, "PYTHONPATH": os.path.dirname(here)}
subprocess.run([sys.executable, os.path.join(here, "seed_demo.py"), base, admin], check=True, capture_output=True, env=env)
if repo:
    out = subprocess.run([sys.executable, os.path.join(here, "seed_code_demo.py"), base, admin, repo, "acme", "ui-agent"],
                         check=True, capture_output=True, text=True, env=env).stdout
    key = out.strip().splitlines()[-1].split(": ")[1]
else:
    r = urllib.request.Request(base + "/admin/agents", data=json.dumps({"agent": "ui-agent"}).encode(), method="POST",
                               headers={"Authorization": "Bearer " + admin, "content-type": "application/json"})
    key = json.load(urllib.request.urlopen(r))["api_key"]
    r = urllib.request.Request(base + "/admin/grants", data=json.dumps({"agent": "ui-agent", "tenant": "acme"}).encode(), method="POST",
                               headers={"Authorization": "Bearer " + admin, "content-type": "application/json"})
    urllib.request.urlopen(r)
os.makedirs("ui_shots", exist_ok=True)
fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 860})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(base + "/")
    pg.fill("#key", key); pg.click("#connect"); pg.wait_for_timeout(2500)
    check("connected, tenant listed", "acme" in pg.inner_text("#tenant"))
    check("graph drawn", "nodes" in pg.inner_text("#gstat")); pg.screenshot(path="ui_shots/graph.png")
    pg.click('[data-t="recall"]'); pg.fill("#q", "report deadline"); pg.click("#doRecall"); pg.wait_for_timeout(800)
    check("recall shows deadline", "deadline" in pg.inner_text("#recallOut").lower()); pg.screenshot(path="ui_shots/recall.png")
    pg.click('[data-t="skills"]'); pg.wait_for_timeout(800)
    check("skills tab", "send-report" in pg.inner_text("#skillOut"))
    if repo:
        pg.click('[data-t="code"]')
        pg.click('[data-tool="criticality"]'); pg.wait_for_timeout(1200)
        txt = pg.inner_text("#codeOut"); check("criticality shows Cypher + files", "algo.pageRank" in txt and ".py" in txt)
        pg.screenshot(path="ui_shots/code_criticality.png")
        first = json.loads(txt.split("\n")[-1].replace(" ", " ")) if txt.strip().splitlines()[-1].startswith("{") else None
        if first:
            pg.fill("#cpath", first["file"]); pg.click('[data-tool="blast_radius"]'); pg.wait_for_timeout(1200)
            check("blast radius lists dependants", "hops" in pg.inner_text("#codeOut")); pg.screenshot(path="ui_shots/code_blast.png")
            pg.click('[data-tool="who_to_ask"]'); pg.wait_for_timeout(1200)
            check("who to ask lists people", "person" in pg.inner_text("#codeOut"))
        pg.click('[data-tool="failure_domains"]'); pg.wait_for_timeout(1200)
        check("failure domains", "size" in pg.inner_text("#codeOut"))
    check("no JS errors", not errs or print(errs))
    b.close()
sys.exit(1 if fails else 0)
