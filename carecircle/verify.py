"""Quote-and-verify: anything read from a photo/voice/PDF must come with the exact text it was read from, and that text must
exist in the source. OCR drops spaces ("WarfarinSodium5mg"), so comparison ignores case, whitespace and punctuation only."""
import re


def squash(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


def quote_in_source(quote: str, source_text: str) -> bool:
    q = squash(quote)
    return len(q) >= 3 and q in squash(source_text)
