"""Readings over time (blood pressure, sugar, INR ...), kept in the circle's graph next to the medicine entries so one query can put them side by side.

  (:Measurement {id, kind, value, unit, at, by, note})-[:FOR]->(:Person)

The app stores what a carer typed and draws it. It does not say whether a value is good or bad, does not compare it with a "normal" range and does not
say what a change in a reading means. The only check is for typing slips: a value that no human body could have (a systolic pressure of 1200) is
refused. For a medicine, `care_trend` lines the readings up with the dates that medicine's entry changed and reports plain arithmetic (the mean
before and after, and how many readings) so a prescriber can see the sequence at a glance."""
from __future__ import annotations

from typing import Optional

from .db import new_id, norm, now_ms

H = 3_600_000
D = 24 * H
# kind -> (label, allowed units, plausible range in the FIRST unit). Ranges only catch slips of the keyboard; they are not clinical ranges.
KINDS = {
    "bp_systolic": ("Blood pressure, top number", ("mmHg",), (40, 300)),
    "bp_diastolic": ("Blood pressure, bottom number", ("mmHg",), (20, 200)),
    "heart_rate": ("Pulse", ("bpm",), (20, 250)),
    "glucose": ("Blood sugar", ("mg/dL", "mmol/L"), (10, 1500)),
    "inr": ("INR", ("ratio",), (0.5, 15)),
    "weight": ("Weight", ("kg", "lb"), (1, 400)),
    "temperature": ("Temperature", ("C", "F"), (25, 115)),
    "spo2": ("Oxygen saturation", ("%",), (30, 100)),
    "tsh": ("Thyroid (TSH)", ("mIU/L",), (0.001, 500)),
}
PLAUSIBLE_ALT = {("glucose", "mmol/L"): (0.5, 85), ("weight", "lb"): (2, 900), ("temperature", "F"): (77, 115), ("temperature", "C"): (25, 46)}


def _range(kind: str, unit: str) -> tuple[float, float]:
    return PLAUSIBLE_ALT.get((kind, unit), KINDS[kind][2])


class CareTrackMixin:
    async def care_measure(self, person: str, kind: str, value: float, unit: str = "", at: Optional[int] = None, note: str = "") -> dict:
        """Record one reading a carer took or was told. Refused only when the number cannot be a real reading (a typing slip)."""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {sorted(KINDS)}")
        label, units, _ = KINDS[kind]
        unit = unit or units[0]
        if unit not in units:
            raise ValueError(f"{label} is recorded in {' or '.join(units)}")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError("the reading must be a number") from None
        lo, hi = _range(kind, unit)
        if not (lo <= v <= hi) or v != v:
            raise ValueError(f"{v:g} {unit} does not look like a real {label.lower()} reading: check for a typing slip")
        t = now_ms() if at is None else int(at)
        if t > now_ms() + H:
            raise ValueError("a reading cannot be from the future")
        mid = new_id("meas")
        await self._q(
            """MERGE (p:Person {id:$p}) ON CREATE SET p.role='patient'
               CREATE (m:Measurement {id:$id, kind:$k, value:$v, unit:$u, at:$t, by:$by, note:$n})-[:FOR]->(p)""",
            {"p": norm(person), "id": mid, "k": kind, "v": v, "u": unit, "t": t, "by": norm(self.agent), "n": note[:120]})
        return {"id": mid, "kind": kind, "value": v, "unit": unit, "at": t}

    async def care_measures(self, person: str, kind: str = "", limit: int = 200) -> list[dict]:
        """Readings, newest first. Optional `kind` filter."""
        rows = await self._q(
            """MATCH (m:Measurement)-[:FOR]->(:Person {id:$p}) WHERE $k = '' OR m.kind = $k
               RETURN m.id, m.kind, m.value, m.unit, m.at, m.by, m.note ORDER BY m.at DESC LIMIT $n""",
            {"p": norm(person), "k": kind, "n": max(1, min(int(limit), 1000))}, scope="read")
        return [dict(id=r[0], kind=r[1], label=KINDS.get(r[1], (r[1],))[0], value=r[2], unit=r[3], at=r[4], by=r[5], note=r[6]) for r in rows]

    async def care_forget_measure(self, measure_id: str) -> dict:
        rows = await self._q("MATCH (m:Measurement {id:$id}) DETACH DELETE m RETURN 1", {"id": measure_id})
        if not rows:
            raise KeyError(measure_id)
        return {"removed": measure_id}

    async def care_trend(self, person: str, kind: str, drug: str = "", window_days: float = 14, now: Optional[int] = None) -> dict:
        """The readings of one kind with the dates that `drug`'s entry changed marked on the same timeline. For each change: how many readings and
        the plain mean in the `window_days` before and after it. Arithmetic over what was typed, nothing more."""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {sorted(KINDS)}")
        t = now_ms() if now is None else now
        series = sorted(await self.care_measures(person, kind, 1000), key=lambda r: r["at"])
        units = sorted({r["unit"] for r in series})
        changes = []
        if drug:
            rows = await self._q(
                """MATCH (x:Dose {drug:$d, status:'confirmed'})-[:FOR]->(:Person {id:$p}) RETURN x.id, x.action, x.dose_text, x.freq_text, x.valid_from ORDER BY x.valid_from""",
                {"d": norm(drug), "p": norm(person)}, scope="read")
            w = window_days * D
            for did, action, dose, freq, at in rows:
                before = [r["value"] for r in series if at - w <= r["at"] < at]
                after = [r["value"] for r in series if at <= r["at"] <= min(at + w, t)]
                mean = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
                changes.append({"dose": did, "at": at, "action": action, "text": f"{dose} {freq}".strip(), "before": {"n": len(before), "mean": mean(before)},
                                "after": {"n": len(after), "mean": mean(after)}})
        return {"kind": kind, "label": KINDS[kind][0], "units": units, "series": series, "drug": norm(drug), "window_days": window_days, "changes": changes,
                "note": "Shown as recorded. The app does not judge a reading or say what a change means: bring this to the prescriber."}
