"""Care Circle views and data-rights operations, mixed into TenantMemory next to CareMixin.

 care_graph        the circle as a graph (people, entries, medicines, enzymes, interactions) with human-readable metadata per node and edge
 care_timeline     what happened, in order, in plain sentences (who changed what, who saw it, which doses were given)
 care_forget       remove one entry for good and return a receipt that proves it is gone (Lethe-style tombstone: hash, not content)
 care_forget_person remove everything about the person cared for, after typing their name, with a receipt
 care_export_fhir  the regimen as a FHIR R4 Bundle of MedicationStatement resources (free text only: no medicine codes are invented)

Nothing here gives advice: every sentence is built from what was recorded or from a cited reference source.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from carecircle.safety import scan_advice

from .db import new_id, norm, now_ms

H = 3_600_000
ENZYMES = {
    "CYP3A": "A liver and gut enzyme family that clears the largest share of commonly used medicines.",
    "CYP2D6": "A liver enzyme that clears many heart, mood and pain medicines; people differ a lot in how active it is.",
    "CYP2C9": "A liver enzyme that clears many blood-thinning, diabetes and anti-inflammatory medicines.",
    "CYP2C19": "A liver enzyme that clears many stomach-acid, anti-seizure and anti-clotting medicines.",
    "CYP1A2": "A liver enzyme that clears caffeine and a number of other medicines.",
    "CYP2B6": "A liver enzyme involved in clearing several antiviral and mood medicines.",
    "CYP2C8": "A liver enzyme that clears some diabetes and cancer medicines.",
}
SOURCE_WORDS = {"typed": "typed in", "photo": "read from a photo", "voice": "from a voice note", "document": "from a document"}


def iso(ms: Optional[int]) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ms else ""


def ago(ms: Optional[int], now: int) -> str:
    if not ms:
        return ""
    h = (now - ms) / H
    if h < 1:
        return "just now" if h < 0.05 else f"{round(h * 60)} minutes ago"
    if h < 48:
        return f"{h:.1f} hours ago".replace(".0 ", " ")
    return f"{h / 24:.0f} days ago"


def who(agent: Optional[str]) -> str:
    """'ravi-455d702e' -> 'ravi' (demo agents carry a circle suffix)."""
    a = (agent or "").split("-")[0]
    return a.capitalize() if a else "Someone"


def _title(drug: str) -> str:
    return drug[:1].upper() + drug[1:] if drug else drug


class CareViewMixin:
    # ------------------------------------------------------------------ the knowledge graph
    async def care_graph(self, person: str, include_history: bool = True, now: Optional[int] = None) -> dict:
        """Nodes and edges for the circle's graph, each with `meta` ([label, value] rows in plain words), a one-line `summary`, and the
        `cypher` pattern that the structure comes from. Safe to show to anyone in the circle; read scope only."""
        from .care import _get_algos, checker
        t = now_ms() if now is None else now
        p = norm(person)
        rows = await self._q(
            """MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p})
               OPTIONAL MATCH (x)-[:SUPERSEDES]->(o:Dose)
               RETURN x.id, x.drug, x.dose_text, x.freq_text, x.valid_from, x.valid_to, x.cur, x.action, x.source_type, x.quote,
                      x.verified, x.by, x.at, o.id ORDER BY x.at""", {"p": p}, scope="read")
        acks = await self._q("MATCH (c:Person)-[a:ACKED]->(x:Dose)-[:FOR]->(:Person {id:$p}) RETURN c.id, x.id, a.at", {"p": p}, scope="read")
        people = await self.care_people()
        check = await self.care_check(person)
        div = await self.care_divergence(person, t)
        algos = _get_algos()
        hubs = await asyncio.to_thread(algos.hub_drugs, 5000)
        rank = {r["drug"]: (i + 1, r["score"]) for i, r in enumerate(hubs["rows"])}
        drugs_now = [r["drug"] for r in check["regimen"]]
        profile = await asyncio.to_thread(algos.drug_profile, sorted({r[1] for r in rows} | set(drugs_now)))

        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        def node(i, kind, label, summary, meta, cypher, **extra):
            nodes[i] = {"id": i, "kind": kind, "label": label, "summary": summary, "meta": meta, "cypher": cypher, **extra}

        def edge(src, dst, kind, label, summary="", meta=None, **extra):
            edges.append({"id": f"{src}>{kind}>{dst}", "source": src, "target": dst, "kind": kind, "label": label,
                          "summary": summary, "meta": meta or [], **extra})

        node(f"person:{p}", "patient", _title(p), f"{_title(p)} is the person this circle looks after.",
             [["Role", "Person cared for"], ["Medicines on record now", str(len(drugs_now))],
              ["Entries ever recorded", str(len(rows))]], "(:Person {role:'patient'})", current=True)
        for c in people["carers"]:
            d = div["carers"].get(c, {"unacknowledged": [], "divergence": 0})
            unseen = d["unacknowledged"]
            mine = [r for r in rows if norm(r[11]) == c]
            seen = [a for a in acks if a[0] == c]
            node(f"person:{c}", "carer", who(c),
                 f"{who(c)} looks after {_title(p)}. " + (f"{len(unseen)} change(s) not yet acknowledged." if unseen else "Up to date with every change."),
                 [["Role", "Carer"], ["Changes recorded", str(len(mine))], ["Changes acknowledged", str(len(seen))],
                  ["Changes not yet seen", ", ".join(f"{_title(u['drug'])} ({u['age_hours']} h)" for u in unseen) or "none"],
                  ["Out-of-date score", f"{d['divergence']:.2f} of 1 (older unseen changes count more; weights are assumptions)"]],
                 "(:Person {role:'carer'})-[:ACKED]->(:Dose)", current=True, score=d["divergence"])

        dose_by_id = {r[0]: r for r in rows}
        for (did, drug, dt, ft, vf, vt, cur, action, src, quote, verified, by, at, old) in rows:
            if not cur and not include_history:
                continue
            ackers = [who(a[0]) for a in acks if a[1] == did]
            label = f"{_title(drug)} {dt}".strip()
            status = "Current" if cur else ("Stopped" if action == "stop" else "Replaced by a newer entry")
            meta = [["Medicine", _title(drug)], ["Dose as written", dt or "not given"], ["How often as written", ft or "not given"],
                    ["Status", status], ["Recorded by", f"{who(by)}, {iso(at)} ({ago(at, t)})"],
                    ["Source", SOURCE_WORDS.get(src, src)],
                    ["Line it was read from", f"“{quote}”" if quote else "typed directly"],
                    ["Quote checked against the source text", "yes" if verified else "no: a person confirmed it by hand"],
                    ["Acknowledged by", ", ".join(ackers) or "nobody yet"]]
            if vt:
                meta.insert(4, ["Ended", iso(vt)])
            node(f"dose:{did}", "dose" if cur else "dose_old", label,
                 f"{who(by)} {'stopped' if action == 'stop' else 'recorded'} {_title(drug)}{' ' + dt if dt else ''}{' ' + ft if ft else ''}, "
                 f"{SOURCE_WORDS.get(src, src)}, {ago(at, t)}.", meta,
                 "(:Dose)-[:FOR]->(:Person), (:Dose)-[:OF]->(:Drug)", current=bool(cur), at=at, short=dt or ft or "entry")
            edge(f"dose:{did}", f"person:{p}", "for", "is for", f"{label} is on record for {_title(p)}.")
            edge(f"dose:{did}", f"drug:{drug}", "of", "is", "", [], weak=True)
            if norm(by) in {x for x in people["carers"]}:
                edge(f"person:{norm(by)}", f"dose:{did}", "recorded", "recorded", f"{who(by)} recorded this entry.")
            for a in acks:
                if a[1] == did:
                    edge(f"person:{a[0]}", f"dose:{did}", "acked", "acknowledged", f"{who(a[0])} acknowledged this entry, {ago(a[2], t)}.",
                         [["Acknowledged", iso(a[2])]])
            if old and old in dose_by_id and include_history:
                edge(f"dose:{did}", f"dose:{old}", "supersedes", "replaced", f"This entry replaced an older one for {_title(drug)}.")

        all_drugs = sorted({r[1] for r in rows if r[6] or include_history} | set(drugs_now))
        for d in all_drugs:
            pr = profile.get(d, {"levels": {}, "total": 0})
            lv = pr["levels"]
            hubrank = rank.get(d)
            on_now = d in drugs_now
            node(f"drug:{d}", "drug" if on_now else "drug_old", _title(d),
                 f"{_title(d)} is {'on record now' if on_now else 'in the history only'}. The reference data lists {pr['total']} interaction pair(s) for it.",
                 [["Medicine", _title(d)], ["On record now", "yes" if on_now else "no (history only)"],
                  ["Interaction pairs in the reference data", str(pr["total"])],
                  ["Of which major / moderate / minor / unrated",
                   f"{lv.get('major', 0)} / {lv.get('moderate', 0)} / {lv.get('minor', 0)} / {lv.get('unknown', 0)}"],
                  ["Hub rank by PageRank over moderate and major pairs",
                   f"#{hubrank[0]} of {len(rank)} (score {hubrank[1]:.5f}); a higher rank means it sits in more hazard pairs" if hubrank else "not in the hazard graph"],
                  ["Source", "DDInter 2.0 (CC BY-NC-SA 4.0)"]],
                 "(:Drug)-[:INTERACTS]-(:Drug)", current=on_now, rank=hubrank[0] if hubrank else None)

        for f in check["direct"] + check["unrated"]:
            a, b = f["drugs"]
            lvl = f["level"]
            if lvl.lower() == "unknown":
                summ = f"{_title(a)} and {_title(b)} are listed together by the source, but without a severity. Unrated is not the same as safe."
            else:
                summ = (f"{_title(a)} and {_title(b)} are listed as a {lvl.lower()} interaction by {f['source']}. "
                        "This is a flag to discuss with a prescriber or pharmacist.")
            edge(f"drug:{a}", f"drug:{b}", "interacts", lvl, summ,
                 [["Pair", f"{_title(a)} + {_title(b)}"], ["Severity as listed", lvl], ["Source", f["source"]],
                  ["Flag weight used in the combined figure", str(f.get("weight", "not rated"))],
                  ["Graph pattern", "(a:Drug)-[:INTERACTS {level}]-(b:Drug)"]], level=lvl.lower(), weight=f.get("weight", 0))
        for f in check["enzyme_paths"]:
            enz = f"enzyme:{f['enzyme']}"
            if enz not in nodes:
                node(enz, "enzyme", f["enzyme"], ENZYMES.get(f["enzyme"], "A liver enzyme that processes some medicines."),
                     [["What it is", ENZYMES.get(f["enzyme"], "A liver enzyme.")], ["Source", "FDA drug-interaction index table (not exhaustive)"]],
                     "(:Drug)-[:INHIBITS|INDUCES]->(:Enzyme)<-[:SUBSTRATE_OF]-(:Drug)", current=True)
            verb = "slows" if f["relation"] == "INHIBITS" else "speeds up"
            edge(f"drug:{f['x']}", enz, "inhibits" if f["relation"] == "INHIBITS" else "induces", f["relation"].lower(),
                 f"{_title(f['x'])} {verb} {f['enzyme']} ({f['strength']}).",
                 [["Medicine", _title(f["x"])], ["Effect on the enzyme", f"{verb} it ({f['strength']})"], ["Source", "FDA CYP index table"]],
                 weight=f["weight"])
            edge(f"drug:{f['y']}", enz, "substrate", "cleared by",
                 f"{_title(f['y'])} is cleared by {f['enzyme']}.", [["Source", f["source"].split("; ")[-1]]], weight=0)
            nodes[enz]["meta"].append(["Path in this regimen", f["meaning"]])
        # one edge per kind/pair only (several paths can share the enzyme)
        seen, uniq = set(), []
        for e in edges:
            if e["id"] in seen or e["source"] not in nodes or e["target"] not in nodes:
                continue
            seen.add(e["id"])
            uniq.append(e)
        for n in nodes.values():
            assert not scan_advice(n["summary"]), n["summary"]
        return {"person": p, "now": t, "nodes": list(nodes.values()), "edges": uniq, "judgement": check["judgement"],
                "legend": {"patient": "Person cared for", "carer": "Carer", "dose": "Current entry", "dose_old": "Past entry", "drug": "Medicine",
                           "enzyme": "Liver enzyme"},
                "notice": check["notice"]}

    # ------------------------------------------------------------------ timeline
    async def care_timeline(self, person: str, limit: int = 100, now: Optional[int] = None) -> list[dict]:
        """Everything that happened for this person, newest first, as plain sentences."""
        t = now_ms() if now is None else now
        p = norm(person)
        out = []
        for (did, drug, dt, ft, action, src, quote, by, at, status, vf) in await self._q(
                """MATCH (x:Dose)-[:FOR]->(:Person {id:$p})
                   RETURN x.id, x.drug, x.dose_text, x.freq_text, x.action, x.source_type, x.quote, x.by, x.at, x.status, x.valid_from""",
                {"p": p}, scope="read"):
            verb = "stopped" if action == "stop" else "recorded"
            pend = " (waiting for confirmation)" if status == "pending" else ""
            out.append({"at": at, "kind": "stop" if action == "stop" else "record", "dose": did, "who": who(by),
                        "text": f"{who(by)} {verb} {_title(drug)}{' ' + dt if dt else ''}{' ' + ft if ft else ''}, {SOURCE_WORDS.get(src, src)}{pend}.",
                        "quote": quote or "", "when": iso(at), "ago": ago(at, t)})
        for (c, did, drug, at) in await self._q(
                "MATCH (c:Person)-[a:ACKED]->(x:Dose)-[:FOR]->(:Person {id:$p}) RETURN c.id, x.id, x.drug, a.at", {"p": p}, scope="read"):
            out.append({"at": at, "kind": "ack", "dose": did, "who": who(c), "text": f"{who(c)} acknowledged the entry for {_title(drug)}.",
                        "quote": "", "when": iso(at), "ago": ago(at, t)})
        for (drug, slot, by, at) in await self._q("MATCH (g:Give {person:$p}) RETURN g.drug, g.slot, g.by, g.at", {"p": p}, scope="read"):
            out.append({"at": at, "kind": "give", "who": who(by), "text": f"{who(by)} recorded {_title(drug)} as given for the {slot} slot.",
                        "quote": "", "when": iso(at), "ago": ago(at, t)})
        for (rid, kind, at, by) in await self._q("MATCH (r:Receipt) RETURN r.id, r.kind, r.at, r.by", scope="read"):
            out.append({"at": at, "kind": "forget", "who": who(by), "text": f"{who(by)} removed {'an entry' if kind == 'dose' else 'all records of a person'} for good (receipt {rid}).",
                        "quote": "", "when": iso(at), "ago": ago(at, t)})
        out.sort(key=lambda e: -e["at"])
        return out[:limit]

    # ------------------------------------------------------------------ forgetting, with a receipt
    async def care_forget(self, dose_id: str, reason: str = "") -> dict:
        """Remove one entry for good: its dose, frequency, quote, links and acknowledgements are deleted. What stays is a receipt with a
        SHA-256 of what was removed (so it can be matched to a copy someone kept, but does not reveal it), who did it, and when."""
        rows = await self._q("MATCH (x:Dose {id:$id}) RETURN x.drug, x.dose_text, x.freq_text, x.quote, x.by, x.at, x.status",
                             {"id": dose_id}, scope="write")
        if not rows:
            raise KeyError(dose_id)
        drug, dt, ft, quote, by, at, status = rows[0]
        digest = hashlib.sha256(json.dumps([drug, dt, ft, quote, by, at], sort_keys=True).encode()).hexdigest()
        rid, t = new_id("rcpt"), now_ms()
        await self._q("MATCH (x:Dose {id:$id}) OPTIONAL MATCH (n:Nudge) WHERE n.key CONTAINS $id DETACH DELETE n, x", {"id": dose_id})
        await self._q("CREATE (:Receipt {id:$r, kind:'dose', hash:$h, at:$t, by:$by, reason:$why, removed:'dose, quote, links, acknowledgements'})",
                      {"r": rid, "h": digest, "t": t, "by": norm(self.agent), "why": reason[:200]})
        left = (await self._q("MATCH (x:Dose {id:$id}) RETURN count(x)", {"id": dose_id}, scope="read"))[0][0]
        return {"receipt": rid, "forgotten": left == 0, "removed": "the entry, its quote, its links and acknowledgements", "sha256": digest,
                "note": "The hash lets you match this to a copy someone else kept; it does not reveal the content."}

    async def care_forget_person(self, person: str, confirm: str = "") -> dict:
        """Remove everything about the person cared for (entries, dose slots, reminders). Needs the person's name typed as `confirm`."""
        p = norm(person)
        if norm(confirm) != p:
            raise ValueError("type the person's name as `confirm` to remove all records of them")
        doses = await self._q("MATCH (x:Dose)-[:FOR]->(:Person {id:$p}) RETURN x.id", {"p": p}, scope="write")
        ids = [r[0] for r in doses]
        gives = (await self._q("MATCH (g:Give {person:$p}) RETURN count(g)", {"p": p}))[0][0]
        digest = hashlib.sha256(json.dumps([p, sorted(ids)]).encode()).hexdigest()
        await self._q("MATCH (g:Give {person:$p}) DELETE g", {"p": p})
        if ids:
            await self._q("UNWIND $ids AS i MATCH (n:Nudge) WHERE n.key CONTAINS i DELETE n", {"ids": ids})
            await self._q("MATCH (x:Dose)-[:FOR]->(:Person {id:$p}) DETACH DELETE x", {"p": p})
        await self._q("MATCH (q:Person {id:$p, role:'patient'}) DETACH DELETE q", {"p": p})
        rid = new_id("rcpt")
        await self._q("CREATE (:Receipt {id:$r, kind:'person', hash:$h, at:$t, by:$by, reason:'', removed:$rm})",
                      {"r": rid, "h": digest, "t": now_ms(), "by": norm(self.agent), "rm": f"{len(ids)} entries, {gives} dose records"})
        left = (await self._q("MATCH (x:Dose)-[:FOR]->(:Person {id:$p}) RETURN count(x)", {"p": p}, scope="read"))[0][0]
        return {"receipt": rid, "forgotten": left == 0, "removed_entries": len(ids), "removed_dose_records": gives, "sha256": digest}

    async def care_receipts(self) -> list[dict]:
        rows = await self._q("MATCH (r:Receipt) RETURN r.id, r.kind, r.hash, r.at, r.by, r.reason, r.removed ORDER BY r.at DESC", scope="read")
        return [dict(receipt=r[0], kind=r[1], sha256=r[2], at=r[3], when=iso(r[3]), by=who(r[4]), reason=r[5], removed=r[6]) for r in rows]

    # ------------------------------------------------------------------ FHIR export
    async def care_export_fhir(self, person: str) -> dict:
        """The regimen as a FHIR R4 Bundle (collection) of one Patient and MedicationStatement resources. Free text only: this tool does not
        assign RxNorm or other medicine codes, so receiving systems must not treat the text as coded."""
        p = norm(person)
        rows = await self._q(
            """MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p})
               RETURN x.id, x.drug, x.dose_text, x.freq_text, x.valid_from, x.valid_to, x.cur, x.source_type, x.quote, x.verified, x.by
               ORDER BY x.valid_from""", {"p": p}, scope="read")
        entries = [{"fullUrl": f"urn:uuid:patient-{p}", "resource": {"resourceType": "Patient", "id": p, "name": [{"text": _title(p)}],
                                                                       "meta": {"tag": [{"code": "synthetic-or-user-entered"}]}}}]
        for (did, drug, dt, ft, vf, vt, cur, src, quote, verified, by) in rows:
            period = {"start": datetime.fromtimestamp(vf / 1000, tz=timezone.utc).isoformat()}
            if vt:
                period["end"] = datetime.fromtimestamp(vt / 1000, tz=timezone.utc).isoformat()
            res = {"resourceType": "MedicationStatement", "id": did, "status": "active" if cur else "stopped",
                   "medicationCodeableConcept": {"text": _title(drug)}, "subject": {"reference": f"Patient/{p}", "display": _title(p)},
                   "effectivePeriod": period, "informationSource": {"display": who(by)},
                   "dosage": [{"text": " ".join(x for x in (dt, ft) if x) or "not recorded"}],
                   "note": [{"text": f"Source: {SOURCE_WORDS.get(src, src)}." + (f" Quoted line: \"{quote}\"." if quote else "")
                                     + (" Quote verified against the source text." if verified else "")}]}
            entries.append({"fullUrl": f"urn:uuid:{did}", "resource": res})
        return {"resourceType": "Bundle", "type": "collection", "timestamp": datetime.now(timezone.utc).isoformat(),
                "meta": {"tag": [{"code": "free-text-only", "display": "No medicine codes are assigned by Care Circle"}]}, "entry": entries}
