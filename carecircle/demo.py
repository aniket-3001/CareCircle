"""Golden demo circle: fully synthetic, deterministic, replayable. One call builds a fresh circle for 'Asha' (the person cared for)
with two carers, a baseline regimen, and returns the keys. The interesting moment (a new clarithromycin label) is left for the
presenter to add through the photo path, so the audience sees the whole chain: photo -> verified quote -> confirm -> conflict ->
a carer who has not been told -> reminder."""
from __future__ import annotations

import io
import uuid

from PIL import Image, ImageDraw, ImageFont

PERSON = "asha"
BASELINE = [("metformin", "500 mg", "twice daily with food"), ("amlodipine", "5 mg", "once daily"),
            ("atorvastatin", "20 mg", "at bedtime")]
CARERS = ("ravi", "meena")


def label_png(drug: str = "Clarithromycin 500 mg tablets", sig: str = "Take ONE tablet twice daily for 7 days") -> bytes:
    """A synthetic pharmacy label (all fictional)."""
    img = Image.new("RGB", (720, 330), "white")
    d = ImageDraw.Draw(img)
    try:
        f, fb = ImageFont.truetype("arial.ttf", 24), ImageFont.truetype("arialbd.ttf", 28)
    except OSError:
        f = fb = None
    d.rectangle([8, 8, 712, 322], outline="#888", width=3)
    for i, (t, b) in enumerate([("DEMO PHARMACY   Rx 00481", False), ("Patient: Asha (synthetic)", False), (drug, True), (sig, False),
                                ("Qty 14   Refills 0   Dr. Example", False)]):
        d.text((28, 24 + i * 56), t, fill="black", font=fb if b else f)
    buf = io.BytesIO(); img.save(buf, "PNG")
    return buf.getvalue()


async def start(gm, prefix: str = "demo") -> dict:
    """Fresh circle + two carer agents with keys, baseline regimen acknowledged by both carers."""
    circle = f"{prefix}-{uuid.uuid4().hex[:8]}"
    agents = {c: f"{c}-{circle[-8:]}" for c in CARERS}          # agent ids are global in the control graph: make them unique per circle
    keys = {}
    for c, a in agents.items():
        await gm.grant(a, circle, ("read", "write"))
        keys[c] = await gm.issue_key(a)
    ravi, meena = gm.open(agents["ravi"], circle), gm.open(agents["meena"], circle)
    ids = []
    for drug, dose, freq in BASELINE:
        ids.append((await ravi.care_record(PERSON, drug, dose_text=dose, freq_text=freq, source_type="typed"))["id"])
    for i in ids:
        await meena.care_ack(i)
    await meena.care_record(PERSON, "vitamin d", dose_text="1000 iu", freq_text="once daily")      # makes meena a known carer
    return {"circle": circle, "person": PERSON, "agents": agents, "keys": keys}
