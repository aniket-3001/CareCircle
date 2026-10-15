"""Safety layer. Three checks, all testable without a model:
 1. scan_advice(obj): no string we emit may tell someone to take/stop/skip/double/adjust a medicine (the tool records and cross-checks).
 2. numbers_match_facts(text, facts): any reworded message may contain only numbers that appear in the record (vayu-labs rule).
 3. judgement(check): a first-class "refuse to judge" summary: no data / partial / flags / no_known_conflict. Never 'safe'.
"""
from __future__ import annotations

import re

# Imperative or advisory phrasing about medication. Matched on OUR output strings only (user-quoted text lives in 'quote' fields).
ADVICE = re.compile(
    r"\b(you should|you must|you need to|do not|don't|never|please)\s+(take|stop|skip|double|halve|increase|decrease|reduce|change|"
    r"discontinue|start|swap|substitute|give)\b|\b(take|stop taking|skip|double|halve|increase|decrease|discontinue)\s+(the |your |this |a |an )?"
    r"(dose|dosage|tablet|pill|medicine|medication|drug)\b|\b(safe to take|is safe|are safe|completely safe|no risk)\b", re.I)
SKIP_KEYS = {"quote", "text", "dose_text", "freq_text", "note_from_user"}        # verbatim user/source text is data, not our advice
NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def scan_advice(obj, path: str = "") -> list[str]:
    """Paths of any emitted string that reads as medication advice. Empty list = clean."""
    bad: list[str] = []
    if isinstance(obj, str):
        if ADVICE.search(obj):
            bad.append(f"{path}: {obj[:80]}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in SKIP_KEYS:
                bad += scan_advice(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            bad += scan_advice(v, f"{path}[{i}]")
    return bad


def numbers_in(text: str) -> list[float]:
    return [float(t.replace(",", "")) for t in NUM.findall(text or "")]


def numbers_match_facts(text: str, facts: dict) -> bool:
    allowed: set[float] = set()
    for v in facts.values():
        allowed.update([float(v)] if isinstance(v, (int, float)) and not isinstance(v, bool) else numbers_in(str(v)))
    return all(n in allowed for n in numbers_in(text))


def reword(template: str, facts: dict, generate=None) -> dict:
    """Plain template unless a model rewrite keeps every number inside `facts`. Says which one was used."""
    if generate is not None:
        try:
            out = (generate(template, facts) or "").strip()
        except Exception:
            out = ""
        if out and numbers_match_facts(out, facts) and not scan_advice(out):
            return {"text": out, "source": "model"}
    return {"text": template, "source": "template"}


def judgement(check: dict) -> dict:
    """What we are willing to say about a regimen, and why we may refuse."""
    reasons = []
    if not check["regimen"]:
        return {"state": "no_data", "reasons": ["no confirmed medicines on record"], "statement": "Nothing to check yet."}
    if check["not_in_reference"]:
        reasons.append(f"not in our reference data: {', '.join(check['not_in_reference'])}")
    if check["unrated"]:
        reasons.append(f"{len(check['unrated'])} pair(s) listed by the source without a severity")
    if check["direct"] or check["enzyme_paths"]:
        return {"state": "flags", "reasons": reasons, "statement": "Possible interactions found: discuss with a prescriber or pharmacist."}
    if reasons:
        return {"state": "partial", "reasons": reasons, "statement": "Not enough information to judge everything. Ask a pharmacist."}
    return {"state": "no_known_conflict", "reasons": [],
            "statement": "No known conflict in our data. This is not a statement of safety."}
