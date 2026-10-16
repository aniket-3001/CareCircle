"""Appointments, conditions and allergies for the person cared for, kept in the circle's graph beside the medicines.

  (:Appointment {id, title, at, place, who, bring, status, by, created})-[:FOR]->(:Person)     who = the carer taking them
  (:Condition {id, name, by, at})-[:FOR]->(:Person)                                            why a medicine is taken, as the family states it
  (:Allergy {id, text, drug, by, at})-[:FOR]->(:Person)                                        drug = the generic name it resolved to, if any

Nothing here gives advice. An appointment is a date and who goes. A condition is a label the family typed. An allergy is cross-checked against
the medicines on record and a hit says "an allergy is recorded for X: check with the prescriber", never "stop" and never "safe".
A past appointment is not deleted: it reads as "done" when looked at (lazy expiry), so the history keeps it."""
from __future__ import annotations

import asyncio
from typing import Optional

from .db import new_id, norm, now_ms
from .textcheck import fit

H = 3_600_000
# A short, hand-written list of common allergy groups -> medicines that belong to them. Deliberately small and labelled as such: a miss is possible,
# which is why a hit is a prompt to ask, and the absence of a hit is never shown as "safe".
ALLERGY_GROUPS = {
    "penicillin": ("amoxicillin", "ampicillin", "penicillin v", "penicillin g", "piperacillin", "flucloxacillin", "dicloxacillin"),
    "sulfa": ("sulfamethoxazole", "sulfasalazine", "sulfadiazine"),
    "nsaid": ("ibuprofen", "naproxen", "diclofenac", "acetylsalicylic acid", "aspirin", "ketorolac", "celecoxib", "indomethacin"),
    "aspirin": ("acetylsalicylic acid", "aspirin"),
    "statin": ("atorvastatin", "simvastatin", "rosuvastatin", "pravastatin", "lovastatin"),
    "macrolide": ("clarithromycin", "azithromycin", "erythromycin"),
    "ace inhibitor": ("lisinopril", "enalapril", "ramipril", "captopril"),
}


class CarePlanMixin:
    # ------------------------------------------------------------------ appointments
    async def care_appoint(self, person: str, title: str, at: int, place: str = "", who: str = "", bring: str = "") -> dict:
        title = fit(title, 80, "the title")
        place, bring = fit(place, 100, "the place"), fit(bring, 200, "what to bring")
        who = fit(who, 40, "who goes")
        if not title:
            raise ValueError("an appointment needs a title")
        if at < now_ms() - 366 * 24 * H or at > now_ms() + 5 * 366 * 24 * H:
            raise ValueError("that date is not within a sensible range")
        aid = new_id("appt")
        await self._q(
            """MERGE (p:Person {id:$p}) ON CREATE SET p.role='patient'
               CREATE (a:Appointment {id:$id, title:$t, at:$at, place:$pl, who:$w, bring:$b, status:'planned', by:$by, created:$c})-[:FOR]->(p)""",
            {"p": norm(person), "id": aid, "t": title, "at": int(at), "pl": place, "w": norm(who), "b": bring, "by": norm(self.agent), "c": now_ms()})
        return {"id": aid}

    async def care_appointments(self, person: str, now: Optional[int] = None) -> list[dict]:
        """Upcoming first (soonest first), then past ones, newest first. A past planned appointment reads as done: nothing is rewritten."""
        t = now_ms() if now is None else now
        rows = await self._q("MATCH (a:Appointment)-[:FOR]->(:Person {id:$p}) RETURN a.id, a.title, a.at, a.place, a.who, a.bring, a.status, a.by ORDER BY a.at",
                             {"p": norm(person)}, scope="read")
        out = [dict(id=r[0], title=r[1], at=r[2], place=r[3], who=r[4], bring=r[5], by=r[7],
                    status=("cancelled" if r[6] == "cancelled" else "done" if r[2] < t else "upcoming")) for r in rows]
        return sorted([x for x in out if x["status"] == "upcoming"], key=lambda x: x["at"]) + sorted([x for x in out if x["status"] != "upcoming"], key=lambda x: -x["at"])

    async def care_appointment_cancel(self, appointment_id: str) -> dict:
        rows = await self._q("MATCH (a:Appointment {id:$id}) SET a.status='cancelled' RETURN 1", {"id": appointment_id})
        if not rows:
            raise KeyError(appointment_id)
        return {"id": appointment_id, "status": "cancelled"}

    async def care_appointment_edit(self, appointment_id: str, title: str = "", at: Optional[int] = None, place: Optional[str] = None,
                                    who: Optional[str] = None, bring: Optional[str] = None) -> dict:
        """Change an appointment's details. Only what is sent changes; who edited it and when is kept."""
        sets, p = ["a.edited_by=$by", "a.edited_at=$now"], {"id": appointment_id, "by": norm(self.agent), "now": now_ms()}
        if title:
            sets.append("a.title=$t"); p["t"] = fit(title, 80, "the title")
        if at is not None:
            if at < now_ms() - 366 * 24 * H or at > now_ms() + 5 * 366 * 24 * H:
                raise ValueError("that date is not within a sensible range")
            sets.append("a.at=$at"); p["at"] = int(at)
        for key, val, cut in (("place", place, 100), ("who", who, 40), ("bring", bring, 200)):
            if val is not None:
                sets.append(f"a.{key}=${key}"); p[key] = (norm(val) if key == "who" else val)[:cut]
        rows = await self._q(f"MATCH (a:Appointment {{id:$id}}) SET {', '.join(sets)} RETURN a.id", p)
        if not rows:
            raise KeyError(appointment_id)
        return {"id": appointment_id}

    async def care_since_visit(self, person: str, appointment_id: str = "", now: Optional[int] = None) -> dict:
        """What to bring to the doctor: every change to the record since the previous appointment (or the last 30 days), the flags now, what no
        carer has yet seen, readings taken in that time, and the questions the carers wrote down. Assembled from the record; nothing is added."""
        t = now_ms() if now is None else now
        appts = await self.care_appointments(person, t)
        target = next((a for a in appts if a["id"] == appointment_id), None) or next((a for a in appts if a["status"] == "upcoming"), None)
        before = [a for a in appts if a["status"] == "done" and (target is None or a["at"] < target["at"])]
        since = before[0]["at"] if before else t - 30 * 24 * H
        changes = await self._q(
            """MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p}) WHERE x.at >= $s
               RETURN x.drug, x.action, x.dose_text, x.freq_text, x.at, x.by, x.source_type ORDER BY x.at DESC""", {"p": norm(person), "s": since}, scope="read")
        meas = await self._q("MATCH (m:Measurement)-[:FOR]->(:Person {id:$p}) WHERE m.at >= $s RETURN m.kind, m.value, m.unit, m.at ORDER BY m.at", {"p": norm(person), "s": since}, scope="read")
        check, div, allergies = await asyncio.gather(self.care_check(person), self.care_divergence(person, t), self.care_allergy_check(person))
        return {"appointment": target, "since": since,
                "changes": [dict(drug=r[0], action=r[1], dose_text=r[2], freq_text=r[3], at=r[4], by=r[5], source=r[6]) for r in changes],
                "readings": [dict(kind=r[0], value=r[1], unit=r[2], at=r[3]) for r in meas],
                "flags": [{"drugs": f["drugs"], "level": f["level"], "source": f["source"]} for f in check["direct"] if f["level"] != "unknown"] +
                         [{"path": f.get("path"), "source": f.get("source", "FDA CYP table")} for f in check["enzyme_paths"]],
                "unseen": {c: v["unacknowledged"] for c, v in div["carers"].items() if v["unacknowledged"]},
                "allergy_hits": allergies["hits"], "regimen": check["regimen"], "judgement": check["judgement"],
                "note": "Assembled from the record for a conversation with the prescriber or pharmacist. It is not advice."}

    # ------------------------------------------------------------------ conditions and allergies
    async def care_condition_add(self, person: str, name: str) -> dict:
        name = fit(name, 80, "a condition")
        if not name:
            raise ValueError("a condition needs a name")
        cid = new_id("cond")
        await self._q("MERGE (p:Person {id:$p}) ON CREATE SET p.role='patient' CREATE (:Condition {id:$id, name:$n, by:$by, at:$t})-[:FOR]->(p)",
                      {"p": norm(person), "id": cid, "n": name, "by": norm(self.agent), "t": now_ms()})
        return {"id": cid}

    async def care_allergy_add(self, person: str, text: str) -> dict:
        text = fit(text, 80, "the text")
        if not text:
            raise ValueError("an allergy needs a name")
        from .care import checker
        cands = await asyncio.to_thread(checker().resolve, text, 1)
        drug = cands[0]["name"] if cands and cands[0]["score"] >= 0.9 else ""
        aid = new_id("alg")
        await self._q("MERGE (p:Person {id:$p}) ON CREATE SET p.role='patient' CREATE (:Allergy {id:$id, text:$t, drug:$d, by:$by, at:$n})-[:FOR]->(p)",
                      {"p": norm(person), "id": aid, "t": text, "d": drug, "by": norm(self.agent), "n": now_ms()})
        return {"id": aid, "resolved_to": drug}

    async def care_profile(self, person: str) -> dict:
        conds = await self._q("MATCH (c:Condition)-[:FOR]->(:Person {id:$p}) RETURN c.id, c.name, c.by ORDER BY c.at", {"p": norm(person)}, scope="read")
        alg = await self._q("MATCH (a:Allergy)-[:FOR]->(:Person {id:$p}) RETURN a.id, a.text, a.drug, a.by ORDER BY a.at", {"p": norm(person)}, scope="read")
        return {"conditions": [dict(id=r[0], name=r[1], by=r[2]) for r in conds], "allergies": [dict(id=r[0], text=r[1], drug=r[2], by=r[3]) for r in alg]}

    async def care_profile_edit(self, item_id: str, text: str) -> dict:
        """Reword a condition or an allergy. An allergy is matched to a medicine name again, so the cross-check follows the new wording."""
        text = fit(text, 80, "the text")
        if not text:
            raise ValueError("it needs some text")
        rows = await self._q("MATCH (n) WHERE (n:Condition OR n:Allergy) AND n.id = $id RETURN labels(n)[0]", {"id": item_id})
        if not rows:
            raise KeyError(item_id)
        if rows[0][0] == "Condition":
            await self._q("MATCH (n:Condition {id:$id}) SET n.name=$t", {"id": item_id, "t": text})
            return {"id": item_id, "resolved_to": ""}
        from .care import checker
        cands = await asyncio.to_thread(checker().resolve, text, 1)
        drug = cands[0]["name"] if cands and cands[0]["score"] >= 0.9 else ""
        await self._q("MATCH (n:Allergy {id:$id}) SET n.text=$t, n.drug=$d", {"id": item_id, "t": text, "d": drug})
        return {"id": item_id, "resolved_to": drug}

    async def care_profile_remove(self, item_id: str) -> dict:
        rows = await self._q("MATCH (n) WHERE (n:Condition OR n:Allergy) AND n.id = $id DETACH DELETE n RETURN 1", {"id": item_id})
        if not rows:
            raise KeyError(item_id)
        return {"removed": item_id}

    async def care_allergy_check(self, person: str) -> dict:
        """Recorded allergies against the medicines on record: an exact generic name, or a medicine in a common group (short hand-written list).
        A hit is a prompt to ask the prescriber. No hit is NOT a statement that nothing is wrong."""
        prof = await self.care_profile(person)
        reg = await self.care_regimen(person)
        hits = []
        for a in prof["allergies"]:
            text = norm(a["text"])
            group = next((m for g, m in ALLERGY_GROUPS.items() if g in text), ())
            for r in reg:
                if r["drug"] == a["drug"] or r["drug"] in group or r["drug"] in text:
                    hits.append({"allergy": a["text"], "drug": r["drug"], "entry": r["id"],
                                 "why": "the exact medicine" if r["drug"] == a["drug"] or r["drug"] in text else f"a {next(g for g, m in ALLERGY_GROUPS.items() if g in text)} medicine (short built-in list)"})
        return {"hits": hits, "allergies": len(prof["allergies"]), "note": "A hit means ask the prescriber or pharmacist. No hit does not mean there is no problem: the list of groups is short."}
