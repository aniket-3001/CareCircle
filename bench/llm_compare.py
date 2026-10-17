"""B7: which model, if any, structures noisy label text better than the rules alone?

  PYTHONPATH=. python bench/llm_compare.py [--n 40] [--seed 7] [--models rules,us.amazon.nova-pro-v1:0,us.anthropic.claude-haiku-4-5-20251001-v1:0] [--out r.json]

The same synthetic labels as `intake_bench.py` (a medicine and strength from the reference graph, drawn with common fonts at three levels of damage and read by the
real OCR) are turned into proposals by the real `intake.propose`, once per model, and scored the same way: is the right medicine the top suggestion, is it among the
top three, is the strength copied exactly, how many wrong extras appear. Every proposal from a model still has to pass the quote check against the OCR text, so a
model can only help by structuring what the OCR read; it cannot add a medicine the text does not contain.

"rules" is the reader with no model. A model name is a Bedrock model or inference-profile id and needs AWS credentials that may call it.
What this does not measure: real photographs (the labels are synthetic), a model's cost, or anything about advice (a model here only structures text).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bench.intake_bench import LEVELS, STRENGTHS, norm_strength, render  # noqa: E402

DEFAULT = "rules,us.amazon.nova-pro-v1:0,us.anthropic.claude-haiku-4-5-20251001-v1:0,us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def cases(n: int, seed: int):
    from carecircle import intake
    from carecircle.checks import Checker
    ch = Checker(os.getenv("FALKORDB_HOST", "localhost"), int(os.getenv("FALKORDB_PORT", "6379")))
    names = sorted({r[0] for r in ch.g.ro_query("MATCH (d:Drug) WHERE size(d.name) >= 5 AND NOT d.name CONTAINS ' ' RETURN d.name").result_set})
    rng = random.Random(seed)
    out = []
    for drug in rng.sample(names, n):
        strength = rng.choice(STRENGTHS)
        for lv in LEVELS:
            src = intake.read_source(render(rng, drug, strength, lv), "label.jpg", "image/jpeg")
            out.append({"drug": drug, "strength": strength, "level": lv, "text": src["text"] if src["status"] == "ok" else ""})
    return ch, out


def score(model: str, ch, cs: list[dict]) -> dict:
    from carecircle import intake
    if model == "rules":
        os.environ["CC_LLM"] = "0"
    else:
        os.environ["CC_LLM"] = "1"
        os.environ["CC_MODEL"] = model
    res = {lv: {"n": 0, "top1": 0, "top3": 0, "strength_right": 0, "extras": 0, "nothing": 0, "secs": 0.0} for lv in LEVELS}
    for c in cs:
        o = res[c["level"]]
        o["n"] += 1
        t0 = time.perf_counter()
        props = intake.propose(c["text"], ch) if c["text"] else []
        o["secs"] += time.perf_counter() - t0
        if not props:
            o["nothing"] += 1
            continue
        hit = next((p for p in props if p["drug_candidates"][0]["name"] == c["drug"]), None)
        in3 = next((p for p in props if c["drug"] in [x["name"] for x in p["drug_candidates"]]), None)
        o["top1"] += hit is not None
        o["top3"] += in3 is not None
        o["extras"] += len(props) - (1 if in3 else 0)
        got = hit or in3
        o["strength_right"] += bool(got) and norm_strength(got["dose_text"]) == norm_strength(c["strength"])
    for o in res.values():
        o["secs_per_label"] = round(o.pop("secs") / max(o["n"], 1), 2)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--models", default=DEFAULT)
    ap.add_argument("--out")
    a = ap.parse_args()
    ch, cs = cases(a.n, a.seed)
    print(f"{a.n} medicines x {len(LEVELS)} damage levels, seed {a.seed}\n")
    all_res = {}
    for m in a.models.split(","):
        try:
            all_res[m] = score(m, ch, cs)
        except Exception as e:                                                  # a model this account cannot call is reported, not hidden
            all_res[m] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            print(f"{m}: FAILED {all_res[m]['error']}")
            continue
        print(m)
        for lv, o in all_res[m].items():
            print(f"  {lv:<9} top-1 {o['top1']:>3}/{o['n']}  top-3 {o['top3']:>3}/{o['n']}  strength {o['strength_right']:>3}/{o['n']}  extras {o['extras']:>3}  nothing {o['nothing']:>2}  {o['secs_per_label']}s each")
    if a.out:
        json.dump({"n": a.n, "seed": a.seed, "results": all_res}, open(a.out, "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
