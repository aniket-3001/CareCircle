"""Live public sources, used for lookups only and always shown with their source:

  RxNorm (US National Library of Medicine, rxnav.nlm.nih.gov)  brand or misspelt name -> the ingredient, with an RxCUI identifier
  openFDA drug labels (api.fda.gov)                            the official label's own words for a medicine (boxed warning, indications)

Both are free and need no key. Every call has a short timeout, is cached for a day, and fails soft: if a service is down the app simply does
without it (the bundled DDInter table and aliases still work). Nothing is ever sent except the medicine name being looked up: no person, no
circle, no account. Switch off with CC_EXTERNAL=0 (tests do)."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Optional

TIMEOUT = 5
TTL = 24 * 3600
_cache: dict[str, tuple[float, object]] = {}
RX = "https://rxnav.nlm.nih.gov/REST"
FDA = "https://api.fda.gov/drug/label.json"


def enabled() -> bool:
    return os.getenv("CC_EXTERNAL", "1") != "0"


_store = None   # the reference graph, opened lazily: lookups are cached there so they survive a restart and are shared by every worker


def _ref():
    global _store
    if _store is None:
        from falkordb import FalkorDB
        from .reference import REF_GRAPH
        _store = FalkorDB(host=os.getenv("FALKORDB_HOST", "localhost"), port=int(os.getenv("FALKORDB_PORT", "6379"))).select_graph(REF_GRAPH)
    return _store


def _stored(url: str) -> Optional[dict]:
    """A cached public answer (name-only lookups, never personal data) from the reference graph, if still fresh."""
    if os.getenv("CC_EXTERNAL_CACHE", "1") == "0":
        return None
    try:
        rows = _ref().ro_query("MATCH (c:Cached {url:$u}) WHERE c.at > $t RETURN c.body", {"u": url, "t": int((time.time() - TTL) * 1000)}).result_set
        return json.loads(rows[0][0]) if rows else None
    except Exception:
        return None


def _keep(url: str, data: dict) -> None:
    if os.getenv("CC_EXTERNAL_CACHE", "1") == "0" or len(json.dumps(data)) > 200_000:
        return
    try:
        _ref().query("MERGE (c:Cached {url:$u}) SET c.at=$t, c.body=$b", {"u": url, "t": int(time.time() * 1000), "b": json.dumps(data)})
    except Exception:
        pass


def _get(url: str) -> Optional[dict]:
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]  # type: ignore[return-value]
    saved = _stored(url)
    if saved is not None:
        _cache[url] = (time.time(), saved)
        return saved
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CareCircle/1.0 (hackathon; read-only lookups)"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.load(r)
    except Exception:
        return None
    _cache[url] = (time.time(), data)
    _keep(url, data)
    return data


def rxnorm_ingredients(term: str) -> list[dict]:
    """'Tylenol 500', 'warfrin', 'Augmentin' -> every active ingredient RxNorm links the term to, e.g. [{"name": "amoxicillin", "rxcui": "723"},
    {"name": "clavulanate", "rxcui": "48203"}]. RxNorm only suggests: the caller keeps just names that exist in the reference graph, and a person confirms."""
    term = " ".join((term or "").split())[:80]
    if not enabled() or len(term) < 3:
        return []
    q = urllib.parse.quote(term)
    d = _get(f"{RX}/approximateTerm.json?term={q}&maxEntries=4")
    out: dict[str, dict] = {}
    for c in ((d or {}).get("approximateGroup") or {}).get("candidate") or []:
        rxcui = c.get("rxcui")
        if not rxcui or float(c.get("score", 0)) < 8:
            continue
        rel = _get(f"{RX}/rxcui/{rxcui}/related.json?tty=IN")
        for g in ((rel or {}).get("relatedGroup") or {}).get("conceptGroup") or []:
            for p in g.get("conceptProperties") or []:
                out.setdefault(p["name"].lower(), {"name": p["name"].lower(), "rxcui": p["rxcui"], "matched": c.get("name") or term, "source": "RxNorm (NLM)"})
        if out:
            break
    return list(out.values())


def _clean(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"^(WARNING|BOXED WARNING|INDICATIONS? (AND|&) USAGE|1 INDICATIONS? (AND|&) USAGE)[:\s-]*", "", text, flags=re.I)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def openfda_label(generic: str) -> Optional[dict]:
    """The official FDA label's own words for a medicine, verbatim and shortened: {boxed_warning, indications, effective, set_id, url, source}."""
    generic = " ".join((generic or "").split())[:60].lower()
    if not enabled() or len(generic) < 3 or '"' in generic:
        return None
    search = urllib.parse.quote(f'openfda.generic_name:"{generic}"')
    d = _get(f"{FDA}?search={search}&limit=1")
    rows = (d or {}).get("results") or []
    if not rows:
        return None
    r = rows[0]
    first = lambda k: (r.get(k) or [""])[0]  # noqa: E731
    sid = (r.get("openfda") or {}).get("spl_set_id") or [r.get("set_id", "")]
    return {
        "drug": generic,
        "boxed_warning": _clean(first("boxed_warning"), 700),
        "indications": _clean(first("indications_and_usage"), 500),
        "effective": r.get("effective_time", ""),
        "brand": ((r.get("openfda") or {}).get("brand_name") or [""])[0],
        "url": f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={sid[0]}" if sid and sid[0] else "https://open.fda.gov/",
        "source": "openFDA drug label (public data; not validated for medical decisions)",
    }


def openfda_recalls(generic: str, limit: int = 2) -> list[dict]:
    """Ongoing US drug recalls listed for products containing `generic` (openFDA enforcement reports), newest first. A recall is about specific
    products and lots: it is shown as published, for a person to check against the pack at home, never as 'this applies to you'."""
    generic = " ".join((generic or "").split())[:60].lower()
    if not enabled() or len(generic) < 3 or '"' in generic:
        return []
    search = urllib.parse.quote(f'openfda.generic_name:"{generic}" AND status:"Ongoing"')
    d = _get(f"https://api.fda.gov/drug/enforcement.json?search={search}&sort=report_date:desc&limit={int(limit)}")
    out = []
    for r in (d or {}).get("results") or []:
        out.append({"drug": generic, "number": r.get("recall_number", ""), "class": r.get("classification", ""), "firm": r.get("recalling_firm", ""),
                    "reason": _clean(r.get("reason_for_recall", ""), 240), "product": _clean(r.get("product_description", ""), 160),
                    "reported": r.get("report_date", ""), "source": "openFDA enforcement report (public data; US recalls)"})
    return out
