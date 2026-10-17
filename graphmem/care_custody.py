"""Witnessed doses and handover notes: who gave it, who saw it, who told the next carer what.

  (:Watch {key: person|drug})                                  the circle marks a medicine "a second carer should confirm each dose" (the family's rule, not ours)
  (:Give {... witness, witness_at})                            for a watched medicine the dose is recorded as given, then a DIFFERENT carer confirms it
  (:Handover {id, person, text, by, at})                       an append-only note from one carer to the next ("INR was 2.4, next check Monday")

No judgement is made about which medicines need a witness: the family chooses. A dose waiting for its second carer is shown as waiting, never as an error. Handover notes
cannot be edited, only added; the only way one goes is erasing the person (with its receipt)."""
from __future__ import annotations

from .db import new_id, norm, now_ms


class CareCustodyMixin:
    async def care_watch(self, person: str, drug: str, on: bool = True) -> dict:
        key = f"{norm(person)}|{norm(drug)}"
        if on:
            await self._q("MERGE (w:Watch {key:$k}) ON CREATE SET w.by=$by, w.at=$t", {"k": key, "by": norm(self.agent), "t": now_ms()})
        else:
            await self._q("MATCH (w:Watch {key:$k}) DELETE w", {"k": key})
        return {"drug": norm(drug), "watched": on}

    async def care_watched(self, person: str) -> list[str]:
        rows = await self._q("MATCH (w:Watch) WHERE w.key STARTS WITH $p RETURN w.key ORDER BY w.key", {"p": norm(person) + "|"}, scope="read")
        return [r[0].split("|", 1)[1] for r in rows]

    async def care_witness(self, person: str, drug: str, slot: str) -> dict:
        """A carer other than the one who gave the dose confirms they saw it given. Idempotent for the same witness; refused for the giver."""
        from .care import parse_slot
        slot, _ = parse_slot(slot)
        key = f"{norm(person)}|{norm(drug)}|{norm(slot)}"
        rows = await self._q("MATCH (g:Give {key:$k}) RETURN g.by, g.witness", {"k": key}, scope="read")
        if not rows:
            raise KeyError("that dose has not been recorded as given")
        giver, witness = rows[0]
        me = norm(self.agent)
        if me == giver:
            raise ValueError("the carer who gave the dose cannot also be its second carer")
        if witness and witness != me:
            return {"witnessed": True, "by": witness, "note": "someone else already confirmed this dose"}
        await self._q("MATCH (g:Give {key:$k}) SET g.witness=$me, g.witness_at=$t", {"k": key, "me": me, "t": now_ms()})
        return {"witnessed": True, "by": me}

    async def care_entry_notes(self, dose_id: str) -> dict:
        """The notes written about one entry: by agents (labelled "noted by <agent>, unverified") and handover notes addressed to it. They sit beside the entry and are
        NOT part of the record: they never change a dose, a flag, the checklist or the history log. `stale` says the entry has changed since they were written."""
        head = await self._q("MATCH (x:Dose {id:$id}) RETURN x.cur, x.status, x.drug", {"id": dose_id}, scope="read")
        if not head:
            raise KeyError(dose_id)
        cur, status, drug = head[0]
        notes = [dict(id=r[0], kind="agent_note", text=r[1], by=r[2], at=r[3], label=f"noted by {r[2]}, unverified")
                 for r in await self._q("MATCH (e)-[:ABOUT]->(:Dose {id:$id}) WHERE e.content IS NOT NULL AND e.redacted = false RETURN e.id, e.content, e.agent, e.ts", {"id": dose_id}, scope="read")]
        notes += [dict(id=r[0], kind="handover", text=r[1], by=r[2], at=r[3], to=r[4] or None, status=r[5],
                       label=f"handover note from {r[2]}" + (f" to {r[4]}" if r[4] else "") + (", accepted" if r[5] == "accepted" else ""))
                  for r in await self._q("MATCH (h:Handover)-[:ABOUT]->(:Dose {id:$id}) RETURN h.id, h.text, h.by, h.at, coalesce(h.to, ''), coalesce(h.status, 'note')", {"id": dose_id}, scope="read")]
        notes.sort(key=lambda n: n["at"])
        reminders = [dict(id=r[0], kind=r[1], to=r[2], at=r[3], channels=list(r[4] or []))
                     for r in await self._q("MATCH (r:Reminder)-[:ABOUT]->(:Dose {id:$id}) RETURN r.id, r.kind, r.to, r.at, r.channels ORDER BY r.at", {"id": dose_id}, scope="read")]
        return {"dose_id": dose_id, "drug": drug, "status": status, "stale": not bool(cur), "notes": notes, "reminders": reminders,
                "note": "Notes are written about this entry by agents and carers. They are not part of the record: they do not change a dose, a flag or the history, and an agent's note is not confirmed by anyone."}

    async def care_handover(self, person: str, text: str, about: str = "", to: str = "") -> dict:
        """A note from this carer to the next. `about` attaches it to the entry it concerns (the next carer who opens the entry sees it). `to` addresses it to one named
        carer of this circle, who can accept it (care_handover_accept); it is shown as stale if the entry it is about changes afterwards."""
        from .textcheck import fit
        text = fit(text, 400, "a handover note")
        if not text:
            raise ValueError("a handover note needs some text")
        hid = new_id("hand")
        if about and not await self._q("MATCH (x:Dose {id:$a})-[:FOR]->(:Person {id:$p}) RETURN x.id", {"a": about, "p": norm(person)}, scope="read", checked=True):
            raise ValueError("a handover note can be about an entry of this person; no such entry here")
        to = norm(to)
        if to:
            if to == norm(self.agent):
                raise ValueError("a handover note is for someone else: name another carer")
            have = await self.peer_scopes(to) if self.peer_scopes is not None else {"read"}
            if not ({"read", "write", "admin"} & set(have)):
                raise ValueError(f"{to!r} is not a carer in this circle, so a note cannot be addressed to them")
        await self._q("CREATE (:Handover {id:$id, person:$p, text:$t, by:$by, at:$at, to:$to, status:$st})",
                      {"id": hid, "p": norm(person), "t": text, "by": norm(self.agent), "at": now_ms(), "to": to, "st": "open" if to else "note"})
        if about:                                               # the note is attached to the entry it is about, so the next carer who opens the entry sees it
            await self._q("MATCH (h:Handover {id:$id}), (x:Dose {id:$a}) CREATE (h)-[:ABOUT]->(x)", {"id": hid, "a": about}, checked=True)
        return {"id": hid, **({"about": about} if about else {}), **({"to": to, "status": "open"} if to else {})}

    async def care_handover_accept(self, handover_id: str) -> dict:
        """The carer a note was addressed to accepts it. Only that carer can; accepting twice changes nothing. It records who accepted and when, and says whether the entry
        the note is about has changed since the note was written."""
        rows = await self._q("MATCH (h:Handover {id:$id}) OPTIONAL MATCH (h)-[:ABOUT]->(x:Dose) RETURN h.to, h.status, h.at, x.id, x.cur, x.status", {"id": handover_id}, scope="read")
        if not rows:
            raise KeyError(handover_id)
        to, status, at, xid, cur, xstatus = rows[0]
        me = norm(self.agent)
        if not to:
            raise ValueError("this note was not addressed to anyone, so there is nothing to accept")
        if me != to:
            raise ValueError(f"this note is addressed to {to}; only they can accept it")
        stale = bool(xid) and not bool(cur)
        if status != "accepted":
            await self._q("MATCH (h:Handover {id:$id}) WHERE h.status <> 'accepted' SET h.status='accepted', h.accepted_by=$me, h.accepted_at=$t",
                          {"id": handover_id, "me": me, "t": now_ms()}, checked=True)
        return {"id": handover_id, "status": "accepted", "accepted_by": me, "stale": stale,
                **({"warning": "the entry this note is about has changed since it was written; check the entry before relying on the note"} if stale else {})}

    async def care_handovers(self, person: str, limit: int = 30) -> list[dict]:
        rows = await self._q("MATCH (h:Handover {person:$p}) OPTIONAL MATCH (h)-[:ABOUT]->(x:Dose) "
                             "RETURN h.id, h.text, h.by, h.at, coalesce(h.to, ''), coalesce(h.status, 'note'), h.accepted_by, h.accepted_at, x.id, x.cur, x.drug ORDER BY h.at DESC LIMIT $n",
                             {"p": norm(person), "n": max(1, min(int(limit), 200))}, scope="read")
        return [dict(id=r[0], text=r[1], by=r[2], at=r[3], to=r[4] or None, status=r[5], accepted_by=r[6], accepted_at=r[7],
                     about=r[8], about_drug=r[10], stale=bool(r[8]) and not bool(r[9]), for_me=bool(r[4]) and r[4] == norm(self.agent)) for r in rows]
