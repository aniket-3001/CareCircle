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


def _atc() -> dict[str, tuple[str, ...]]:
    try:
        with open(os.path.join(os.path.dirname(__file__), "snapshot", "classes_atc.json"), encoding="utf-8") as f:
            return {k.replace(" ", "-"): tuple(v["members"]) for k, v in json.load(f)["classes"].items()}
    except (OSError, ValueError, KeyError):
        return {}


ATC = _atc()


def group_of(text: str) -> tuple[str, tuple[str, ...]]:
    """The class a typed allergy names (or ("", ()) when it names none): the class word, or one of its other spellings, must occur as whole words."""
    t = " " + re.sub(r"[^a-z0-9+\- ]+", " ", text.lower()) + " "
    for name, c in CLASSES.items():
        for word in (name, *c["also"]):
            if f" {word} " in t:
                return name, tuple(dict.fromkeys(c["members"] + ATC.get(name.replace(" ", "-"), ())))
    for name, members in ATC.items():
        if f" {name.replace('-', ' ')} " in t or f" {name} " in t or f" {name}s " in t:
            return name, members
    return "", ()
