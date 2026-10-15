"""Care Circle operations, mixed into TenantMemory. One tenant graph = one circle (a person being cared for + their carers).

  (:Person {id, role})   (:Dose {id, drug, dose_text, freq_text, valid_from, valid_to, cur, action, status, source_type, quote, by, at})
  (Dose)-[:FOR]->(Person)   (Dose)-[:OF]->(Drug)   (Dose)-[:SUPERSEDES]->(Dose)   (Carer)-[:ACKED {at}]->(Dose)
  (:Give {key, person, drug, slot, by, at})                 unique key = one dose slot, claimed atomically
  (:Nudge {key, at})                                        unique key = a reminder is never produced twice

The tool records and cross-checks. It never produces dosing advice: `dose_text`/`freq_text` are quoted strings, never parsed or computed.
Interaction flags come from the shared reference graph (carecircle.checks) and always carry their source.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from carecircle import risk
from carecircle.algos import Algos
from carecircle.checks import Checker
from carecircle.safety import judgement, reword
from carecircle.verify import quote_in_source

from .db import new_id, norm, now_ms

_checker: Optional[Checker] = None
_algos: Optional[Algos] = None
SOURCES = ("typed", "photo", "voice", "document")
H = 3_600_000


def _get_algos() -> Algos:
    global _algos
    if _algos is None:
        _algos = Algos(os.getenv("FALKORDB_HOST", "localhost"), int(os.getenv("FALKORDB_PORT", "6379")))
    return _algos


def checker() -> Checker:
    global _checker
    if _checker is None:
        _checker = Checker(os.getenv("FALKORDB_HOST", "localhost"), int(os.getenv("FALKORDB_PORT", "6379")))
    return _checker


class CareMixin:
    # ------------------------------------------------------------------ record / confirm
    async def care_record(self, person: str, drug: str, action: str = "set", dose_text: str = "", freq_text: str = "",
                          source_type: str = "typed", quote: str = "", source_text: str = "", confirm: bool = True,
                          at: Optional[int] = None) -> dict:
        """A change to what `person` takes. action 'set' (start/change) or 'stop'. The previous current entry is closed and linked
        by SUPERSEDES. If `quote` is given it must occur in `source_text` (the OCR/transcript), else the entry stays UNVERIFIED and
        PENDING until someone confirms it with care_confirm; pending entries never reach the regimen or the checks."""
        if action not in ("set", "stop"):
            raise ValueError("action must be 'set' or 'stop'")
        if source_type not in SOURCES:
            raise ValueError(f"source_type must be one of {SOURCES}")
        verified = quote_in_source(quote, source_text) if quote else source_type == "typed"
        status = "confirmed" if (confirm and verified) else "pending"
        d, ts, did = norm(drug), (now_ms() if at is None else at), new_id("dose")
        rows = await self._q(
            """
            MERGE (p:Person {id:$p}) ON CREATE SET p.role='patient'
            MERGE (dr:Drug {name:$d})
            MERGE (au:Person {id:$by}) ON CREATE SET au.role='carer'
            CREATE (x:Dose {id:$id, drug:$d, dose_text:$dt, freq_text:$ft, valid_from:$ts, cur:false, action:$a, status:$st,
                            source_type:$src, quote:$q, verified:$v, by:$by, at:$ts})
            CREATE (x)-[:FOR]->(p) CREATE (x)-[:OF]->(dr)
            RETURN x.id""",
            {"p": norm(person), "d": d, "id": did, "dt": dose_text[:80], "ft": freq_text[:80], "ts": ts, "a": action, "st": status,
             "src": source_type, "q": quote[:200], "v": verified, "by": norm(self.agent)})
        if status == "confirmed":
            await self._care_activate(did)
        return {"id": rows[0][0], "status": status, "verified": verified,
                "note": None if verified else "quote not found in the source text: confirm manually before it counts"}

    async def _care_activate(self, did: str) -> None:
        """Make a confirmed entry current and close the previous one for the same person+drug."""
        await self._q(
            """
            MATCH (x:Dose {id:$id})-[:FOR]->(p:Person)
            OPTIONAL MATCH (old:Dose {cur:true, drug:x.drug})-[:FOR]->(p) WHERE old.id <> x.id
            FOREACH (_ IN CASE WHEN old IS NULL THEN [] ELSE [1] END |
                     SET old.cur=false, old.valid_to=x.valid_from CREATE (x)-[:SUPERSEDES]->(old))
            SET x.cur = (x.action = 'set'), x.valid_to = CASE WHEN x.action = 'stop' THEN x.valid_from ELSE null END""",
            {"id": did}, checked=True)

    async def care_confirm(self, dose_id: str) -> dict:
        """A person confirms a pending entry (after looking at the quote beside the source). Makes it current."""
        rows = await self._q("MATCH (x:Dose {id:$id, status:'pending'}) SET x.status='confirmed', x.confirmed_by=$by RETURN x.id",
                             {"id": dose_id, "by": norm(self.agent)})
        if not rows:
            raise KeyError(dose_id)
        await self._care_activate(dose_id)
        return {"id": dose_id, "status": "confirmed"}

    # ------------------------------------------------------------------ read
    async def care_regimen(self, person: str, as_of: Optional[int] = None) -> list[dict]:
        """What `person` takes now, or at `as_of` (ms): confirmed 'set' entries valid at that time."""
        t = now_ms() if as_of is None else as_of
        rows = await self._q(
            """MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p})
               WHERE x.action='set' AND x.valid_from <= $t AND (x.valid_to IS NULL OR x.valid_to > $t)
               RETURN x.id, x.drug, x.dose_text, x.freq_text, x.valid_from, x.source_type, x.quote, x.by ORDER BY x.drug""",
            {"p": norm(person), "t": t}, scope="read")
        return [dict(id=r[0], drug=r[1], dose_text=r[2], freq_text=r[3], since=r[4], source=r[5], quote=r[6], by=r[7]) for r in rows]

    async def care_check(self, person: str, as_of: Optional[int] = None) -> dict:
        """Interaction flags for the regimen at `as_of`, from the shared reference graph (sources attached; never 'safe')."""
        reg = await self.care_regimen(person, as_of)
        res = await asyncio.to_thread(checker().check, [r["drug"] for r in reg])
        res["regimen"] = reg
        res["judgement"] = judgement(res)
        return res

    async def care_resolve(self, text: str, n: int = 3) -> list[dict]:
        """Top-n drug name candidates for an OCR/voice string. Nothing is auto-accepted; a person chooses."""
        if self._guard:
            await self._guard("read")
        return await asyncio.to_thread(checker().resolve, text, n)

    # ------------------------------------------------------------------ carers: acknowledgement and staleness
    async def care_ack(self, dose_id: str) -> dict:
        """The calling carer says they have seen this change."""
        rows = await self._q(
            """MATCH (x:Dose {id:$id, status:'confirmed'})
               MERGE (c:Person {id:$me}) ON CREATE SET c.role='carer'
               MERGE (c)-[a:ACKED]->(x) ON CREATE SET a.at=$t
               RETURN x.id""", {"id": dose_id, "me": norm(self.agent), "t": now_ms()})
        if not rows:
            raise KeyError(dose_id)
        return {"id": dose_id, "carer": norm(self.agent)}

    async def care_divergence(self, person: str, now: Optional[int] = None) -> dict:
        """Per carer: confirmed changes they have not acknowledged and a [0,1] divergence score. Older unacknowledged changes count
        more; a change touching a current interaction flag carries that flag's weight, otherwise a base 0.3 (an assumption)."""
        t = now_ms() if now is None else now
        carers = [r[0] for r in await self._q("MATCH (c:Person {role:'carer'}) RETURN c.id ORDER BY c.id", scope="read")]
        changes = await self._q("MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p}) "
                                "RETURN x.id, x.drug, x.action, x.at, x.by ORDER BY x.at", {"p": norm(person)}, scope="read", checked=True)
        flags = await self.care_check(person)
        heavy: dict[str, float] = {}
        for f in flags["direct"]:
            for d in f["drugs"]:
                heavy[d] = max(heavy.get(d, 0), f["weight"])
        for f in flags["enzyme_paths"]:
            left, right = f["path"].split(" -", 1)[0], f["path"].rsplit("SUBSTRATE_OF- ", 1)[-1]
            for d in (left, right):
                heavy[d] = max(heavy.get(d, 0), f["weight"])
        out = {}
        for c in carers:
            acked = {r[0] for r in await self._q("MATCH (:Person {id:$c})-[:ACKED]->(x:Dose) RETURN x.id", {"c": c}, scope="read", checked=True)}
            miss = [(i, d, a, at) for i, d, a, at, by in changes if i not in acked and norm(by) != c]
            ws = [heavy.get(d, 0.3) for _, d, _, _ in miss]
            ages = [(t - at) / H for *_, at in miss]
            out[c] = {"unacknowledged": [{"dose": i, "drug": d, "action": a, "age_hours": round((t - at) / H, 1)} for i, d, a, at in miss],
                      "divergence": risk.divergence(ws, ages) if miss else 0.0}
        worst = max(out, key=lambda k: out[k]["divergence"], default=None)
        return {"carers": out, "most_out_of_date": worst if worst and out[worst]["divergence"] > 0 else None,
                "half_life_hours": risk.HALF_LIFE_HOURS, "weights_are_assumptions": True}

    async def care_nudges(self, person: str, now: Optional[int] = None, remind_after_h: float = 4, escalate_after_h: float = 12) -> list[dict]:
        """Reminders due: unacknowledged changes older than remind_after_h -> 'remind' that carer; older than escalate_after_h ->
        'escalate' to the other carers. Each (kind, carer, dose, recipient) is produced once: claiming it is a conditional write."""
        t = now_ms() if now is None else now
        div = await self.care_divergence(person, t)
        sent = []
        for carer, d in div["carers"].items():
            for u in d["unacknowledged"]:
                todo = [("remind", carer)] if u["age_hours"] >= remind_after_h else []
                if u["age_hours"] >= escalate_after_h:
                    todo += [("escalate", o) for o in div["carers"] if o != carer]
                for kind, to in todo:
                    key = f"{kind}|{carer}|{u['dose']}|{to}"
                    r = await self._q("MERGE (n:Nudge {key:$k}) ON CREATE SET n.at=$t, n.fresh=true "
                                      "WITH n, n.fresh AS fresh SET n.fresh=false RETURN fresh", {"k": key, "t": t}, checked=True)
                    if r[0][0]:
                        facts = {"drug": u["drug"], "hours": u["age_hours"], "carer": carer}
                        tpl = (f"{carer.split(chr(45))[0].capitalize()} has not yet seen the change to {u['drug']} made {u['age_hours']} hours ago. "
                               "Please check with them.") if kind == "escalate" else (
                               f"The change to {u['drug']} made {u['age_hours']} hours ago is not yet acknowledged. Please open it and confirm.")
                        sent.append({"kind": kind, "about_carer": carer, "notify": to, "drug": u["drug"], "age_hours": u["age_hours"],
                                     "message": reword(tpl, facts)})
        return sent

    async def care_reminders(self, person: str, now: Optional[int] = None, remind_after_h: float = 4, escalate_after_h: float = 12) -> list[dict]:
        """Reminders that are due, as a read-only preview: nothing is claimed, so looking at them never uses them up (care_nudges claims and delivers).
        `delivered` says whether the chat bot has already sent that one."""
        t = now_ms() if now is None else now
        div = await self.care_divergence(person, t)
        out = []
        for carer, d in div["carers"].items():
            for u in d["unacknowledged"]:
                todo = [("remind", carer)] if u["age_hours"] >= remind_after_h else []
                if u["age_hours"] >= escalate_after_h:
                    todo += [("escalate", o) for o in div["carers"] if o != carer]
                for kind, to in todo:
                    key = f"{kind}|{carer}|{u['dose']}|{to}"
                    sent = (await self._q("MATCH (n:Nudge {key:$k}) RETURN count(n)", {"k": key}, scope="read"))[0][0] > 0
                    facts = {"drug": u["drug"], "hours": u["age_hours"], "carer": carer}
                    tpl = (f"{carer.split(chr(45))[0].capitalize()} has not yet seen the change to {u['drug']} made {u['age_hours']} hours ago. Please check with them.") if kind == "escalate" else (
                          f"The change to {u['drug']} made {u['age_hours']} hours ago is not yet acknowledged. Please open it and confirm.")
                    out.append({"kind": kind, "about_carer": carer, "notify": to, "drug": u["drug"], "age_hours": u["age_hours"],
                                "message": reword(tpl, facts), "delivered": sent})
        return out

    # ------------------------------------------------------------------ doses given: never twice for one slot
    async def care_give(self, person: str, drug: str, slot: str) -> dict:
        """Record that the calling carer gave `drug` for dose slot `slot` (e.g. '2026-10-16 08:00'). A slot can be claimed once:
        the claim is a single MERGE, so two carers racing get exactly one winner and the other is told who already recorded it."""
        key = f"{norm(person)}|{norm(drug)}|{norm(slot)}"
        rows = await self._q(
            """MERGE (g:Give {key:$k}) ON CREATE SET g.by=$me, g.at=$t, g.person=$p, g.drug=$d, g.slot=$s, g.won=true
               WITH g, g.won AS fresh, g.by AS by, g.at AS at SET g.won=false RETURN fresh, by, at""",
            {"k": key, "me": norm(self.agent), "t": now_ms(), "p": norm(person), "d": norm(drug), "s": norm(slot)})
        fresh, by, at = rows[0]
        if fresh:
            return {"given": True, "slot": slot}
        return {"given": False, "duplicate": True, "already_given_by": by, "at": at,
                "note": "this slot was already recorded; check with them before giving another dose"}

    async def care_gives(self, person: str, limit: int = 50) -> list[dict]:
        rows = await self._q("MATCH (g:Give {person:$p}) RETURN g.drug, g.slot, g.by, g.at ORDER BY g.at DESC LIMIT $n",
                             {"p": norm(person), "n": limit}, scope="read")
        return [dict(drug=r[0], slot=r[1], by=r[2], at=r[3]) for r in rows]

    async def care_drug_info(self, drug: str) -> dict:
        """What public sources say about one medicine on record: the official label's own words (openFDA / DailyMed), the RxNorm identifier, and
        which reference sources cover it. Reading only: the medicine name is the only thing sent out, never a person or a circle."""
        from carecircle import external
        if self._guard:
            await self._guard("read")
        d = norm(drug)
        label, rx = await asyncio.gather(asyncio.to_thread(external.openfda_label, d), asyncio.to_thread(external.rxnorm_ingredients, d))
        ck = checker()
        return {"drug": d, "in_interaction_reference": d in ck.known_names(), "rxnorm": next((r for r in rx if r["name"] == d), None),
                "label": label, "available": external.enabled(),
                "note": "Public reference text, shown as published. It is not advice for this person: ask the prescriber or pharmacist."}

    async def care_people(self) -> dict:
        """Patients and carers known in this circle."""
        rows = await self._q("MATCH (p:Person) RETURN p.id, p.role ORDER BY p.role, p.id", scope="read")
        return {"patients": [r[0] for r in rows if r[1] == "patient"], "carers": [r[0] for r in rows if r[1] == "carer"]}

    async def care_hubs(self, person: str) -> dict:
        """Graph-algorithm views: which medicines sit in most hazards within this regimen, and the PageRank hubs of the reference graph
        (each with the Cypher that ran)."""
        algos = _get_algos()
        reg = await self.care_regimen(person)
        return {"regimen_hubs": await asyncio.to_thread(algos.regimen_hubs, [r["drug"] for r in reg]),
                "global_hubs": await asyncio.to_thread(algos.hub_drugs, 10)}
