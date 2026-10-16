"""Intake on a few hundred rendered medicine labels, through the real pipeline (RapidOCR, then the rule-based reader), at three levels of damage.

  PYTHONPATH=. python bench/intake_bench.py [--n 150] [--seed 7] [--out result.json]

What it measures: for a medicine name and strength drawn from the reference graph, is the right medicine the top suggestion, is it among the top three, is the strength
copied right, and how many wrong extra suggestions appear. What it does NOT measure: accuracy on real photographs. The labels are synthetic (text drawn with common fonts, then
tilted, blurred, shrunk, noised and JPEG-compressed), they carry generic names only, and they hold no brand names, curved bottles, glare or hands. Treat the numbers as a floor
for "does the pipeline read clean printing, and how fast does it degrade", not as a promise about a kitchen counter. Nothing here is a person's data: every name is a public drug name."""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import sys
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FONTS = ["arial.ttf", "times.ttf", "verdana.ttf", "calibri.ttf", "cour.ttf", "tahoma.ttf", "georgia.ttf"]
STRENGTHS = ["5 mg", "10 mg", "20 mg", "25 mg", "40 mg", "50 mg", "100 mg", "250 mg", "500 mg", "1 g", "75 mcg", "150 mg", "0.5 mg", "300 mg"]
FREQS = ["Take one tablet twice daily", "Take 1 tablet once daily", "Take one tablet at bedtime", "Take one capsule every morning", "Take 2 tablets three times a day"]
NOISE = ["Rx only", "Qty 30", "Keep out of reach of children", "Refills: 2", "Store at room temperature", "Dr A. Sample"]
LEVELS = ("clean", "moderate", "harsh")


def font(name: str, size: int):
    for base in (r"C:\Windows\Fonts", "/usr/share/fonts/truetype/msttcorefonts", "/usr/share/fonts/truetype/dejavu"):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def render(rng: random.Random, drug: str, strength: str, level: str) -> bytes:
    f1, f2 = rng.choice(FONTS), rng.choice(FONTS)
    big, small = font(f1, rng.randint(34, 46)), font(f2, rng.randint(22, 28))
    name = rng.choice([drug.title(), drug.upper(), drug])
    lines = [(name, big), (strength + " tablets", big), (rng.choice(FREQS), small), (rng.choice(NOISE), small), (rng.choice(NOISE), small)]
    img = Image.new("RGB", (760, 420), (rng.randint(235, 255), rng.randint(235, 255), rng.randint(225, 250)))
    d = ImageDraw.Draw(img)
    y = 26
    for text, fnt in lines:
        d.text((34, y), text, fill=(rng.randint(0, 40),) * 3, font=fnt)
        y += int(fnt.size * 1.5)
    if level != "clean":
        harsh = level == "harsh"
        img = img.rotate(rng.uniform(-8, 8) if harsh else rng.uniform(-3, 3), expand=True, fillcolor=(240, 240, 235), resample=Image.BICUBIC)
        if harsh:
            img = img.resize((img.width // 2, img.height // 2), Image.BILINEAR).resize((img.width, img.height), Image.BILINEAR)
        img = img.filter(ImageFilter.GaussianBlur(1.6 if harsh else 0.8))
        px = img.load()
        for _ in range(img.width * img.height // (14 if harsh else 60)):
            x, y2 = rng.randrange(img.width), rng.randrange(img.height)
            v = rng.randint(0, 255)
            px[x, y2] = (v, v, v)
        if harsh:
            img = Image.blend(img, Image.new("RGB", img.size, (200, 200, 200)), 0.35)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=35 if level == "harsh" else 60 if level == "moderate" else 92)
    return buf.getvalue()


def norm_strength(s: str) -> str:
    """The number and unit only: OCR punctuation between them ("40:mg", "50.mg") is not a different strength; a lost decimal point ("05mg" for 0.5 mg) is."""
    return re.sub(r"(?<=\d)[\s.:]+(?=[a-zµ])", "", (s or "").lower()).replace(" ", "")


def run(n: int, seed: int) -> dict:
    from carecircle import intake
    from carecircle.checks import Checker
    ch = Checker(os.getenv("FALKORDB_HOST", "localhost"), int(os.getenv("FALKORDB_PORT", "6379")))
    names = sorted({r[0] for r in ch.g.ro_query("MATCH (d:Drug) WHERE size(d.name) >= 5 AND NOT d.name CONTAINS ' ' RETURN d.name").result_set})
    rng = random.Random(seed)
    picks = rng.sample(names, n)
    out = {lv: {"images": 0, "unreadable": 0, "top1": 0, "top3": 0, "strength_right": 0, "strength_blank": 0, "strength_wrong_number": 0, "strength_asked": 0, "extra_proposals": 0, "secs": 0.0} for lv in LEVELS}
    misses: dict[str, list] = {lv: [] for lv in LEVELS}
    wrong_strength: dict[str, list] = {lv: [] for lv in LEVELS}
    for drug in picks:
        strength = rng.choice(STRENGTHS)
        for lv in LEVELS:
            data = render(rng, drug, strength, lv)
            t0 = time.perf_counter()
            src = intake.read_source(data, "label.jpg", "image/jpeg")
            props = intake.rule_proposals(src["text"], ch) if src["status"] == "ok" else []
            o = out[lv]
            o["secs"] += time.perf_counter() - t0
            o["images"] += 1
            o["strength_asked"] += 1
            if not props:
                o["unreadable"] += 1
                misses[lv].append((drug, "nothing proposed"))
                continue
            hit = next((p for p in props if p["drug_candidates"][0]["name"] == drug), None)
            in3 = next((p for p in props if drug in [c["name"] for c in p["drug_candidates"]]), None)
            o["top1"] += hit is not None
            o["top3"] += in3 is not None
            o["extra_proposals"] += len(props) - (1 if in3 else 0)
            got = (hit or in3)
            right = bool(got) and norm_strength(got["dose_text"]) == norm_strength(strength)
            o["strength_right"] += right
            if got and not right:
                o["strength_blank" if not got["dose_text"] else "strength_wrong_number"] += 1
                wrong_strength[lv].append((drug, strength, got["dose_text"], src["text"][:90].replace(chr(10), " / ")))
            if not hit:
                misses[lv].append((drug, props[0]["drug_candidates"][0]["name"]))
    for lv, o in out.items():
        o["secs_per_image"] = round(o.pop("secs") / o["images"], 2)
    return {"n_drugs": n, "seed": seed, "levels": out, "examples_missed": {lv: m[:8] for lv, m in misses.items()},
            "examples_wrong_strength": {lv: m[:8] for lv, m in wrong_strength.items()}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out")
    a = ap.parse_args()
    r = run(a.n, a.seed)
    print(f"{a.n} drugs x {len(LEVELS)} damage levels, seed {a.seed}")
    for lv, o in r["levels"].items():
        n = o["images"]
        print(f"  {lv:<9} top-1 {o['top1']:>3}/{n} ({100 * o['top1'] / n:.0f}%)  top-3 {o['top3']:>3}/{n} ({100 * o['top3'] / n:.0f}%)  "
              f"strength right {o['strength_right']:>3}/{n} (left blank {o['strength_blank']}, a different number {o['strength_wrong_number']})  nothing proposed {o['unreadable']:>3}  wrong extra suggestions {o['extra_proposals']:>3}  {o['secs_per_image']} s/image")
    for lv, m in r["examples_missed"].items():
        if m:
            print(f"  e.g. missed at {lv}: {m[:5]}")
    for lv, m in r["examples_wrong_strength"].items():
        for ex in m[:3]:
            print(f"  wrong strength at {lv}: {ex}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
