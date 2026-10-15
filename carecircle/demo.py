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
    img = Image.new("RGB", (900, 420), "white")
    d = ImageDraw.Draw(img)
    try:
        f, fb = ImageFont.truetype("arial.ttf", 32), ImageFont.truetype("arialbd.ttf", 38)
    except OSError:
        f = fb = None
    d.rectangle([8, 8, 892, 412], outline="#888", width=3)
    for i, (t, b) in enumerate([("DEMO PHARMACY   Rx 00481", False), ("Patient: Asha (synthetic)", False), (drug, True), (sig, False),
                                ("Qty 14   Refills 0   Dr. Example", False)]):
        d.text((32, 28 + i * 74), t, fill="black", font=fb if b else f)
    buf = io.BytesIO(); img.save(buf, "PNG")
    return buf.getvalue()


async def start(gm, prefix: str = "demo") -> dict:
    """Fresh circle + two carer agents with keys, baseline regimen acknowledged by both carers."""
    circle = f"{prefix}-{uuid.uuid4().hex[:8]}"
    agents = {c: f"{c}-{circle[-8:]}" for c in CARERS}          # agent ids are global in the control graph: make them unique per circle
    keys = {}
    for c, a in agents.items():
        await gm.grant(a, circle, ("read", "write", "admin"))
        keys[c] = await gm.issue_key(a)
    ravi, meena = gm.open(agents["ravi"], circle), gm.open(agents["meena"], circle)
    ids = []
    for drug, dose, freq in BASELINE:
        ids.append((await ravi.care_record(PERSON, drug, dose_text=dose, freq_text=freq, source_type="typed"))["id"])
    for i in ids:
        await meena.care_ack(i)
    await meena.care_record(PERSON, "vitamin d", dose_text="1000 iu", freq_text="once daily")      # makes meena a known carer
    return {"circle": circle, "person": PERSON, "agents": agents, "keys": keys}


async def seed_shared(gm, acc) -> None:
    """The two public demo accounts and the circle they share. Idempotent; `reset_shared` rebuilds the circle. Demo accounts are ordinary accounts
    (so sign-in, profile and circles behave exactly as for anyone) whose password is shown on the sign-in page."""
    from .accounts import DEMO_ACCOUNTS, DEMO_PASSWORD, SHARED_CIRCLE
    agents = []
    for email, name in DEMO_ACCOUNTS:
        row = await acc.by_email(email) or await acc.create(email, name, DEMO_PASSWORD, demo=True)
        agents.append(row["agent"])
    if await acc.role(agents[0], SHARED_CIRCLE):
        return
    from graphmem.db import now_ms
    await gm.create_tenant(SHARED_CIRCLE)
    for i, a in enumerate(agents):
        await gm.grant(a, SHARED_CIRCLE, ("read", "write", "admin") if i == 0 else ("read", "write"))
        await acc._q("MATCH (a:Account {agent:$ag}), (t:Tenant {id:$c}) CREATE (a)-[:MEMBER {role:$r, at:$t}]->(t)",
                     {"ag": a, "c": SHARED_CIRCLE, "r": "owner" if i == 0 else "carer", "t": now_ms()})
    await acc._q("MATCH (t:Tenant {id:$c}) SET t.name=\"Asha's circle (demo)\", t.person=$p, t.owner=$o, t.demo=true", {"c": SHARED_CIRCLE, "p": PERSON, "o": agents[0]})
    ravi, meena = gm.open(agents[0], SHARED_CIRCLE), gm.open(agents[1], SHARED_CIRCLE)
    ids = [(await ravi.care_record(PERSON, d, dose_text=dose, freq_text=freq, source_type="typed"))["id"] for d, dose, freq in BASELINE]
    for i in ids:
        await meena.care_ack(i)
    await meena.care_record(PERSON, "vitamin d", dose_text="1000 iu", freq_text="once daily")


async def reset_shared(gm, acc) -> None:
    from .accounts import SHARED_CIRCLE
    await gm.db.drop_tenant(SHARED_CIRCLE)
    await acc._q("MATCH (t:Tenant {id:$c}) DETACH DELETE t", {"c": SHARED_CIRCLE})
    await seed_shared(gm, acc)
