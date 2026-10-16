"""Multimodal intake: turn a photo, voice note, PDF/DOCX or typed text into PROPOSED medication entries. Nothing is written here.

Pipeline per file:  source text (independent of any LLM)  ->  proposals  ->  every proposal's quote verified against the source text.
  image  : RapidOCR (local, no key)         audio : faster-whisper (local)         pdf : pypdf          docx : python-docx
Proposal extractors, best first:
  1. Bedrock (Nova by default; set CC_MODEL for another id) given the text and, for images, the picture. Output is strict JSON, schema
     checked, and EACH quote must be found in the OCR/ASR text, so a model cannot invent a label line.
  2. Rules (regex + fuzzy drug match): always available offline.
The model only structures what is there. It never decides interactions or doses; those come from the graph and the prescriber.
"""
from __future__ import annotations

import io
import json
import os
import re
from typing import Optional

from . import brands
from .verify import field_in_quote, quote_in_source

DOSE_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(?:[\s.:]?(?:mcg|µg|mg|ml|iu|units?)|\s?g)", re.I)   # OCR glues words: "Sodium5mgtablets"
FREQ_RE = re.compile(r"\b((?:once|twice|thrice) (?:a day|daily|per day|weekly)|once|twice|thrice|daily|every \d+ ?(?:hours?|hrs?)|\d+ times (?:a|per) day|at bedtime|bedtime|(?:at|in the|every) (?:night|morning|evening|afternoon)|night|morning|evening|"
                     r"with (?:food|meals)|before (?:food|meals)|after (?:food|meals)|as needed|prn|od|bd|bid|tid|qid)\b", re.I)
MAX_BYTES = 12 * 1024 * 1024
_whisper = None
_ocr = None


# ---------------------------------------------------------------- source text
def read_source(data: bytes, filename: str, content_type: str = "", language: Optional[str] = None) -> dict:
    """{kind, text, method, status, note}. status 'ok' | 'empty' | 'unsupported'. Never raises for bad content."""
    if len(data) > MAX_BYTES:
        return {"kind": "unknown", "text": "", "method": "none", "status": "unsupported", "note": "file too large"}
    name, ct = filename.lower(), (content_type or "").lower()
    try:
        if ct.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            return _done("image", _ocr_text(data), "rapidocr")
        if ct.startswith("audio/") or name.endswith((".wav", ".mp3", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".webm")):
            return _done("voice", _asr_text(data, filename, language), "faster-whisper")
        if ct == "application/pdf" or name.endswith(".pdf"):
            from pypdf import PdfReader
            return _done("document", "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages), "pypdf")
        if name.endswith(".docx"):
            import docx
            return _done("document", "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs), "python-docx")
        if name.endswith((".txt", ".md")) or ct.startswith("text/"):
            return _done("typed", data.decode("utf-8", errors="replace"), "text")
    except Exception as e:                                                       # corrupt file: report, don't crash
        return {"kind": "unknown", "text": "", "method": "none", "status": "unsupported", "note": f"{type(e).__name__}"}
    return {"kind": "unknown", "text": "", "method": "none", "status": "unsupported", "note": "unsupported file type"}


def _done(kind: str, text: str, method: str) -> dict:
    text = text.strip()
    return {"kind": kind, "text": text, "method": method, "status": "ok" if text else "empty",
            "note": None if text else "nothing readable found: type it in or retake the photo"}


_O_FOR_ZERO = re.compile(r"(?<=\d)([Oo]+)(?=\d|\s?(?:mg|mcg|ml|g)\b)", re.I)


def fix_digits(text: str) -> str:
    """OCR reads a zero as the letter O inside numbers ("5o0 mg", "1OO mg"). Only touches O's that follow a digit and precede a digit or a unit."""
    return _O_FOR_ZERO.sub(lambda m: "0" * len(m.group(1)), text)


def _ocr_text(data: bytes) -> str:
    global _ocr
    from PIL import Image
    import numpy as np
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    res, _ = _ocr(np.array(Image.open(io.BytesIO(data)).convert("RGB")))
    return "\n".join(r[1] for r in (res or []))


def _asr_text(data: bytes, filename: str, language: Optional[str]) -> str:
    global _whisper
    import tempfile
    from faster_whisper import WhisperModel
    if _whisper is None:
        _whisper = WhisperModel(os.getenv("CC_WHISPER", "base"), device="cpu", compute_type="int8")
    suffix = os.path.splitext(filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        path = f.name
    try:
        segs, _ = _whisper.transcribe(path, language=language, vad_filter=True)
        return " ".join(s.text.strip() for s in segs)
    finally:
        os.remove(path)


# ---------------------------------------------------------------- proposals
_JOINERS = re.compile(r",|\s+and\s+|\s*&\s*|\s*\+\s*|\s+plus\s+|\s+then\s+", re.I)


def _split_medicines(line: str, checker) -> list[str]:
    """'metformin 500 mg twice daily and atorvastatin 20 mg at night' is two medicines. Split a line at its joiners (comma, and, &, +, plus) only when
    at least two different medicines are named in it, and keep each medicine's own dose and timing words with it. Every piece is a contiguous slice of
    the original line, so the quote still occurs in the source exactly. A line with one medicine ('1 tablet morning and evening') is never cut."""
    cuts, last = [], 0
    for m in _JOINERS.finditer(line):
        cuts.append((last, m.start()))
        last = m.end()
    cuts.append((last, len(line)))
    parts = [(a, b) for a, b in cuts if line[a:b].strip()]
    if len(parts) < 2:
        return [line]
    groups: list[list[tuple[int, int]]] = []
    names: list[str] = []
    for a, b in parts:
        c = checker.candidates(line[a:b], 1)
        named = c[0]["name"] if c and c[0]["score"] >= 0.8 else None
        if named and (not names or named != names[-1]):
            groups.append([(a, b)])
            names.append(named)
        elif groups:
            groups[-1].append((a, b))                      # a dose or timing fragment belongs to the medicine before it
        else:
            groups.append([(a, b)])
            names.append("")
    if len({n for n in names if n}) < 2:
        return [line]
    return [line[g[0][0]:g[-1][1]].strip() for g in groups]


_NOT_A_MEDICINE_LINE = re.compile(r"^(take|taken|store|keep|qty|quantity|refills?|rx|dr|doctor|patient|name|date|pharmacy|tablets?|capsules?|use|apply|"
                                  r"dispense|discard|expiry|exp|mfg|batch|lot|total|price|mrp|phone|tel|address|signature)\b", re.I)


def _names_a_medicine(line: str, checker) -> bool:
    c = checker.candidates(line, 1)
    return bool(brands.find(line)) or bool(c and c[0]["score"] >= 0.8)


def _ingredient_candidate(name: str, checker) -> dict:
    """An ingredient of a combination as a candidate: known to the reference graph (so it can be checked) or not (recorded, but not checked)."""
    if name in checker.known_names():
        return {"name": name, "score": 1.0, "via": brands.SOURCE}
    return {"name": name, "score": 0.0, "unchecked": True, "via": brands.SOURCE}


def rule_proposals(text: str, checker) -> list[dict]:
    """One proposal per medicine named. Dose/frequency are copied as written, never interpreted.

    A combination brand (Telma-AM) becomes one proposal for EACH of its ingredients, so none of them disappears from the interaction checks; the strength
    printed beside a combination belongs to the product, so it is shown on the proposals as `combination_strength` and not copied onto an ingredient.
    A line that looks like a medicine (a name and a dose or a frequency) but names nothing the reference data knows is NOT dropped: it becomes a proposal
    marked `unchecked`, which a person can record as a medicine that is not checked against anything."""
    out, seen = [], set()
    lines = [part for l in re.split(r"[\n;]|(?<=[.!?])\s", text) if l.strip() for part in _split_medicines(l.strip(), checker)]
    covered: set[int] = set()
    for i, line in enumerate(lines):
        found = brands.find(line)
        if found:
            dose, freq, last = DOSE_RE.search(line), FREQ_RE.search(line), i
            for k in range(i + 1, min(i + 4, len(lines))):
                if dose and freq:
                    break
                if _names_a_medicine(lines[k], checker):
                    break
                d2 = None if dose else DOSE_RE.search(lines[k])
                f2 = None if freq else FREQ_RE.search(lines[k])
                if d2 or f2:
                    dose, freq, last = dose or d2, freq or f2, k
            quote = " ".join(lines[i:last + 1])[:200]
            covered.update(range(i, last + 1))
            for brand, ingredients, _s, _e in found:
                for ing in ingredients:
                    key = (ing, brand)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"drug_candidates": [_ingredient_candidate(ing, checker)], "dose_text": "", "freq_text": freq.group(0) if freq else "",
                                "quote": quote, "method": "brand list", "combination": brand, "combination_ingredients": ingredients,
                                "combination_strength": dose.group(0) if dose else ""})
            continue
        cands = checker.candidates(line, 3)
        if not cands or cands[0]["score"] < 0.8:                  # line must actually contain a drug name
            word = re.match(r"\s*([A-Za-z][A-Za-z\-]{3,30})\b", line)
            looks_like_one = DOSE_RE.search(line) or re.match(r"\s*[A-Za-z][A-Za-z\-]*[ \-]+\d", line)       # "Name 500 mg" or "Name 1 daily": a name, then a number
            if (i not in covered and word and looks_like_one and not _NOT_A_MEDICINE_LINE.match(line)
                    and not checker.candidates(word.group(1), 1)):
                out.append({"drug_candidates": [{"name": word.group(1).lower(), "score": 0.0, "unchecked": True, "via": "read from the text; not in our reference data"}],
                            "dose_text": (DOSE_RE.search(line).group(0) if DOSE_RE.search(line) else ""),
                            "freq_text": (FREQ_RE.search(line).group(0) if FREQ_RE.search(line) else ""), "quote": line[:200], "method": "rules"})
            continue
        dose, freq, last = DOSE_RE.search(line), FREQ_RE.search(line), i
        for k in range(i + 1, min(i + 4, len(lines))):            # labels spread a drug over lines: name / strength / "twice daily"
            if dose and freq:
                break
            c2 = checker.candidates(lines[k], 1)
            if brands.find(lines[k]) or (c2 and c2[0]["score"] >= 0.8 and c2[0]["name"] != cands[0]["name"]):   # the next line names another drug: stop
                break
            d2 = None if dose else DOSE_RE.search(lines[k])
            f2 = None if freq else FREQ_RE.search(lines[k])
            if d2 or f2:
                dose, freq, last = dose or d2, freq or f2, k
        quote = " ".join(lines[i:last + 1])                       # contiguous lines, so the quote still occurs in the source text
        covered.update(range(i, last + 1))
        key = (cands[0]["name"], dose.group(0).lower() if dose else "")
        if key in seen:
            continue
        seen.add(key)
        out.append({"drug_candidates": cands, "dose_text": dose.group(0) if dose else "", "freq_text": freq.group(0) if freq else "",
                    "quote": quote[:200], "method": "rules"})
    return out


_PROMPT = ("You read medication information. Extract every medicine mentioned. Return ONLY JSON: "
           '{"items":[{"drug":str,"dose_text":str,"freq_text":str,"quote":str}]}. Copy drug, dose_text, freq_text and quote VERBATIM '
           "from the source; use \"\" when absent. Never infer, convert, complete or correct anything. No advice, no commentary.")


def llm_proposals(text: str, image: Optional[bytes] = None, image_format: str = "png") -> list[dict]:
    """Bedrock Converse. Returns [] on any failure so the caller falls back to rules. Output is untrusted: strict shape + caps."""
    if os.getenv("CC_LLM", "1") == "0":
        return []
    try:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
        content = []
        if image:
            content.append({"image": {"format": image_format, "source": {"bytes": image}}})
        content.append({"text": _PROMPT + "\n\nSOURCE TEXT:\n" + text[:6000]})
        r = client.converse(modelId=os.getenv("CC_MODEL", "us.amazon.nova-pro-v1:0"), messages=[{"role": "user", "content": content}],
                            inferenceConfig={"maxTokens": 800, "temperature": 0})
        raw = r["output"]["message"]["content"][0]["text"]
        m = re.search(r"\{.*\}|\[.*\]", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
        items = data.get("items", data) if isinstance(data, dict) else data
        out = []
        for it in (items if isinstance(items, list) else [])[:20]:
            if not isinstance(it, dict) or not isinstance(it.get("drug"), str) or not it["drug"].strip():
                continue
            out.append({"llm_drug": it["drug"].strip()[:80], "dose_text": str(it.get("dose_text", ""))[:60],
                        "freq_text": str(it.get("freq_text", ""))[:80], "quote": str(it.get("quote", ""))[:200], "method": "bedrock"})
        return out
    except Exception:
        return []


def propose(text: str, checker, image: Optional[bytes] = None, image_format: str = "png") -> list[dict]:
    """Merge LLM and rule proposals. Each carries `verified` = its quote occurs in the independent source text. Unverified LLM items
    are kept but flagged, never trusted. Drug names are always resolved to reference-graph candidates for a human to choose."""
    props = []
    for p in llm_proposals(text, image, image_format):
        named = p.pop("llm_drug")
        if not quote_in_source(named, p["quote"]):                # a quote that does not even contain the drug name proves nothing
            continue
        for k in ("dose_text", "freq_text"):                      # a model may not put a dose or frequency on a line that does not say it: such a field is dropped,
            if p[k] and not field_in_quote(p[k], p["quote"]):    # so the quote that is shown really contains everything shown beside it
                p[k] = ""
        p["drug_candidates"] = checker.resolve(named, 3)
        p["verified"] = bool(text) and quote_in_source(p["quote"], text)
        if p["drug_candidates"]:
            props.append(p)
    have = {(p["drug_candidates"][0]["name"]) for p in props if p["verified"] and p["dose_text"]}   # a model item with no dose yields to the rule reading
    for p in rule_proposals(text, checker):
        if p["drug_candidates"][0]["name"] not in have:
            p["verified"] = quote_in_source(p["quote"], text)
            props = [q for q in props if not (q["drug_candidates"][0]["name"] == p["drug_candidates"][0]["name"] and not q["dose_text"])]
            props.append(p)
    for p in props:
        p["needs_human"] = True                                  # always: nothing is written without a person confirming
    return props
