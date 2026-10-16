"""Follow-ups: a short checklist drawn from the record, that a carer approves before anything is created.

(:Followup {id, person, key, text, kind, status, by, at, done_by, done_at})-[:FOR]->(:Person)
(:Followup)-[:BASIS]->(:Dose)       the entries the follow-up was written from

The record suggests (flagged pairs, a carer who has not seen a medicine, a recent change, an allergy hit); a person ticks the ones they want; only then
are they written. A follow-up is stale when an entry it rests on has since been replaced or stopped, found by walking BASIS to the entry's validity,
the same way the engine's plans notice an outdated input. Wording is "ask" or "tell", never what to take: nothing here is advice."""
from __future__ import annotations

import asyncio
from typing import Optional

from .db import new_id, norm, now_ms

DAY = 86_400_000


class CareFollowupsMixin:
    async def care_followup_suggest(self, person: str, now: Optional[int] = None) -> list[dict]:
        """Suggested follow-ups from the record as it is now, minus any already on the list. Read-only: nothing is written until a person approves."""
        t = now_ms() if now is None else now
        p = norm(person)
        check, div, allergies, have = await asyncio.gather(
            self.care_check(person), self.care_divergence(person), self.care_allergy_check(person), self._followup_keys(p))
        by_drug = {r["drug"]: r["id"] for r in check["regimen"]}
        out: list[dict] = []

        def add(key: str, kind: str, text: str, drugs: list[str]) -> None:
            if key not in have and not any(o["key"] == key for o in out):
                out.append({"key": key, "kind": kind, "text": text, "basis": [by_drug[d] for d in drugs if d in by_drug]})

        pairs = [tuple(sorted(x["drugs"])) for x in check["direct"]] + [tuple(sorted((x["x"], x["y"]))) for x in check["enzyme_paths"]]
        for a, b in sorted(set(pairs)):
            add(f"pair|{a}|{b}", "prescriber", f"Ask the prescriber or pharmacist about {a.title()} and {b.title()} together", [a, b])
        for hit in allergies["hits"]:
            add(f"allergy|{hit['drug']}", "prescriber", f"Ask the prescriber about the recorded {hit['allergy']} allergy and {hit['drug'].title()}", [hit["drug"]])
        for carer, v in sorted(div["carers"].items()):
            for u in v["unacknowledged"]:
                add(f"unseen|{carer}|{u['drug']}", "carer", f"Make sure {carer.title()} has seen {u['drug'].title()}", [u["drug"]])
        for r in check["regimen"]:
            if t - r["since"] <= 7 * DAY:
                add(f"new|{r['drug']}", "pharmacist", f"Tell the pharmacist about {r['drug'].title()} {r['dose_text']}".strip(), [r["drug"]])
        return out

    async def _followup_keys(self, p: str) -> set[str]:
        rows = await self._q("MATCH (f:Followup {person:$p}) WHERE f.status <> 'dismissed' RETURN f.key", {"p": p}, scope="read")
        return {r[0] for r in rows}

    async def care_followup_add(self, person: str, items: list) -> dict:
        """Write the follow-ups a person approved (each one: key, text, kind, basis = entry ids). A key already on the list is not added twice."""
        if not isinstance(items, list) or not items or len(items) > 20:
            raise ValueError("send between 1 and 20 follow-ups")
        p = norm(person)
        added = []
        for it in items:
            key, text = str(it.get("key", ""))[:120], " ".join(str(it.get("text", "")).split())[:200]
            if not key or not text:
                raise ValueError("each follow-up needs a key and text")
            kind = it.get("kind") if it.get("kind") in ("prescriber", "pharmacist", "carer", "other") else "other"
            fid = new_id("fup")
            rows = await self._q(
                """MERGE (q:Person {id:$p}) ON CREATE SET q.role='patient'
                   WITH q OPTIONAL MATCH (e:Followup {person:$p, key:$k}) WHERE e.status <> 'dismissed'
                   WITH q, e WHERE e IS NULL
                   CREATE (f:Followup {id:$id, person:$p, key:$k, text:$t, kind:$kind, status:'open', by:$by, at:$now})-[:FOR]->(q)
                   RETURN f.id""",
                {"p": p, "k": key, "id": fid, "t": text, "kind": kind, "by": norm(self.agent), "now": now_ms()})
            if not rows:
                continue
            for did in [str(b) for b in it.get("basis", [])][:6]:
                await self._q("MATCH (f:Followup {id:$f}), (x:Dose {id:$d})-[:FOR]->(:Person {id:$p}) MERGE (f)-[:BASIS]->(x)", {"f": fid, "d": did, "p": p})
            added.append(fid)
        return {"added": added, "skipped": len(items) - len(added)}

    async def care_followups(self, person: str) -> list[dict]:
        """The list, open first. `stale` means an entry it was written from has since been replaced or stopped: look again before doing it."""
        rows = await self._q(
            """MATCH (f:Followup {person:$p})
               OPTIONAL MATCH (f)-[:BASIS]->(x:Dose)
               WITH f, count(x) AS n, sum(CASE WHEN x.valid_to IS NULL THEN 0 ELSE 1 END) AS gone
               RETURN f.id, f.text, f.kind, f.status, f.by, f.at, f.done_by, f.done_at, n, gone
               ORDER BY CASE f.status WHEN 'open' THEN 0 ELSE 1 END, f.at DESC""", {"p": norm(person)}, scope="read")
        return [dict(id=r[0], text=r[1], kind=r[2], status=r[3], by=r[4], at=r[5], done_by=r[6], done_at=r[7], stale=r[3] == "open" and int(r[9] or 0) > 0)
                for r in rows if r[3] != "dismissed"]

    async def care_followup_done(self, followup_id: str, dismiss: bool = False) -> dict:
        """Mark a follow-up done (or dismissed). Who and when are kept."""
        st = "dismissed" if dismiss else "done"
        rows = await self._q("MATCH (f:Followup {id:$id}) WHERE f.status = 'open' SET f.status=$st, f.done_by=$by, f.done_at=$t RETURN f.id",
                             {"id": followup_id, "st": st, "by": norm(self.agent), "t": now_ms()})
        if not rows:
            raise KeyError(followup_id)
        return {"id": followup_id, "status": st}
