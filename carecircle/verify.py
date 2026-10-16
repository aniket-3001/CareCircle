"""Quote-and-verify: anything read from a photo/voice/PDF must come with the exact text it was read from, and that text must
exist in the source. OCR drops spaces ("WarfarinSodium5mg"), so comparison ignores case, whitespace and punctuation only."""
import re


def squash(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


def quote_in_source(quote: str, source_text: str) -> bool:
    q = squash(quote)
    return len(q) >= 3 and q in squash(source_text)


def field_in_quote(field: str, quote: str) -> bool:
    """A dose or frequency read from a label really is in the line it is said to come from. Same squashing as quote_in_source, with no minimum length
    ("5g" and "od" are real), and a number must not start in the middle of another one: "500 mg" is not in "1500 mg"."""
    f = squash(field)
    if not f:
        return False
    return re.search((r"(?<![\d.])" if f[0].isdigit() else "") + re.escape(f), squash(quote)) is not None
