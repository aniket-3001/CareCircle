"""Reading a dose as written, for display and for catching unit slips. Never for deciding a dose.

`parse("500 mg")` gives an integer amount in micrograms (or micro-units for iu / ml) so no float is ever compared. `slip(old, new)` says when a new entry for the
same medicine differs from the previous one by a typical typing or reading slip: a unit that changed (mg to mcg), or a value exactly 10x, 100x or 1000x apart.
That is only a prompt to look at the label again: it never says which one is right."""
from __future__ import annotations

import re
from typing import Optional

# unit -> (family, micro multiplier)
UNITS = {"mcg": ("mass", 1), "ug": ("mass", 1), "µg": ("mass", 1), "mg": ("mass", 1000), "g": ("mass", 1_000_000), "gm": ("mass", 1_000_000),
         "iu": ("activity", 1_000_000), "ml": ("volume", 1_000_000), "l": ("volume", 1_000_000_000)}
PAT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mcg|µg|ug|mg|gm|g|iu|ml|l)\b", re.I)


def parse(text: str) -> Optional[dict]:
    """First amount with a unit in `text`: {"micro": int, "unit": "mg", "family": "mass"}, or None."""
    m = PAT.search(text or "")
    if not m:
        return None
    unit = m.group(2).lower()
    fam, mult = UNITS[unit]
    whole, _, frac = m.group(1).replace(",", ".").partition(".")
    micro = int(whole) * mult + (int((frac + "000000")[:6]) * mult) // 1_000_000
    return {"micro": micro, "unit": unit, "family": fam}


def slip(old_text: str, new_text: str) -> Optional[str]:
    """A plain-words prompt if `new_text` looks like a unit or magnitude slip against `old_text`, else None."""
    a, b = parse(old_text), parse(new_text)
    if not a or not b or a["micro"] == b["micro"]:
        return None
    na, nb = PAT.search(old_text).group(1), PAT.search(new_text).group(1)
    if a["family"] != b["family"] or (a["unit"] != b["unit"] and na == nb):
        return f"The unit changed from {a['unit']} to {b['unit']}. Check the label again."
    hi, lo = max(a["micro"], b["micro"]), min(a["micro"], b["micro"])
    if lo and hi % lo == 0 and hi // lo in (10, 100, 1000):
        return f"This is {hi // lo} times {'more' if b['micro'] > a['micro'] else 'less'} than the entry before ({old_text.strip()} to {new_text.strip()}). Check the label again."
    return None
