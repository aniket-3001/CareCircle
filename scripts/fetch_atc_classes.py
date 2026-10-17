"""Fetch the members of each allergy class from NLM RxClass (WHO ATC codes, by ingredient) into carecircle/snapshot/classes_atc.json.

  python scripts/fetch_atc_classes.py

The class words a family types ("penicillin", "NSAIDs") are mapped by hand to ATC codes below; the members come from the table, not from a hand list.
carecircle/classes.py adds them to its starter list. Run it to refresh; the file records the date and the codes used.
"""
import json
import os
import time
import urllib.request

CODES = {
    "penicillin": ["J01CA", "J01CE", "J01CF", "J01CR"], "cephalosporin": ["J01DB", "J01DC", "J01DD", "J01DE"], "sulfa": ["J01EB", "J01EC", "J01ED", "J01EE"],
    "nsaid": ["M01A"], "aspirin": ["N02BA", "B01AC06"], "statin": ["C10AA"], "macrolide": ["J01FA"], "fluoroquinolone": ["J01MA"], "tetracycline": ["J01AA"],
    "ace inhibitor": ["C09A", "C09B"], "arb": ["C09C", "C09D"], "beta blocker": ["C07A"], "opioid": ["N02A"], "benzodiazepine": ["N05BA", "N05CD", "N03AE"],
    "ppi": ["A02BC"], "sulfonylurea": ["A10BB"], "anticonvulsant": ["N03A"],
    "calcium channel blocker": ["C08"], "thiazide": ["C03A", "C03B"], "fibrate": ["C10AB"], "anticoagulant": ["B01AA", "B01AB", "B01AE", "B01AF"],
    "antidepressant": ["N06A"], "antipsychotic": ["N05A"], "aminoglycoside": ["J01G"], "carbapenem": ["J01DH"], "nitrofuran": ["J01XE"],
}
URL = "https://rxnav.nlm.nih.gov/REST/rxclass/classMembers.json?classId={}&relaSource=ATC&ttys=IN"


def members(code: str) -> set[str]:
    with urllib.request.urlopen(URL.format(code), timeout=60) as r:
        d = json.load(r)
    return {m["minConcept"]["name"].lower() for m in d.get("drugMemberGroup", {}).get("drugMember", [])}


def main() -> None:
    out = {"source": "NLM RxClass, ATC relation, ingredient level", "fetched": time.strftime("%Y-%m-%d"), "classes": {}}
    for name, codes in CODES.items():
        got: set[str] = set()
        for c in codes:
            got |= members(c)
            time.sleep(0.3)
        out["classes"][name] = {"atc": codes, "members": sorted(got)}
        print(f"{name:24s} {len(got):4d} ingredients")
    path = os.path.join(os.path.dirname(__file__), "..", "carecircle", "snapshot", "classes_atc.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, sort_keys=True)


main()
