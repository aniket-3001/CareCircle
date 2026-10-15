"""Download the public reference data Care Circle needs into data/ref (gitignored): DDInter 2.0 CSVs and the FDA CYP table.
DDInter is CC BY-NC-SA 4.0 (non-commercial): fine for this project, state it wherever the data is shown."""
import hashlib, json, pathlib, sys, time, urllib.request

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "ref"
OUT.mkdir(parents=True, exist_ok=True)
DD = "https://ddinter2.scbdd.com/static/media/download/ddinter_downloads_code_{}.csv"
FDA = ("https://www.fda.gov/drugs/drug-interactions-labeling/"
       "drug-development-and-drug-interactions-table-substrates-inhibitors-and-inducers")


def get(url, dest):
    if dest.exists() and dest.stat().st_size > 1000 and (verified(dest) or not MANIFEST.exists() and seal(dest) is None):
        return
    req = urllib.request.Request(url, headers={"User-Agent": "carecircle-research"})
    for attempt in range(5):                       # the portals are slow and sometimes time out
        try:
            data = urllib.request.urlopen(req, timeout=60).read()
            break
        except OSError as e:
            print("retry", dest.name, type(e).__name__, flush=True)
            time.sleep(3 * (attempt + 1))
    else:
        sys.exit(f"{url}: giving up after 5 attempts")
    if len(data) < 1000 or data.lstrip()[:1] == b"<" and dest.suffix == ".csv":   # portals answer 200 with an HTML error page
        sys.exit(f"{url}: not the file we expected ({len(data)} bytes)")
    if dest.suffix == ".csv" and not data.lstrip().lower().startswith(b"ddinterid_a"):   # right kind of file: the header names the columns we read
        sys.exit(f"{url}: the header is not a DDInter table")
    dest.write_bytes(data)
    seal(dest)
    print("ok", dest.name, len(data))


MANIFEST = OUT / "MANIFEST.json"


def seal(path):
    """Record each file's SHA-256 so a later run can tell the file on disk is the one that was checked."""
    m = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    m[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size, "fetched": int(time.time())}
    MANIFEST.write_text(json.dumps(m, indent=1, sort_keys=True))


def verified(path):
    """True if the file on disk matches the manifest (a half-written or edited file is fetched again)."""
    m = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    return path.name in m and hashlib.sha256(path.read_bytes()).hexdigest() == m[path.name]["sha256"]


for c in "ABDGHJLMNPRSV":
    get(DD.format(c), OUT / f"ddinter_{c}.csv")
try:
    get(FDA, OUT / "fda_cyp.html")
except SystemExit as e:                            # the FDA site sometimes blocks scripted requests: use the bundled copy (US government work)
    snap = pathlib.Path(__file__).resolve().parent.parent / "carecircle" / "snapshot" / "fda_cyp.html"
    print("FDA download failed, using bundled snapshot:", e)
    (OUT / "fda_cyp.html").write_bytes(snap.read_bytes())
