"""Two plain counts a family can bring to a pharmacist. Arithmetic over what is on record; never a score of the person and never advice.

* regimen_load: how many medicines, how many different times of day the written frequencies imply, and how many carry a special direction (with food, empty
  stomach, before a meal ...). It is a simple count, NOT the validated Medication Regimen Complexity Index.
* anticholinergic_count: the sum of per-medicine scores from a short list copied from the published Anticholinergic Cognitive Burden scale (Boustani 2008, 2012
  update). The list here is a SUBSET typed in by hand, so it can miss medicines and a total is a minimum: say so every time, and check with a pharmacist."""
from __future__ import annotations

import re

ACB = {
    # score 3
    "amitriptyline": 3, "atropine": 3, "benztropine": 3, "chlorpheniramine": 3, "chlorpromazine": 3, "clozapine": 3, "darifenacin": 3, "dicyclomine": 3, "diphenhydramine": 3,
    "doxepin": 3, "hydroxyzine": 3, "imipramine": 3, "meclizine": 3, "nortriptyline": 3, "oxybutynin": 3, "paroxetine": 3, "promethazine": 3, "quetiapine": 3, "scopolamine": 3,
    "thioridazine": 3, "tolterodine": 3, "trospium": 3,
    # score 2
    "amantadine": 2, "carbamazepine": 2, "cyclobenzaprine": 2, "cyproheptadine": 2, "loxapine": 2, "oxcarbazepine": 2, "pimozide": 2,
    # score 1
    "alprazolam": 1, "aripiprazole": 1, "atenolol": 1, "bupropion": 1, "captopril": 1, "cetirizine": 1, "chlorthalidone": 1, "cimetidine": 1, "codeine": 1, "colchicine": 1,
    "diazepam": 1, "digoxin": 1, "furosemide": 1, "fluvoxamine": 1, "haloperidol": 1, "hydralazine": 1, "hydrocortisone": 1, "isosorbide": 1, "loperamide": 1, "loratadine": 1,
    "metoprolol": 1, "morphine": 1, "nifedipine": 1, "prednisone": 1, "quinidine": 1, "ranitidine": 1, "risperidone": 1, "theophylline": 1, "trazodone": 1, "triamterene": 1,
    "venlafaxine": 1, "warfarin": 1,
}
SOURCE = "Anticholinergic Cognitive Burden scale (Boustani 2008; 2012 update), a hand-copied subset"
DIRECTION = re.compile(r"\b(with (food|meals?|water|milk)|empty stomach|before (breakfast|meals?|food|bed)|after (food|meals?)|at bedtime|upright|do not crush)\b", re.I)
TIMES = (("morning", r"morning|breakfast|\bam\b|once daily|daily|once a day|every day"), ("midday", r"midday|noon|lunch|three times|3 times|thrice|tds|\btid\b"),
         ("evening", r"evening|dinner|supper|night|bedtime|twice|2 times|\bbd\b|\bbid\b|three times|3 times|thrice|tds|\btid\b"))


def anticholinergic_count(regimen: list[dict]) -> dict:
    hits = [{"drug": r["drug"], "score": ACB[r["drug"]]} for r in regimen if r["drug"] in ACB]
    total = sum(h["score"] for h in hits)
    return {"total": total, "medicines": hits, "list_size": len(ACB), "source": SOURCE,
            "statement": f"{total} from {len(hits)} medicine(s) on this short list; a total of 3 or more is the usual reason to ask a pharmacist for a review. "
                         "The list is a subset, so the real total could be higher. This is a talking point, not a verdict." if hits else
                         "None of the medicines on record is on this short list. The list is a subset, so that does not mean the burden is zero."}


def regimen_load(regimen: list[dict]) -> dict:
    directions = sum(1 for r in regimen if DIRECTION.search(r.get("freq_text", "") or ""))
    slots: set[str] = set()
    for r in regimen:
        f = (r.get("freq_text", "") or "").lower()
        for name, pat in TIMES:
            if re.search(pat, f):
                slots.add(name)
    return {"medicines": len(regimen), "times_of_day": len(slots), "special_directions": directions,
            "statement": f"{len(regimen)} medicines, written to be taken at {len(slots) or 'unspecified'} time(s) of day, {directions} with a special direction. "
                         "A simple count of what is written, not the validated Medication Regimen Complexity Index."}
