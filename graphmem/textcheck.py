"""One place that decides what text the system will store. Anything that reaches the database as a string goes through here first, so a bad character is a
clear 400/422 to the caller, never a crash: a NUL character cannot be sent to the database, and a lone surrogate cannot be encoded as UTF-8."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator

NUL = chr(0)


def check_text(value: Any, where: str = "arguments") -> None:
    """Raise ValueError for text that cannot be stored, however deeply it is nested in dicts and lists."""
    if isinstance(value, str):
        if NUL in value:
            raise ValueError(f"{where} cannot contain a NUL (zero) character")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError(f"{where} contains characters that are not valid text") from None
    elif isinstance(value, dict):
        for k, v in value.items():
            check_text(k, where)
            check_text(v, where)
    elif isinstance(value, (list, tuple)):
        for v in value:
            check_text(v, where)


def fit(value: Any, limit: int, what: str) -> str:
    """Tidy the spaces in a piece of text and refuse it if it is too long. Never cuts it short: a record that quietly drops the end of what someone
    wrote (a dose instruction, a handover note) is worse than one that asks them to shorten it."""
    v = " ".join(str(value if value is not None else "").split())
    if len(v) > limit:
        raise ValueError(f"{what} is limited to {limit} characters (this is {len(v)}): shorten it, or split it in two")
    return v


class Clean(BaseModel):
    """Base for every request body: all its text is checked once it has parsed."""

    @model_validator(mode="after")
    def _no_bad_text(self):
        check_text(self.model_dump(), "the request")
        return self


def shown_name(s: str) -> str:
    """A medicine's name for people to read: 'vitamin d' -> 'Vitamin D', 'vitamin b12' -> 'Vitamin B12', 'acetylsalicylic acid' -> 'Acetylsalicylic acid'.
    The first letter is capitalised and nothing else is lower-cased; a lone letter (with digits) after 'vitamin' is a vitamin's name, so it is capitalised too.
    The same rule as `title` in the web app, so a name reads the same in a reminder, the graph and the screens."""
    import re
    return (s[:1].upper() + s[1:]) if not s else re.sub(r"(?<=\bvitamin )[a-z]\d*\b", lambda m: m.group(0).upper(), s[:1].upper() + s[1:], flags=re.I)


def product_name(p: str) -> str:
    """A combination product's name as it is usually printed: 'telma-am' -> 'Telma-AM' (short parts after a hyphen in capitals). The same rule as `productName` in the web app."""
    return " ".join("-".join((x.upper() if i > 0 and len(x) <= 3 else x[:1].upper() + x[1:]) for i, x in enumerate(w.split("-"))) for w in p.split(" "))
