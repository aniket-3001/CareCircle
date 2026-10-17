"""Medicine classes used by the allergy check: which medicines belong to a group a family might name ("penicillin", "NSAIDs", "sulfa").

Two sources. carecircle/snapshot/classes_atc.json lists the ingredients of each class from the WHO ATC table as served by NLM RxClass (scripts/fetch_atc_classes.py;
the class words are mapped to ATC codes by hand, the members are not). The short hand-written list below is kept as a floor, and the two are merged. Neither is
complete: a medicine can be missing from a group, and a group can be missing altogether. A hit means "ask the prescriber"; no hit means nothing. Members
are generic names, matched to a regimen entry by name.

A class is a word a family types, with the other words that mean the same ("nsaids", "anti-inflammatory"). Cross-reactivity between classes
(for example penicillin and cephalosporin) is deliberately not claimed here."""
from __future__ import annotations

import json
import os
import re

CLASSES: dict[str, dict] = {
    "penicillin": {"also": ("penicillins", "beta-lactam penicillin"), "members": ("amoxicillin", "ampicillin", "penicillin v", "penicillin g", "piperacillin", "flucloxacillin", "dicloxacillin", "cloxacillin", "benzylpenicillin")},
    "cephalosporin": {"also": ("cephalosporins", "cephalexin allergy"), "members": ("cefazolin", "cephalexin", "cefuroxime", "cefixime", "ceftriaxone", "cefotaxime", "cefpodoxime", "cefdinir", "ceftazidime", "cefepime")},
    "sulfa": {"also": ("sulpha", "sulfonamide", "sulphonamide"), "members": ("sulfamethoxazole", "sulfasalazine", "sulfadiazine")},
    "nsaid": {"also": ("nsaids", "anti-inflammatory", "painkiller"), "members": ("ibuprofen", "naproxen", "diclofenac", "acetylsalicylic acid", "aspirin", "ketorolac", "celecoxib", "indomethacin", "etoricoxib", "nimesulide", "mefenamic acid", "piroxicam", "meloxicam")},
    "aspirin": {"also": ("acetylsalicylic",), "members": ("acetylsalicylic acid", "aspirin")},
    "statin": {"also": ("statins",), "members": ("atorvastatin", "simvastatin", "rosuvastatin", "pravastatin", "lovastatin", "fluvastatin", "pitavastatin")},
    "macrolide": {"also": ("macrolides",), "members": ("clarithromycin", "azithromycin", "erythromycin", "roxithromycin")},
    "fluoroquinolone": {"also": ("quinolone", "quinolones", "fluoroquinolones"), "members": ("ciprofloxacin", "levofloxacin", "moxifloxacin", "ofloxacin", "norfloxacin")},
    "tetracycline": {"also": ("tetracyclines",), "members": ("doxycycline", "tetracycline", "minocycline")},
    "ace inhibitor": {"also": ("ace inhibitors", "ace-inhibitor", "ace"), "members": ("lisinopril", "enalapril", "ramipril", "captopril", "perindopril", "benazepril", "fosinopril")},
    "arb": {"also": ("arbs", "angiotensin receptor blocker", "sartan", "sartans"), "members": ("telmisartan", "losartan", "valsartan", "olmesartan", "candesartan", "irbesartan", "azilsartan")},
    "beta blocker": {"also": ("beta-blocker", "beta blockers", "beta-blockers"), "members": ("metoprolol", "atenolol", "propranolol", "bisoprolol", "carvedilol", "nebivolol", "labetalol")},
    "opioid": {"also": ("opiate", "opioids", "opiates"), "members": ("morphine", "codeine", "tramadol", "oxycodone", "fentanyl", "tapentadol", "hydrocodone")},
    "benzodiazepine": {"also": ("benzodiazepines", "benzo"), "members": ("diazepam", "alprazolam", "lorazepam", "clonazepam", "midazolam", "temazepam")},
    "ppi": {"also": ("proton pump inhibitor", "proton pump inhibitors"), "members": ("omeprazole", "pantoprazole", "esomeprazole", "lansoprazole", "rabeprazole")},
    "sulfonylurea": {"also": ("sulfonylureas", "sulphonylurea"), "members": ("glimepiride", "glibenclamide", "glipizide", "gliclazide")},
    "anticonvulsant": {"also": ("antiepileptic", "anti-epileptic", "anticonvulsants"), "members": ("carbamazepine", "phenytoin", "valproic acid", "lamotrigine", "levetiracetam", "oxcarbazepine")},
}


def _atc() -> dict[str, dict]:
    try:
        with open(os.path.join(os.path.dirname(__file__), "snapshot", "classes_atc.json"), encoding="utf-8") as f:
            return json.load(f)["classes"]
    except (OSError, ValueError, KeyError):
        return {}


ATC_SOURCE = "WHO ATC via NLM RxClass"
HAND_SOURCE = "hand-written (unverified)"


def all_classes() -> dict[str, dict]:
    """Both sources merged, one entry per class: {also: [spellings], atc: [codes], members: {ingredient: source}}. Names have spaces, not hyphens."""
    out: dict[str, dict] = {}
    for name, c in CLASSES.items():
        out[name.replace("-", " ")] = {"also": list(c["also"]), "atc": [], "members": {m: HAND_SOURCE for m in c["members"]}}
    for name, v in _atc().items():
        e = out.setdefault(name.replace("-", " "), {"also": [], "atc": [], "members": {}})
        e["also"] = list(dict.fromkeys(e["also"] + list(v.get("also", []))))
        e["atc"] = list(v.get("atc", []))
        for m in v["members"]:
            e["members"][m] = ATC_SOURCE                   # a member in both lists is credited to the table
    return out


CLASS_TABLE = all_classes()


def words_for(name: str, also: list[str]) -> list[str]:
    """The ways a person may write the class: its name (spaces or hyphens, with or without an s) and its other spellings."""
    base = [name, name.replace(" ", "-"), name + "s", name.replace(" ", "-") + "s", *also, *[w + "s" for w in also]]
    return list(dict.fromkeys(w.lower() for w in base))


def classes_named_in(text: str, table: dict[str, dict] | None = None) -> list[str]:
    """The classes a typed allergy names: the class word, or one of its other spellings, must occur as whole words."""
    t = " " + re.sub(r"[^a-z0-9+\- ]+", " ", text.lower()) + " "
    return [name for name, c in (table or CLASS_TABLE).items() if any(f" {w} " in t for w in words_for(name, c["also"]))]


def group_of(text: str) -> tuple[str, tuple[str, ...]]:
    """The first class a typed allergy names (or ("", ()) when it names none) and its members."""
    for name in classes_named_in(text):
        return name, tuple(CLASS_TABLE[name]["members"])
    return "", ()
