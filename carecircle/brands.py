"""Combination brands -> every ingredient they contain.

Most chronic prescriptions in India are fixed-dose combinations ("Telma-AM" is telmisartan AND amlodipine). Reading such a name as one ingredient silently
removes the other from every interaction check, so the reader expands a known combination into all its ingredients, and each ingredient becomes its own
proposal that a person confirms.

THIS TABLE IS SMALL, HAND-WRITTEN AND NOT VERIFIED against a drug master or a label (none is licensed for this project). Each row is the usual
formulation of the brand; manufacturers change formulations and sell the same name in other strengths. Everything it produces is shown as "from a
brand list, check the pack", and a brand that is not in this table is never reduced to one ingredient: it stays a proposal the person has to name.
A licensed drug master (for example CDSCO-approved formulations) would replace it; the code reads only `expand()`."""
from __future__ import annotations

import re

SOURCE = "hand-written brand list (unverified): check the pack"

# brand as printed -> ingredients, using the names the reference graph uses where it has them. An ingredient the reference graph lacks is still listed:
# the app then records it as "not checked against anything".
COMBINATIONS = {
    "Telma-AM": ["telmisartan", "amlodipine"],
    "Telma-H": ["telmisartan", "hydrochlorothiazide"],
    "Glycomet-GP": ["metformin", "glimepiride"],
    "Ecosprin-AV": ["acetylsalicylic acid", "atorvastatin"],
    "Ecosprin Gold": ["acetylsalicylic acid", "atorvastatin", "clopidogrel"],
    "Amlokind-AT": ["amlodipine", "atenolol"],
    "Concor-AM": ["bisoprolol", "amlodipine"],
    "Augmentin": ["amoxicillin", "clavulanic acid"],
    "Clavam": ["amoxicillin", "clavulanic acid"],
    "Combiflam": ["ibuprofen", "acetaminophen"],
    "Zerodol-P": ["aceclofenac", "acetaminophen"],
    "Pan-D": ["pantoprazole", "domperidone"],
    "Losar-H": ["losartan", "hydrochlorothiazide"],
    "Janumet": ["sitagliptin", "metformin"],
    "Istamet": ["sitagliptin", "metformin"],
    "Shelcal": ["calcium carbonate", "cholecalciferol"],
    "Calcirol-D3": ["cholecalciferol"],
}


def squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_INDEX = {squash(k): (k, v) for k, v in COMBINATIONS.items()}
_ORDER = sorted(_INDEX, key=len, reverse=True)                   # the longest name first: "ecosprin gold" before "ecosprin"


def find(text: str) -> list[tuple[str, list[str], int, int]]:
    """Every combination brand named in `text`, as (brand, ingredients, start, end) in the ORIGINAL text. Case, spaces and hyphens do not matter
    ("Telma AM", "TELMA-AM", "telmaam"). A name must stand on its own: it is not taken from inside a longer word."""
    out, taken = [], []
    for key in _ORDER:
        brand, ingredients = _INDEX[key]
        pattern = r"(?<![a-z0-9])" + r"[\s\-_.]*".join(re.escape(ch) for ch in key) + r"(?![a-z])"
        for m in re.finditer(pattern, text.lower()):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            out.append((brand, ingredients, m.start(), m.end()))
    return sorted(out, key=lambda x: x[2])
