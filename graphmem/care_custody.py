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

    async def care_handover(self, person: str, text: str) -> dict:
        text = " ".join(text.split())[:400]
        if not text:
            raise ValueError("a handover note needs some text")
        hid = new_id("hand")
        await self._q("CREATE (:Handover {id:$id, person:$p, text:$t, by:$by, at:$at})", {"id": hid, "p": norm(person), "t": text, "by": norm(self.agent), "at": now_ms()})
        return {"id": hid}

    async def care_handovers(self, person: str, limit: int = 30) -> list[dict]:
        rows = await self._q("MATCH (h:Handover {person:$p}) RETURN h.id, h.text, h.by, h.at ORDER BY h.at DESC LIMIT $n", {"p": norm(person), "n": max(1, min(int(limit), 200))}, scope="read")
        return [dict(id=r[0], text=r[1], by=r[2], at=r[3]) for r in rows]
