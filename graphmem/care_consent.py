"""Whether the person being cared for knows about this record, and a plain view of it written for them.

  (:Consent {id, status, who, note, by, at})-[:FOR]->(:Person)        status: agreed | declined | not_asked. Newest wins; older ones stay as history.

This is a NOTE in the family's own record of what the person said and who said it. It is not legal consent under any law (in India, the DPDP Act has its own
requirements, which this project does not claim to meet). The patient view is read-only and says what is kept, who can see it, and how to have it removed.
"""
from __future__ import annotations

from typing import Optional

from .db import new_id, norm, now_ms
from .textcheck import fit

STATUS = ("agreed", "declined", "not_asked")
WHO = ("the person themselves", "a guardian or family member on their behalf")


class CareConsentMixin:
    async def care_consent_set(self, person: str, status: str, who: str = "the person themselves", note: str = "") -> dict:
        """Write down whether the person knows this record exists and agrees to it, who answered, and when. Newest entry stands; older ones stay in the history."""
        if status not in STATUS:
            raise ValueError("status is one of: " + ", ".join(STATUS))
        if who not in WHO:
            raise ValueError("who is one of: " + "; ".join(WHO))
        note = fit(note, 200, "the note")
        person = await self._known_person(person)
        cid = new_id("cons")
        last = (await self._q("MATCH (c:Consent)-[:FOR]->(:Person {id:$p}) RETURN max(c.at)", {"p": norm(person)}, scope="read"))[0][0] or 0
        at = max(now_ms(), int(last) + 1)                     # strictly later than the one before it, so "newest wins" never depends on the clock's resolution
        await self._q("MATCH (p:Person {id:$p}) CREATE (:Consent {id:$id, status:$s, who:$w, note:$n, by:$by, at:$t})-[:FOR]->(p)",
                      {"p": norm(person), "id": cid, "s": status, "w": who, "n": note, "by": norm(self.agent), "t": at})
        return {"id": cid, "status": status}

    async def care_consent(self, person: str) -> dict:
        """The current answer (newest) and the history. 'not_asked' when nothing was written down."""
        rows = await self._q("MATCH (c:Consent)-[:FOR]->(:Person {id:$p}) RETURN c.id, c.status, c.who, c.note, c.by, c.at ORDER BY c.at DESC", {"p": norm(person)}, scope="read")
        hist = [{"id": r[0], "status": r[1], "who": r[2], "note": r[3], "by": r[4], "at": r[5]} for r in rows]
        return {"status": hist[0]["status"] if hist else "not_asked", "current": hist[0] if hist else None, "history": hist,
                "note": "A note kept by the family of what the person said. It is not legal consent."}

    async def care_patient_view(self, person: str) -> dict:
        """What this record holds about the person, in plain words, for the person themselves to read: the medicines, who can see them, and how to have it removed."""
        reg = await self.care_regimen(person)
        members = [r[0] for r in await self._q("MATCH (c:Person {role:'carer'}) RETURN c.id ORDER BY c.id", scope="read")]
        consent = await self.care_consent(person)
        return {"person": norm(person),
                "medicines": [{"drug": r["drug"], "dose_text": r["dose_text"], "freq_text": r["freq_text"], "slots": r["slots"], "recorded_by": r["by"]} for r in reg],
                "who_can_see": members,
                "what_is_kept": ["the medicines, strengths and times your family typed or read from labels",
                                 "who recorded each change and when, and which carers have seen it",
                                 "which doses were marked as given, and by whom",
                                 "notes, appointments and allergies your family added"],
                "what_is_not": ["it is not a medical record kept by a doctor or pharmacy", "it does not give advice and does not say any medicine is safe"],
                "your_rights": "The owner of the circle can remove any entry, or everything about you, for good; a receipt remains that something was removed, but not what it said.",
                "consent": consent["current"]}


class CareReviewMixin:
    """What a pharmacist (or anyone) who opened a share link wrote back: a name they typed and a short note, kept in the circle. The name is not verified."""

    async def care_add_review(self, person: str, name: str, note: str, share: str) -> dict:
        """Written by the share service on behalf of a link's owner, never reachable as an operation."""
        name, note = fit(name, 60, "the name"), fit(note, 300, "the note")
        if not name:
            raise ValueError("please type your name")
        rid = new_id("rev")
        await self._q("MATCH (p:Person {id:$p}) CREATE (:Review {id:$id, name:$n, note:$t, share:$s, at:$a})-[:FOR]->(p)",
                      {"p": norm(person), "id": rid, "n": name, "t": note, "s": share, "a": now_ms()})
        return {"id": rid}

    async def care_pharmacist_reviews(self, person: str) -> list[dict]:
        """Notes written back from a share link, newest first. The name is whatever was typed: it is not checked."""
        rows = await self._q("MATCH (r:Review)-[:FOR]->(:Person {id:$p}) RETURN r.id, r.name, r.note, r.at ORDER BY r.at DESC LIMIT 50", {"p": norm(person)}, scope="read")
        return [{"id": r[0], "name": r[1], "note": r[2], "at": r[3], "verified": False} for r in rows]
