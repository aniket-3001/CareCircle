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
import hmac
import os
import secrets
import json
from datetime import datetime, timezone
from typing import Optional

from carecircle.safety import scan_advice

from .db import new_id, norm, now_ms
from .textcheck import plural, product_name, shown_name

H = 3_600_000
_secret_cache: dict = {}


def server_secret() -> bytes:
    """The secret that keys erase receipts when it is set: CC_RECEIPT_SECRET (32 or more characters), or the SecureString parameter named by CC_RECEIPT_SECRET_PARAM,
    read once with the server's own role and kept only in memory. It is never stored in a circle's graph, so a copy of the graph (a backup, a dump) holds the
    receipts but not the key that would let someone test guesses against them. Empty when neither is set."""
    s = os.getenv("CC_RECEIPT_SECRET", "")
    param = os.getenv("CC_RECEIPT_SECRET_PARAM", "")
    if not s and param:
        if param not in _secret_cache:
            import boto3
            _secret_cache[param] = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1")).get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
        s = _secret_cache[param]
    if s and len(s) < 32:
        raise ValueError("the receipt secret must be at least 32 characters")
    return s.encode()


ENZYMES = {
    "CYP3A": "A liver and gut enzyme family that clears the largest share of commonly used medicines.",
    "CYP2D6": "A liver enzyme that clears many heart, mood and pain medicines; people differ a lot in how active it is.",
    "CYP2C9": "A liver enzyme that clears many blood-thinning, diabetes and anti-inflammatory medicines.",
    "CYP2C19": "A liver enzyme that clears many stomach-acid, anti-seizure and anti-clotting medicines.",
    "CYP1A2": "A liver enzyme that clears caffeine and a number of other medicines.",
    "CYP2B6": "A liver enzyme involved in clearing several antiviral and mood medicines.",
    "CYP2C8": "A liver enzyme that clears some diabetes and cancer medicines.",
    "P-gp": "A pump in the gut, liver and kidney walls that pushes some medicines out of cells, which changes how much reaches the blood.",
    "BCRP": "A pump in the gut and liver that pushes some medicines out of cells.",
    "OATP1B1": "A transporter that carries some medicines (many cholesterol medicines among them) from the blood into the liver.",
    "OATP1B3": "A transporter that carries some medicines from the blood into the liver.",
    "OAT1": "A kidney transporter that moves some medicines from the blood into the urine.",
    "OAT3": "A kidney transporter that moves some medicines from the blood into the urine.",
    "OCT2": "A kidney transporter that moves some medicines (metformin among them) from the blood into the urine.",
    "MATE1": "A kidney transporter that moves some medicines out into the urine.",
    "MATE-2K": "A kidney transporter that moves some medicines out into the urine.",
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
    return shown_name(drug)


class CareViewMixin:
    # ------------------------------------------------------------------ the knowledge graph
    async def care_graph(self, person: str, include_history: bool = True, now: Optional[int] = None) -> dict:
        """The circle as a graph: nodes and edges, each with plain-language metadata (read scope).

        Every node and edge carries `meta` ([label, value] rows in plain words), a one-line `summary` and the `cypher` pattern it comes from."""
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
                 f"{who(c)} looks after {_title(p)}. " + (f"{plural(len(unseen), 'change')} not yet acknowledged." if unseen else "Up to date with every change."),
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
                    ["Quote checked against the source text", ("yes" if verified else "no: a person confirmed it by hand") if quote else "not applicable (typed directly)"],
                    ["Acknowledged by", ", ".join(ackers) or "nobody yet"]]
            if vt:
                meta.insert(4, ["Ended", iso(vt)])
            node(f"dose:{did}", "dose" if cur else "dose_old", label,
                 f"{who(by)} {'stopped' if action == 'stop' else 'recorded'} {_title(drug)}{' ' + dt if dt else ''}{' ' + ft if ft else ''}, "
                 f"{SOURCE_WORDS.get(src, src)}, {ago(at, t)}.", meta,
                 "(:Dose)-[:FOR]->(:Person), (:Dose)-[:OF]->(:Drug)", current=bool(cur), at=at, short="stopped" if action == "stop" else (dt or ft or "entry"))
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
                 f"{_title(d)} is {'on record now' if on_now else 'in the history only'}. The reference data lists {plural(pr['total'], 'interaction pair')} for it.",
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
                what = ENZYMES.get(f["enzyme"], "A transporter that moves some medicines in and out of cells." if f.get("target") == "transporter" else "A liver enzyme that processes some medicines.")
                node(enz, "enzyme", f["enzyme"], what,
                     [["What it is", what], ["Source", "FDA drug-interaction tables (not exhaustive)"]],
                     "(:Drug)-[:INHIBITS|INDUCES]->(:Enzyme)<-[:SUBSTRATE_OF]-(:Drug)", current=True)
            verb = "slows" if f["relation"] == "INHIBITS" else "speeds up"
            edge(f"drug:{f['x']}", enz, "inhibits" if f["relation"] == "INHIBITS" else "induces", f["relation"].lower(),
                 f"{_title(f['x'])} {verb} {f['enzyme']} ({f['strength']}).",
                 [["Medicine", _title(f["x"])], ["Effect on the enzyme", f"{verb} it ({f['strength']})"], ["Source", f["source"].split("; ")[0]]],
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
    async def care_history_digest(self, person: str, upto: int = 0) -> dict:
        """A fingerprint of what was written about a person: each entry's fixed fields are chained (hash of the one before + this one), oldest first.
        Write the head hash down (or print it with the doctor's sheet); later, `upto` = that count recomputes the same prefix, and a different hash means an
        earlier entry was changed or removed after the fact. It does not say an entry is true, only that it is unchanged. Marking an entry as a mistake,
        stopping a medicine and a later entry do not change the earlier chain (status and end dates are not part of it)."""
        rows = await self._q(
            """MATCH (x:Dose)-[:FOR]->(:Person {id:$p}) OPTIONAL MATCH (x)-[:VIA]->(pr:Product)
               RETURN x.id, x.drug, coalesce(pr.combo, x.product, ''), x.dose_text, x.freq_text, x.action, x.valid_from, x.by, x.quote, coalesce(x.created_at, x.valid_from)
               ORDER BY coalesce(x.created_at, x.valid_from), x.id""", {"p": norm(person)}, scope="read")
        if upto < 0:
            raise ValueError("upto must be zero or more")
        chain, h = [], hashlib.sha256(b"carecircle-history-v1").hexdigest()
        for i, r in enumerate(rows, 1):
            if upto and i > upto:
                break
            h = hashlib.sha256((h + json.dumps(list(r), ensure_ascii=False, separators=(",", ":"))).encode("utf-8")).hexdigest()
            chain.append(h)
        return {"entries": len(chain), "of": len(rows), "head": chain[-1] if chain else "",
                "checkpoints": [{"n": n, "hash": chain[n - 1]} for n in (1, 5, 10, 25, 50, 100, 250, 500) if n <= len(chain)],
                "note": "Detects a change to an earlier entry's medicine, strength, frequency, time, writer or quoted line. It does not show an entry is correct."}

    async def care_timeline(self, person: str, limit: int = 100, now: Optional[int] = None) -> list[dict]:
        """Everything that happened for this person, newest first, as plain sentences."""
        t = now_ms() if now is None else now
        p = norm(person)
        out = []
        grouped: dict = {}                                          # the entries of one product (the two ingredients of Telma-AM) typed together are ONE line, as they were one prescription
        for (did, drug, dt, ft, action, src, quote, by, at, status, vf, mby, mat, mwhy, prod, pstrength) in await self._q(
                """MATCH (x:Dose)-[:FOR]->(:Person {id:$p}) OPTIONAL MATCH (x)-[:VIA]->(pr:Product)
                   RETURN x.id, x.drug, x.dose_text, x.freq_text, x.action, x.source_type, x.quote, x.by, x.at, x.status, x.valid_from,
                          x.mistake_by, x.mistake_at, x.mistake_reason, coalesce(pr.combo, x.product, ''), coalesce(pr.strength, x.pstrength, '')""",
                {"p": p}, scope="read"):
            gk = (prod, by, action, status, at // 60_000) if prod else None
            if gk and gk in grouped:
                grouped[gk]["ingredients"].append(drug)
                grouped[gk]["doses"].append(did)
                continue
            verb = "stopped" if action == "stop" else "recorded"
            pend = " (waiting for confirmation)" if status == "pending" else " (marked as entered by mistake)" if status == "mistake" else ""
            if status == "mistake" and mat:
                out.append({"at": mat, "kind": "mistake", "dose": did, "who": who(mby),
                            "text": f"{who(mby)} marked the entry for {_title(drug)} as entered by mistake{': ' + mwhy if mwhy else ''}.",
                            "quote": "", "when": iso(mat), "ago": ago(mat, t)})
            row = {"at": at, "kind": "stop" if action == "stop" else "record", "dose": did, "status": status, "who": who(by),
                   "text": f"{who(by)} {verb} {_title(drug)}{' ' + dt if dt else ''}{' ' + ft if ft else ''}, {SOURCE_WORDS.get(src, src)}{pend}.",
                   "quote": quote or "", "when": iso(at), "ago": ago(at, t)}
            if gk:
                row.update(_dt=dt or pstrength, _ft=ft, _src=src, _pend=pend, _verb=verb, product=prod, ingredients=[drug], doses=[did])
                grouped[gk] = row
            out.append(row)
        for row in grouped.values():                                  # a product's one line names the product and its ingredients
            if len(row["ingredients"]) > 1:
                names = " + ".join(_title(i) for i in sorted(row["ingredients"]))
                row["text"] = (f"{row['who']} {row['_verb']} {product_name(row['product'])} ({names})"
                               f"{' ' + row['_dt'] if row['_dt'] else ''}{' ' + row['_ft'] if row['_ft'] else ''}, {SOURCE_WORDS.get(row['_src'], row['_src'])}{row['_pend']}.")
            for k in ("_dt", "_ft", "_src", "_pend", "_verb"):
                row.pop(k, None)
        acks: dict = {}
        for (c, did, drug, at, prod) in await self._q(
                "MATCH (c:Person)-[a:ACKED]->(x:Dose)-[:FOR]->(:Person {id:$p}) OPTIONAL MATCH (x)-[:VIA]->(pr:Product) RETURN c.id, x.id, x.drug, a.at, coalesce(pr.combo, x.product, '')",
                {"p": p}, scope="read"):
            ak = (c, prod, at // 60_000) if prod else None
            if ak and ak in acks:
                acks[ak]["text"] = f"{who(c)} acknowledged the entry for {product_name(prod)}."
                continue
            row = {"at": at, "kind": "ack", "dose": did, "who": who(c), "text": f"{who(c)} acknowledged the entry for {_title(drug)}.",
                   "quote": "", "when": iso(at), "ago": ago(at, t)}
            if ak:
                acks[ak] = row
            out.append(row)
        gives: dict = {}
        for (drug, slot, by, at, via) in await self._q("MATCH (g:Give {person:$p}) RETURN g.drug, g.slot, g.by, g.at, coalesce(g.via, '')", {"p": p}, scope="read"):
            gk2 = (via, slot, by, at // 60_000) if via else None
            if gk2 and gk2 in gives:
                gives[gk2]["drugs"].append(drug)
                gives[gk2]["text"] = f"{who(by)} recorded {' + '.join(_title(d) for d in sorted(gives[gk2]['drugs']))} as given for the {slot} slot (one tablet)."
                continue
            row = {"at": at, "kind": "give", "who": who(by), "text": f"{who(by)} recorded {_title(drug)} as given for the {slot} slot.",
                   "quote": "", "when": iso(at), "ago": ago(at, t)}
            if gk2:
                row["drugs"] = [drug]
                gives[gk2] = row
            out.append(row)
        for (kindm, val, unit, at, by) in await self._q("MATCH (m:Measurement)-[:FOR]->(:Person {id:$p}) RETURN m.kind, m.value, m.unit, m.at, m.by", {"p": p}, scope="read"):
            out.append({"at": at, "kind": "measure", "who": who(by), "text": f"{who(by)} recorded {kindm.replace('_', ' ')} {val:g} {unit}.", "quote": "", "when": iso(at), "ago": ago(at, t)})
        for (rid, kind, at, by) in await self._q("MATCH (r:Receipt) RETURN r.id, r.kind, r.at, r.by", scope="read"):
            out.append({"at": at, "kind": "forget", "who": who(by), "text": f"{who(by)} removed {'an entry' if kind == 'dose' else 'all records of a person'} for good (receipt {rid}).",
                        "quote": "", "when": iso(at), "ago": ago(at, t)})
        out.sort(key=lambda e: -e["at"])
        return out[:limit]

    # ------------------------------------------------------------------ forgetting, with a receipt
    async def care_forget(self, dose_id: str, reason: str = "") -> dict:
        """Remove one entry for good and return a receipt.

        The dose, frequency, quote, links and acknowledgements are deleted. What stays is a receipt with a keyed hash (HMAC-SHA-256, the key stays on the
        server) of what was removed, who did it, and when. A plain hash of a short line like "warfarin 5 mg" could be found by trying likely lines; a keyed one cannot. Only the owner of the circle may do this: it cannot
        be undone and it removes what other carers may rely on. Any carer can instead mark an entry as entered by mistake (care_mark_mistake), which keeps it in the history."""
        rows = await self._q("MATCH (x:Dose {id:$id}) OPTIONAL MATCH (x)-[:VIA]->(pr:Product) RETURN x.drug, x.dose_text, x.freq_text, x.quote, x.by, x.at, x.status, coalesce(pr.combo, x.product, '')",
                             {"id": dose_id}, scope="admin")
        if not rows:
            raise KeyError(dose_id)
        drug, dt, ft, quote, by, at, status, product = rows[0]
        owner = await self._q("MATCH (x:Dose {id:$id})-[:FOR]->(p:Person) RETURN p.id", {"id": dose_id}, scope="write")
        kdf = await self._receipt_kdf()
        digest = await self._receipt_mac([drug, dt, ft, quote, by, at], kdf)
        rid, t = new_id("rcpt"), now_ms()
        for (fid,) in await self._q("MATCH (f)-[:ABOUT]->(:Dose {id:$id}) WHERE f.pred IS NOT NULL RETURN f.id", {"id": dose_id}, checked=True):
            await self.forget_fact(fid, "the entry it was about was erased")                    # facts written about it are retracted with it
        await self._q("MATCH (e)-[:ABOUT]->(:Dose {id:$id}) WHERE e.content IS NOT NULL SET e.content='[removed]', e.redacted=true", {"id": dose_id})       # what was written about it goes with it
        await self._q("MATCH (h:Handover)-[:ABOUT]->(:Dose {id:$id}) DETACH DELETE h", {"id": dose_id})
        await self._q("MATCH (r:Reminder)-[:ABOUT]->(:Dose {id:$id}) DETACH DELETE r", {"id": dose_id})
        await self._q("MATCH (x:Dose {id:$id}) OPTIONAL MATCH (n:Nudge) WHERE n.key CONTAINS $id DETACH DELETE n, x", {"id": dose_id})
        await self._q("CREATE (:Receipt {id:$r, kind:'dose', hash:$h, at:$t, by:$by, reason:$why, removed:'dose, quote, links, acknowledgements', kdf:$kdf})",
                      {"r": rid, "h": digest, "t": t, "by": norm(self.agent), "why": reason[:200], "kdf": kdf})
        if owner:                                                   # close the gap: the entry before it becomes current again
            await self._care_rechain(owner[0][0], drug, product)
        await self._chain_note("erase", dose_id, digest, norm(self.agent))      # the log says an entry was erased, and by whom, without saying what it held
        left = (await self._q("MATCH (x:Dose {id:$id}) RETURN count(x)", {"id": dose_id}, scope="read"))[0][0]
        return {"receipt": rid, "forgotten": left == 0, "removed": "the entry, its quote, its links and acknowledgements", "sha256": digest,
                "note": "The receipt code lets this server match it to a copy someone kept (care_receipt_check); without the server's key it cannot be tried against guesses."}

    async def care_mark_mistake(self, dose_id: str, reason: str = "") -> dict:
        """Take an entry off the record as entered by mistake, without erasing it: it stays in the history, marked, with who marked it and why, and the entry
        before it becomes current again. Any carer can do this; the owner (or whoever marked it) can put it back with care_restore_entry."""
        rows = await self._q("MATCH (x:Dose {id:$id})-[:FOR]->(p:Person) WHERE x.status IN ['confirmed', 'pending'] OPTIONAL MATCH (x)-[:VIA]->(pr:Product) RETURN x.drug, p.id, x.status, coalesce(pr.combo, x.product, '')", {"id": dose_id}, scope="write")
        if not rows:
            raise KeyError(dose_id)
        drug, person, was, product = rows[0]
        await self._q("MATCH (x:Dose {id:$id}) SET x.status='mistake', x.status_before=$was, x.cur=false, x.mistake_by=$by, x.mistake_at=$t, x.mistake_reason=$why",
                      {"id": dose_id, "was": was, "by": norm(self.agent), "t": now_ms(), "why": (reason or "")[:200]}, checked=True)
        await self._care_rechain(person, drug, product)
        await self._chain_note("mistake", dose_id, norm(self.agent), (reason or "")[:200])
        return {"id": dose_id, "status": "mistake", "note": "Marked as entered by mistake. It stays in the history; the owner or you can put it back."}

    async def care_restore_entry(self, dose_id: str) -> dict:
        """Put back an entry that was marked as entered by mistake. Only the owner or the carer who marked it."""
        rows = await self._q("MATCH (x:Dose {id:$id, status:'mistake'})-[:FOR]->(p:Person) OPTIONAL MATCH (x)-[:VIA]->(pr:Product) RETURN x.drug, p.id, x.status_before, x.mistake_by, coalesce(pr.combo, x.product, '')", {"id": dose_id}, scope="write")
        if not rows:
            raise KeyError(dose_id)
        drug, person, before, marker, product = rows[0]
        if norm(marker) != norm(self.agent) and self._guard:
            await self._guard("admin")                                       # anyone but the carer who marked it needs the owner's right to undo it
        await self._q("MATCH (x:Dose {id:$id}) SET x.status=$st, x.status_before=null, x.mistake_by=null, x.mistake_at=null, x.mistake_reason=null",
                      {"id": dose_id, "st": before or "confirmed"}, checked=True)
        await self._care_rechain(person, drug, product)
        await self._chain_note("restore", dose_id, norm(self.agent))
        return {"id": dose_id, "status": before or "confirmed"}

    async def care_forget_person(self, person: str, confirm: str = "") -> dict:
        """Remove everything about the person cared for (entries, dose slots, reminders). Needs the person's name typed as `confirm`."""
        p = norm(person)
        if norm(confirm) != p:
            raise ValueError("type the person's name as `confirm` to remove all records of them")
        doses = await self._q("MATCH (x:Dose)-[:FOR]->(:Person {id:$p}) RETURN x.id", {"p": p}, scope="admin")      # owners only
        ids = [r[0] for r in doses]
        gives = (await self._q("MATCH (g:Give {person:$p}) RETURN count(g)", {"p": p}))[0][0]
        kdf = await self._receipt_kdf()
        digest = await self._receipt_mac([p, sorted(ids)], kdf)
        await self._q("MATCH (g:Give {person:$p}) DELETE g", {"p": p})
        await self._q("MATCH (v:Prevented {person:$p}) DELETE v", {"p": p})
        await self._q("MATCH (h:Handover {person:$p}) DELETE h", {"p": p})
        await self._q("MATCH (w:Watch) WHERE w.key STARTS WITH $k DELETE w", {"k": p + "|"})
        await self._q("MATCH (f:Followup {person:$p}) DETACH DELETE f", {"p": p})
        for lab in ("Measurement", "Appointment", "Condition", "Allergy", "Consent", "Review"):
            await self._q(f"MATCH (m:{lab})-[:FOR]->(:Person {{id:$p}}) DETACH DELETE m", {"p": p})
        if ids:
            await self._q("UNWIND $ids AS i MATCH (n:Nudge) WHERE n.key CONTAINS i DELETE n", {"ids": ids})
        for (fid,) in await self._q("MATCH (f)-[:ABOUT]->(t) WHERE f.pred IS NOT NULL AND ((t:Dose AND (t)-[:FOR]->(:Person {id:$p})) OR (t:Person AND t.id = $p)) RETURN DISTINCT f.id", {"p": p}, checked=True):
            await self.forget_fact(fid, "the person it was about was erased")
        await self._q("MATCH (e)-[:ABOUT]->(:Dose)-[:FOR]->(:Person {id:$p}) WHERE e.content IS NOT NULL SET e.content='[removed]', e.redacted=true", {"p": p})
        await self._q("MATCH (e)-[:ABOUT]->(:Person {id:$p}) WHERE e.content IS NOT NULL SET e.content='[removed]', e.redacted=true", {"p": p})
        await self._q("MATCH (r:Reminder {person:$p}) DETACH DELETE r", {"p": p})
        await self._q("MATCH (x:Dose)-[:FOR]->(:Person {id:$p}) DETACH DELETE x", {"p": p})
        await self._q("MATCH (pr:Product {person:$p}) DETACH DELETE pr", {"p": p})                       # the tablets go with the person
        await self._q("MATCH (q:Person {id:$p, role:'patient'}) DETACH DELETE q", {"p": p})
        await self._q("MATCH (s:Source) DETACH DELETE s")                         # the text read from photos, voice notes and documents (names and all)
        await self._q("MATCH (m:ChatMsg) DELETE m")                                # the helper's conversation: it is about this person
        await self._q("MATCH (e:Event) DELETE e")                                  # the history log started over: it held hashes of the entries that no longer exist
        await self._q("MATCH (c:Chain) DELETE c")
        await self._chain_note("erase_person", p, digest, norm(self.agent))
        rid = new_id("rcpt")
        await self._q("CREATE (:Receipt {id:$r, kind:'person', hash:$h, at:$t, by:$by, reason:'', removed:$rm, kdf:$kdf})",
                      {"r": rid, "h": digest, "t": now_ms(), "by": norm(self.agent), "rm": f"{len(ids)} entries, {gives} dose records", "kdf": kdf})
        left = (await self._q("MATCH (x:Dose)-[:FOR]->(:Person {id:$p}) RETURN count(x)", {"p": p}, scope="read"))[0][0]
        return {"receipt": rid, "forgotten": left == 0, "removed_entries": len(ids), "removed_dose_records": gives, "sha256": digest}

    async def _receipt_kdf(self) -> str:
        """'server' when a server secret is set (the key is derived from it and this circle's id and is stored nowhere), else 'graph' (the older way: a random
        key kept in the circle's own graph, which protects against API users but not against anyone who holds a copy of the graph)."""
        return "server" if await asyncio.to_thread(server_secret) else "graph"

    async def _receipt_key(self, kdf: str = "graph") -> bytes:
        """The key for receipts: derived from the server secret and the circle's id ('server'), or the circle's own random key kept in its graph ('graph')."""
        if kdf == "server":
            secret = await asyncio.to_thread(server_secret)
            if not secret:
                raise ValueError("this receipt was made with the server's receipt secret, which is not set here, so it cannot be checked")
            return hmac.new(secret, b"cc-receipt-v2|" + self.tenant.encode("utf-8"), hashlib.sha256).digest()
        rows = await self._q("MATCH (s:Setting {key:'receipt_key'}) RETURN s.value LIMIT 1", scope="read", checked=True)
        if rows:
            return bytes.fromhex(rows[0][0])
        key = secrets.token_hex(32)
        await self._q("MERGE (s:Setting {key:'receipt_key'}) ON CREATE SET s.value=$v", {"v": key}, checked=True)
        rows = await self._q("MATCH (s:Setting {key:'receipt_key'}) RETURN s.value LIMIT 1", scope="read", checked=True)
        return bytes.fromhex(rows[0][0])

    async def _receipt_mac(self, parts: list, kdf: str = "graph") -> str:
        return hmac.new(await self._receipt_key(kdf), json.dumps(parts, sort_keys=True).encode("utf-8"), hashlib.sha256).hexdigest()

    async def care_receipt_check(self, receipt: str, drug: str = "", dose_text: str = "", freq_text: str = "", quote: str = "", by: str = "", at: int = 0) -> dict:
        """Does a copy someone kept (the medicine, strength, frequency, quoted line, writer and time) match what a dose receipt says was erased? Admin only."""
        rows = await self._q("MATCH (r:Receipt {id:$r, kind:'dose'}) RETURN r.hash, coalesce(r.kdf, 'graph')", {"r": receipt}, scope="admin")
        if not rows:
            raise KeyError(receipt)
        mine = await self._receipt_mac([norm(drug), dose_text, freq_text, quote, norm(by), at], rows[0][1])
        return {"receipt": receipt, "matches": hmac.compare_digest(mine, rows[0][0])}

    async def care_receipts(self) -> list[dict]:
        """Receipts of everything that was removed for good (hash, who, when), newest first."""
        rows = await self._q("MATCH (r:Receipt) RETURN r.id, r.kind, r.hash, r.at, r.by, r.reason, r.removed, coalesce(r.kdf, 'graph') ORDER BY r.at DESC", scope="read")
        return [dict(receipt=r[0], kind=r[1], sha256=r[2], at=r[3], when=iso(r[3]), by=who(r[4]), reason=r[5], removed=r[6], keyed_by=r[7]) for r in rows]

    # ------------------------------------------------------------------ the helper assistant: the conversation is kept in the circle's graph
    async def care_chat_ask(self, person: str, question: str, now: Optional[int] = None, daily_limit: int = 60, lang: str = "") -> dict:
        """Ask the helper assistant about this circle. Both sides of the exchange are stored for the asking carer, so the chat is there on any device.

        Answers come from the circle's own record (rules first, then a guarded model); the assistant never changes anything and never advises.
        It reads this carer's last turns, so a follow-up ('and Ravi?', 'why is the second one flagged?') is read against what it just listed; when what a follow-up refers to cannot be told it asks which one, and the advice check applies to every follow-up."""
        import os
        from carecircle import assistant
        from .care import checker
        t = now_ms() if now is None else now
        me = norm(self.agent)
        day = t // 86_400_000
        used = (await self._q("MATCH (m:ChatMsg {by:$me, day:$d, role:'user'}) RETURN count(m)", {"me": me, "d": day}, scope="read"))[0][0]
        if used >= daily_limit:
            raise ValueError(f"You have used today's {daily_limit} questions for the assistant. It resets tomorrow.")
        facts = await assistant.gather(self, person, t)
        recent = await self._q("MATCH (m:ChatMsg {by:$me}) RETURN m.role, m.text, m.ctx, m.at ORDER BY m.at DESC LIMIT 20", {"me": me}, scope="read")
        history = [{"role": r[0], "text": r[1], "ctx": json.loads(r[2]) if r[2] else {}, "at": r[3]} for r in reversed(recent)]
        out = await asyncio.to_thread(assistant.ask, question, facts, checker(), None, lang, history)
        qid, aid = new_id("msg"), new_id("msg")
        links = json.dumps(out.get("links", []))
        props = json.dumps(out.get("proposals", []))
        await self._q("""CREATE (:ChatMsg {id:$q, by:$me, day:$d, role:'user', text:$qt, at:$t, links:'[]', props:'[]', source:''}),
                         (:ChatMsg {id:$a, by:$me, day:$d, role:'assistant', text:$at, at:$t2, links:$l, props:$p, source:$s, ptext:$pt, ctx:$cx})""",
                      {"q": qid, "a": aid, "me": me, "d": day, "qt": " ".join(question.split())[:300], "at": out["answer"], "t": t, "t2": t + 1,
                       "l": links, "p": props, "s": out["source"], "pt": out.get("text", ""), "cx": json.dumps(out.get("ctx") or {})})
        return {"id": aid, "role": "assistant", "text": out["answer"], "source": out["source"], "at": t + 1, "links": out.get("links", []),
                "proposals": out.get("proposals", []), "proposal_text": out.get("text", ""), "left_today": max(0, daily_limit - used - 1)}

    async def care_chat_history(self, limit: int = 40) -> list[dict]:
        """This carer's conversation with the helper assistant, oldest first."""
        rows = await self._q("MATCH (m:ChatMsg {by:$me}) RETURN m.id, m.role, m.text, m.at, m.source, m.links, m.props, m.ptext ORDER BY m.at DESC LIMIT $n",
                             {"me": norm(self.agent), "n": limit}, scope="read")
        return [{"id": r[0], "role": r[1], "text": r[2], "at": r[3], "source": r[4], "links": json.loads(r[5] or "[]"), "proposals": json.loads(r[6] or "[]"),
                 "proposal_text": r[7] or ""} for r in reversed(rows)]

    async def care_chat_clear(self) -> dict:
        """Delete this carer's conversation with the helper assistant."""
        await self._q("MATCH (m:ChatMsg {by:$me}) DELETE m", {"me": norm(self.agent)})
        return {"cleared": True}

    # ------------------------------------------------------------------ FHIR export
    async def care_export_fhir(self, person: str, coded: bool = False) -> dict:
        """The regimen as a FHIR R4 Bundle of MedicationStatement resources.

        A collection of one Patient and the statements. By default it is free text only and says so. With `coded=true` each medicine whose name matches an RxNorm
        ingredient EXACTLY (looked up at NLM RxNav; only the medicine name is sent) also carries that RxNorm code; one that does not match stays text, and the
        bundle says which are which. A brand or combination (Telma-AM) is never coded as a single ingredient."""
        p = norm(person)
        rows = await self._q(
            """MATCH (x:Dose {status:'confirmed', action:'set'})-[:FOR]->(:Person {id:$p})
               RETURN x.id, x.drug, x.dose_text, x.freq_text, x.valid_from, x.valid_to, x.cur, x.source_type, x.quote, x.verified, x.by
               ORDER BY x.valid_from""", {"p": p}, scope="read")
        entries = [{"fullUrl": f"urn:uuid:patient-{p}", "resource": {"resourceType": "Patient", "id": p, "name": [{"text": _title(p)}],
                                                                       "meta": {"tag": [{"code": "synthetic-or-user-entered"}]}}}]
        codes: dict[str, str] = {}
        if coded:
            from carecircle import external
            for d in sorted({r[1] for r in rows}):
                got = await asyncio.to_thread(external.rxnorm_ingredients, d)
                hit = next((g for g in got if g["name"] == d and g.get("rxcui")), None)         # an exact ingredient match only: a guess is not a code
                if hit:
                    codes[d] = str(hit["rxcui"])
        for (did, drug, dt, ft, vf, vt, cur, src, quote, verified, by) in rows:
            period = {"start": datetime.fromtimestamp(vf / 1000, tz=timezone.utc).isoformat()}
            if vt:
                period["end"] = datetime.fromtimestamp(vt / 1000, tz=timezone.utc).isoformat()
            res = {"resourceType": "MedicationStatement", "id": did, "status": "active" if cur else "stopped",
                   "medicationCodeableConcept": ({"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": codes[drug], "display": _title(drug)}], "text": _title(drug)}
                                                 if drug in codes else {"text": _title(drug)}), "subject": {"reference": f"Patient/{p}", "display": _title(p)},
                   "effectivePeriod": period, "informationSource": {"display": who(by)},
                   "dosage": [{"text": " ".join(x for x in (dt, ft) if x) or "not recorded"}],
                   "note": [{"text": f"Source: {SOURCE_WORDS.get(src, src)}." + (f" Quoted line: \"{quote}\"." if quote else "")
                                     + (" Quote verified against the source text." if verified else "")}]}
            entries.append({"fullUrl": f"urn:uuid:{did}", "resource": res})
        return {"resourceType": "Bundle", "type": "collection", "timestamp": datetime.now(timezone.utc).isoformat(),
                "meta": {"tag": [({"code": "coded-where-exact", "display": f"{len(codes)} of {len({r[1] for r in rows})} medicines carry an RxNorm code (exact ingredient match only); the others are free text"}
                                  if coded else {"code": "free-text-only", "display": "No medicine codes are assigned by Care Circle"})]}, "entry": entries}
