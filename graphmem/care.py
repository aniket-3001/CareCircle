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
import functools
import difflib
import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Optional

from carecircle import risk
from carecircle.algos import Algos
from carecircle.checks import Checker
from carecircle.safety import judgement, reword
from carecircle.verify import quote_in_source

from .db import new_id, norm, now_ms
from .textcheck import fit, product_name

_checker: Optional[Checker] = None
_algos: Optional[Algos] = None
SOURCES = ("typed", "photo", "voice", "document")
SOURCE_KIND = {"photo": "image", "voice": "voice", "document": "document"}      # what the server's own reader calls each kind of source it has read
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


SLOT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$")
SNAP_MIN = 90               # a typed time within this many minutes of one of the medicine's confirmed times is that time ("21:15" for a 21:00 dose)
NEAR_MIN = 60               # with no confirmed times, a second give of the same medicine this close to an earlier one is the same dose


def parse_slot(slot: str) -> tuple[str, int]:
    """A dose slot is a local date and time such as '2026-10-16 08:00'. Returns it in that exact form and as milliseconds (read as UTC; callers allow for the
    time zone). Anything else is refused: a typo must not turn into a 'dose given' that never happened."""
    m = SLOT_RE.match(" ".join(str(slot).split()))
    if not m:
        raise ValueError("a dose slot looks like 2026-10-16 08:00 (year-month-day hour:minute)")
    try:
        when = datetime(*(int(x) for x in m.groups()), tzinfo=timezone.utc)
    except ValueError:
        raise ValueError("that date and time do not exist") from None
    if not 2000 <= when.year <= 2100 or when.timestamp() * 1000 > now_ms() + 2 * 86_400_000:
        raise ValueError("a dose cannot be recorded as given more than a day or two ahead")
    return when.strftime("%Y-%m-%d %H:%M"), int(when.timestamp() * 1000)


@functools.lru_cache(maxsize=8192)
def _ingredient_of(name: str) -> str:
    """Name -> ingredient, remembered: the fuzzy match against ~1,800 names is slow, a give looks up every name on the record, and the reference names do not
    change while the server runs. (Without this, building the shared demo circle took 38 s and the server missed its start-up window.)"""
    try:
        top = checker().candidates(name, 1)
    except Exception:
        return name
    return top[0]["name"] if top and top[0]["score"] >= 0.95 else name


class CareMixin:
    @staticmethod
    def _pkey(person: str, product: str, drug: str) -> str:
        """The key of the (:Product) a tablet is: a brand as printed (kind 'product': a combination such as Telma-AM, or a one-ingredient brand such as Storvas) or the medicine itself (kind 'medicine'). One node per
        person and tablet; every entry of it points at it with VIA, and the times it is taken at live on it."""
        return f"{person}|product|{product}" if product else f"{person}|medicine|{drug}"
    # ------------------------------------------------------------------ record / confirm
    async def _known_person(self, person: str) -> str:
        """The person's id, refused if it is a near miss of someone already in the circle ("ashaa" for "asha"): a slip of the keyboard would otherwise start a second
        patient with an empty record, and the real one would look as if the medicine had never been entered. A genuinely different name is fine."""
        p = norm(person)
        have = [r[0] for r in await self._q("MATCH (q:Person {role:'patient'}) RETURN q.id", scope="read")]
        if p in have or not have:
            return p
        close = difflib.get_close_matches(p, have, n=1, cutoff=0.8)
        if close:
            raise ValueError(f"'{p}' looks like '{close[0]}', who is already in this circle. Use that name; if they really are two people, add '{p}' first with care_add_person.")
        return p

    async def care_add_person(self, person: str) -> dict:
        """Add another person to the circle on purpose (a name close to someone already there is otherwise refused as a likely typing slip)."""
        p = norm(person)
        if not p or len(p) > 60:
            raise ValueError("a person's name is 1 to 60 characters")
        await self._q("MERGE (q:Person {id:$p}) ON CREATE SET q.role='patient'", {"p": p})
        return {"person": p}

    async def care_record(self, person: str, drug: str, action: str = "set", dose_text: str = "", freq_text: str = "",
                          source_type: str = "typed", quote: str = "", source_text: str = "", confirm: bool = True,
                          at: Optional[int] = None, edited: str = "", source_ref: str = "", product: str = "", product_strength: str = "") -> dict:
        """A change to what `person` takes. action 'set' (start/change) or 'stop'. The previous current entry is closed and linked
        by SUPERSEDES. If `quote` is given it must occur in the text it was read from, else the entry stays UNVERIFIED and PENDING until someone
        confirms it with care_confirm; pending entries never reach the regimen or the checks. For a photo, voice note or document the text is the one
        the SERVER read (named by `source_ref`, returned by /intake): text a caller sends along cannot vouch for itself. For typed entries the caller's
        own `source_text` is the source."""
        if action not in ("set", "stop"):
            raise ValueError("action must be 'set' or 'stop'")
        if source_type not in SOURCES:
            raise ValueError(f"source_type must be one of {SOURCES}")
        stored = None
        if source_type != "typed":
            stored = await self._source(source_ref, SOURCE_KIND[source_type]) if source_ref else None
            source_text = stored["text"] if stored else ""                # never the caller's own claim about what a photo said
        verified = quote_in_source(quote, source_text) if quote else source_type == "typed"
        status = "confirmed" if (confirm and verified) else "pending"
        d, ts, did = norm(drug), (now_ms() if at is None else at), new_id("dose")
        if not d or len(d) > 80:
            raise ValueError("a medicine name is 1 to 80 characters")
        dose_text, freq_text = fit(dose_text, 80, "the dose"), fit(freq_text, 80, "how often")
        person = await self._known_person(person)
        product_strength = fit(product_strength, 80, "the product strength")
        product = norm(product)[:80]                       # the product the medicine came as ("telma-am"); empty when it was typed as the medicine itself
        pk = self._pkey(norm(person), product, d)
        cur = await self._q("MATCH (o:Dose {cur:true, drug:$d})-[:FOR]->(:Person {id:$p}), (o)-[:VIA]->(:Product {key:$pk}) "
                            "RETURN o.id, o.dose_text, o.freq_text, o.valid_from LIMIT 1", {"d": d, "p": norm(person), "pk": pk}, scope="read")
        if action == "stop" and not cur:
            raise KeyError(f"{d} is not on the record, so there is nothing to stop")
        same = lambda x, y: " ".join((x or "").lower().split()) == " ".join((y or "").lower().split())      # noqa: E731
        if action == "set" and cur and ts >= cur[0][3] and same(cur[0][1], dose_text) and same(cur[0][2], freq_text):
            return {"id": cur[0][0], "status": "confirmed", "verified": True, "unchanged": True,
                    "note": "already on the record exactly like this, so nothing was added"}
        warning = None
        if action == "set" and dose_text:
            from carecircle import dose as dosemod
            prev = await self._q("MATCH (o:Dose {cur:true, drug:$d})-[:FOR]->(:Person {id:$p}), (o)-[:VIA]->(:Product {key:$pk}) RETURN o.dose_text LIMIT 1",
                                 {"d": d, "p": norm(person), "pk": pk}, scope="read")
            warning = dosemod.slip(prev[0][0], dose_text) if prev and prev[0][0] else None
        rows = await self._q(
            """
            MERGE (p:Person {id:$p}) ON CREATE SET p.role='patient'
            MERGE (dr:Drug {name:$d})
            MERGE (au:Person {id:$by}) ON CREATE SET au.role='carer'
            MERGE (pr:Product {key:$pk}) ON CREATE SET pr.name=$pn, pr.kind=$pkind, pr.person=$p, pr.combo=$pcombo
            SET pr.strength = CASE WHEN $ps <> '' THEN $ps ELSE pr.strength END
            CREATE (x:Dose {id:$id, drug:$d, product:$pr, pstrength:$ps, dose_text:$dt, freq_text:$ft, valid_from:$ts, cur:false, action:$a, status:$st,
                            source_type:$src, quote:$q, verified:$v, by:$by, at:$ts, created_at:$now, edited:$ed})
            CREATE (x)-[:FOR]->(p) CREATE (x)-[:OF]->(dr) CREATE (x)-[:VIA]->(pr)
            WITH x OPTIONAL MATCH (s:Source {id:$sref}) FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END | CREATE (x)-[:READ_FROM]->(s))
            RETURN x.id""",
            {"p": norm(person), "d": d, "id": did, "dt": dose_text, "ft": freq_text, "ts": ts, "now": now_ms(), "a": action, "st": status,
             "src": source_type, "q": quote[:200], "v": verified, "by": norm(self.agent), "ed": ",".join(sorted({x for x in edited.split(",") if x in ("drug", "dose", "freq")})),
             "sref": stored["id"] if stored else "", "pr": product, "ps": product_strength,
             "pk": pk, "pn": product or d, "pkind": "product" if product else "medicine", "pcombo": product})
        if status == "confirmed":
            await self._care_activate(did)
            if action == "set" and cur and ts >= cur[0][3] and not (cur[0][2] and same(cur[0][2], freq_text)):
                await self._q("MATCH (pr:Product {key:$pk}) REMOVE pr.slots, pr.as_needed, pr.ends_on, pr.sched_by, pr.sched_at, pr.sched_first", {"pk": pk}, checked=True)          # a new written frequency: the times a person confirmed no longer apply to it
            if action == "set" and cur and cur[0][2] and same(cur[0][2], freq_text):          # the same written frequency: the product keeps its times (and the entry carries a copy, for one release, so a rolled-back server still reads them)
                await self._q("MATCH (o:Dose {id:$o}), (x:Dose {id:$n}) WHERE o.slots IS NOT NULL AND x.slots IS NULL "
                              "SET x.slots=o.slots, x.as_needed=o.as_needed, x.sched_by=o.sched_by, x.sched_at=o.sched_at, x.sched_first=o.sched_first, x.ends_on=o.ends_on",
                              {"o": cur[0][0], "n": did}, checked=True)
        await self._chain_entry(rows[0][0])                               # the append-only log: this entry, as written
        out = {"id": rows[0][0], "status": status, "verified": verified,
               "note": None if verified else ("no stored source for this " + source_type + ": confirm manually before it counts" if source_type != "typed" and not stored
                                              else "quote not found in the source text: confirm manually before it counts")}
        if warning:
            out["warning"] = warning
        return out

    async def care_store_source(self, kind: str, text: str, file_sha256: str = "", file_bytes: int = 0) -> str:
        """Keep the text the server read from a photo, voice note or document, and return its id. NOT an operation callers can reach: only the server's own
        intake (OCR, speech to text, document reader) calls it, so a stored source is evidence of what was really read, not of what a caller says it read.
        The picture or recording itself is not kept (it shows names and a doctor); only a SHA-256 of the file and its size, so a carer who still holds the file can show it is the one that was read."""
        if kind not in SOURCE_KIND.values():
            raise ValueError("unknown source kind")
        text = (text or "")[:20000]
        sid = new_id("src")
        await self._q("MATCH (o:Source) WHERE o.at < $old AND NOT (:Dose)-[:READ_FROM]->(o) DELETE o", {"old": now_ms() - 7 * 24 * H})
        await self._q("CREATE (:Source {id:$i, kind:$k, text:$t, sha256:$h, file_sha256:$fh, file_bytes:$fb, by:$by, at:$n})",
                      {"i": sid, "k": kind, "t": text, "h": hashlib.sha256(text.encode("utf-8")).hexdigest(), "fh": (file_sha256 or "")[:64], "fb": int(file_bytes or 0), "by": norm(self.agent), "n": now_ms()})
        return sid

    async def care_entry_source(self, dose_id: str) -> dict:
        """What an entry was read from: the full text the server read from the photo, voice note or document (not the image itself, which is never kept),
        the kind, and when. An entry typed in by hand has none."""
        rows = await self._q("MATCH (x:Dose {id:$i}) OPTIONAL MATCH (x)-[:READ_FROM]->(s:Source) RETURN x.quote, x.source_type, s.kind, s.text, s.sha256, s.at, s.file_sha256, s.file_bytes",
                             {"i": dose_id}, scope="read")
        if not rows:
            raise KeyError(dose_id)
        quote, how, kind, text, sha, at, fsha, fbytes = rows[0]
        return {"id": dose_id, "how_entered": how, "quote": quote or "", "has_source": text is not None, "kind": kind, "text": text or "",
                "sha256": sha, "read_at": at, "file_sha256": fsha or "", "file_bytes": fbytes or 0,
                "note": "This is the text the server read, kept so the quoted line can be checked. The picture or recording itself is not stored; only its fingerprint, so someone who still has the file can check it is the one that was read." if text is not None
                else "Typed in by hand, so there is no photo, voice note or document behind it."}

    async def _source(self, ref: str, kind: str) -> Optional[dict]:
        rows = await self._q("MATCH (s:Source {id:$i, kind:$k}) RETURN s.id, s.text", {"i": ref, "k": kind}, scope="read", checked=True)
        return {"id": rows[0][0], "text": rows[0][1]} if rows else None

    async def _care_activate(self, did: str) -> None:
        """A confirmed entry has joined the record: lay out that medicine's whole timeline again."""
        rows = await self._q("MATCH (x:Dose {id:$id})-[:FOR]->(p:Person) OPTIONAL MATCH (x)-[:VIA]->(pr:Product) RETURN p.id, x.drug, coalesce(pr.combo, x.product, '')", {"id": did}, checked=True)
        if rows:
            await self._care_rechain(rows[0][0], rows[0][1], rows[0][2])

    async def _care_rechain(self, person: str, drug: str, product: str = "") -> None:
        """Lay out every confirmed entry for one person and medicine in date order, as one timeline: each entry ends where the next begins, only the
        last 'set' is current, a 'stop' ends the medicine, and each entry replaces the one before it (SUPERSEDES). Because the order comes from the
        entries' own dates, an older prescription typed in late slots into the history instead of overriding the current one, and forgetting an entry
        simply closes the gap, so the entry before it is current again. Each statement recomputes from what is stored, so racing writers converge."""
        order = "ORDER BY x.valid_from, coalesce(x.created_at, x.valid_from), x.id"
        pk = self._pkey(person, product, drug)
        await self._q(
            f"""MATCH (x:Dose {{drug:$d, status:'confirmed'}})-[:FOR]->(:Person {{id:$p}}), (x)-[:VIA]->(:Product {{key:$pk}})
                WITH x {order}
                WITH collect(x) AS es
                UNWIND range(0, size(es) - 1) AS i
                WITH es[i] AS x, CASE WHEN i + 1 < size(es) THEN es[i + 1] ELSE null END AS nxt
                SET x.cur = (nxt IS NULL AND x.action = 'set'),
                    x.valid_to = CASE WHEN x.action = 'stop' THEN x.valid_from WHEN nxt IS NULL THEN null ELSE nxt.valid_from END""",
            {"p": person, "d": drug, "pk": pk}, checked=True)
        await self._q("MATCH (x:Dose {drug:$d})-[:FOR]->(:Person {id:$p}), (x)-[:VIA]->(:Product {key:$pk}) MATCH (x)-[r:SUPERSEDES]->(:Dose) DELETE r",
                      {"p": person, "d": drug, "pk": pk}, checked=True)
        await self._q(
            f"""MATCH (x:Dose {{drug:$d, status:'confirmed'}})-[:FOR]->(:Person {{id:$p}}), (x)-[:VIA]->(:Product {{key:$pk}})
                WITH x {order}
                WITH collect(x) AS es
                UNWIND range(1, size(es) - 1) AS i
                WITH es[i] AS n, es[i - 1] AS o
                CREATE (n)-[:SUPERSEDES]->(o)""",
            {"p": person, "d": drug, "pk": pk}, checked=True)
        # a tablet with no current entry left (stopped, or every entry erased) has no times, and one with no entries at all is not kept
        await self._q("MATCH (pr:Product {key:$pk}) WHERE NOT (pr)<-[:VIA]-(:Dose {cur:true}) REMOVE pr.slots, pr.as_needed, pr.ends_on, pr.sched_by, pr.sched_at, pr.sched_first", {"pk": pk}, checked=True)
        await self._q("MATCH (pr:Product {key:$pk}) WHERE NOT (pr)<-[:VIA]-(:Dose) DETACH DELETE pr", {"pk": pk}, checked=True)

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
        from carecircle import schedule as sched
        today = sched.local_date(t, await self._tz()).isoformat()
        rows = await self._q(
            """MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p})
               WHERE x.action='set' AND x.valid_from <= $t AND (x.valid_to IS NULL OR x.valid_to > $t)
               OPTIONAL MATCH (x)-[:VIA]->(pr:Product)
               WITH x, pr, coalesce(pr.ends_on, x.ends_on) AS ends
               WHERE (ends IS NULL OR ends = '' OR ends >= $today)
               RETURN x.id, x.drug, x.dose_text, x.freq_text, x.valid_from, x.source_type, x.quote, x.by, coalesce(pr.slots, x.slots), coalesce(pr.as_needed, x.as_needed), ends,
                      coalesce(pr.combo, x.product, ''), coalesce(pr.strength, x.pstrength, ''), coalesce(pr.key, '')
               ORDER BY x.drug, coalesce(pr.combo, x.product, '')""",
            {"p": norm(person), "t": t, "today": today}, scope="read")
        return [dict(id=r[0], drug=r[1], dose_text=r[2], freq_text=r[3], since=r[4], source=r[5], quote=r[6], by=r[7],
                     slots=list(r[8] or []), as_needed=bool(r[9]), ends_on=r[10] or None, product=r[11], product_strength=r[12], product_key=r[13]) for r in rows]

    async def care_duplicates(self, person: str, as_of: Optional[int] = None) -> list[dict]:
        """Ingredients recorded on more than one current entry (the same medicine reaching the person through two products: a combination brand and a plain
        entry, or two brands). The entries are kept apart on purpose (one per product), so this is where a second source of the same ingredient shows up.
        Found by the graph: the current entries of the person grouped on the (:Drug) they are OF, keeping the groups of two or more."""
        t = now_ms() if as_of is None else as_of
        from carecircle import schedule as sched
        today = sched.local_date(t, await self._tz()).isoformat()
        rows = await self._q(
            """MATCH (x:Dose {status:'confirmed', action:'set'})-[:FOR]->(:Person {id:$p}), (x)-[:OF]->(d:Drug)
               WHERE x.valid_from <= $t AND (x.valid_to IS NULL OR x.valid_to > $t)
               OPTIONAL MATCH (x)-[:VIA]->(pr:Product)
               WITH d.name AS drug, x, coalesce(pr.combo, x.product, '') AS cb, coalesce(pr.ends_on, x.ends_on) AS ends
               WHERE (ends IS NULL OR ends = '' OR ends >= $today)
               WITH drug, x, cb ORDER BY cb, x.id
               WITH drug, collect({id: x.id, product: cb, dose_text: x.dose_text, freq_text: x.freq_text, by: x.by}) AS es
               WHERE size(es) > 1 RETURN drug, es ORDER BY drug""",
            {"p": norm(person), "t": t, "today": today}, scope="read")
        out = []
        for drug, es in rows:
            names = [(product_name(e["product"]) if e["product"] else "recorded as the plain medicine") for e in es]
            title = drug[:1].upper() + drug[1:]
            out.append({"kind": "duplicate", "ingredient": drug, "entries": list(es),
                        "meaning": f"{title} is on record {len(es)} times: {'; '.join(names)}. It may be the same medicine from two sources.",
                        "source": "the entries on record (not a reference table)"})
        return out

    async def care_check(self, person: str, as_of: Optional[int] = None) -> dict:
        """Interaction flags for the regimen at `as_of`, from the shared reference graph (sources attached; never 'safe')."""
        reg = await self.care_regimen(person, as_of)
        res = await asyncio.to_thread(checker().check, [r["drug"] for r in reg])
        res["duplicates"] = await self.care_duplicates(person, as_of)
        res["regimen"] = reg
        res["judgement"] = judgement(res)
        return res

    async def care_drug_search(self, text: str, n: int = 8) -> list[dict]:
        """Search the reference list by name (starts with, then contains). For a person who knows what the medicine is called."""
        if self._guard:
            await self._guard("read")
        return await asyncio.to_thread(checker().search, text, n)

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
        changes = await self._q("MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p}) OPTIONAL MATCH (x)-[:VIA]->(pr:Product) "
                                "RETURN x.id, x.drug, x.action, x.at, x.by, coalesce(pr.combo, x.product, '') ORDER BY x.valid_from, coalesce(x.created_at, x.valid_from), x.id", {"p": norm(person)}, scope="read", checked=True)
        flags = await self.care_check(person)
        heavy: dict[str, float] = {}
        for f in flags["direct"]:
            for d in f["drugs"]:
                heavy[d] = max(heavy.get(d, 0), f["weight"])
        for f in flags["enzyme_paths"]:
            for d in (f["x"], f["y"]):                                          # the medicines are fields of the flag; the path text is for people to read
                heavy[d] = max(heavy.get(d, 0), f["weight"])
        out = {}
        for c in carers:
            acked = {r[0] for r in await self._q("MATCH (:Person {id:$c})-[:ACKED]->(x:Dose) RETURN x.id", {"c": c}, scope="read", checked=True)}
            latest: dict[str, tuple] = {}
            for row in changes:                                                      # ordered by time: the last row per medicine and product is where it stands now
                latest[(row[1], row[5])] = row
            miss = [(i, d, a, at, pr) for i, d, a, at, by, pr in latest.values() if i not in acked and norm(by) != c]
            ws = [heavy.get(m[1], 0.3) for m in miss]
            ages = [(t - m[3]) / H for m in miss]
            out[c] = {"unacknowledged": [{"dose": i, "drug": d, "action": a, "age_hours": round((t - at) / H, 1), "product": pr} for i, d, a, at, pr in miss],
                      "divergence": risk.divergence(ws, ages) if miss else 0.0}
        worst = max(out, key=lambda k: out[k]["divergence"], default=None)
        return {"carers": out, "most_out_of_date": worst if worst and out[worst]["divergence"] > 0 else None,
                "half_life_hours": risk.HALF_LIFE_HOURS, "weights_are_assumptions": True}

    async def care_nudges(self, person: str, now: Optional[int] = None, remind_after_h: float = 4, escalate_after_h: float = 12,
                          hold: Optional[set] = None) -> list[dict]:
        """CLAIMS the reminders that are due (so they are not produced twice): for the delivery loop and the circle's owner only. To look at what is due without using
        it up, call care_reminders. Reminders due: unacknowledged changes older than remind_after_h -> 'remind' that carer; older than escalate_after_h ->
        'escalate' to the other carers. Each (kind, carer, dose, recipient) is produced once: claiming it is a conditional write."""
        if self._guard:                                  # it only lists what is due, but each reminder it returns is claimed (used up): that is a write
            await self._guard("write")
        t = now_ms() if now is None else now
        div = await self.care_divergence(person, t)
        sent = []
        for carer, d in div["carers"].items():
            for u in d["unacknowledged"]:
                todo = [("remind", carer)] if u["age_hours"] >= remind_after_h else []
                if u["age_hours"] >= escalate_after_h:
                    todo += [("escalate", o) for o in div["carers"] if o != carer]
                for kind, to in todo:
                    if hold and to.lower() in hold:          # quiet hours: leave it unclaimed, it is sent when they end
                        continue
                    key = f"{kind}|{carer}|{u['dose']}|{to}"
                    r = await self._q("MERGE (n:Nudge {key:$k}) ON CREATE SET n.at=$t, n.fresh=true "
                                      "WITH n, n.fresh AS fresh SET n.fresh=false RETURN fresh", {"k": key, "t": t}, checked=True)
                    if r[0][0]:
                        facts = {"drug": u["drug"], "hours": u["age_hours"], "carer": carer}
                        tpl = (f"{carer.split(chr(45))[0].capitalize()} has not yet seen the change to {u['drug']} made {u['age_hours']} hours ago. "
                               "Please check with them.") if kind == "escalate" else (
                               f"The change to {u['drug']} made {u['age_hours']} hours ago is not yet acknowledged. Please open it and confirm.")
                        sent.append({"kind": kind, "about_carer": carer, "notify": to, "drug": u["drug"], "age_hours": u["age_hours"], "dose": u["dose"], "person": norm(person),
                                     "message": reword(tpl, facts), "claim": key})
        return sent

    async def care_nudge_release(self, claim: str, max_tries: int = 5) -> bool:
        """Hand a claimed reminder back because it could not be delivered anywhere, so the next pass produces it again. After `max_tries` hand-backs it stays used
        (a destination that keeps failing must not be tried for ever). Not an operation callers can reach: only the delivery loop uses it."""
        if self._guard:
            await self._guard("write")
        rows = await self._q("MATCH (n:Nudge {key:$k}) WHERE coalesce(n.tries, 0) < $m SET n.fresh = true, n.tries = coalesce(n.tries, 0) + 1 RETURN n.tries",
                             {"k": claim, "m": max_tries}, checked=True)
        if not rows:
            await self._q("MATCH (n:Nudge {key:$k}) SET n.gave_up = true", {"k": claim}, checked=True)       # kept used, but not delivered: the preview must not say it was
        return bool(rows)

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
                    sent = (await self._q("MATCH (n:Nudge {key:$k}) WHERE n.fresh = false AND coalesce(n.gave_up, false) = false RETURN count(n)", {"k": key}, scope="read"))[0][0] > 0
                    facts = {"drug": u["drug"], "hours": u["age_hours"], "carer": carer}
                    tpl = (f"{carer.split(chr(45))[0].capitalize()} has not yet seen the change to {u['drug']} made {u['age_hours']} hours ago. Please check with them.") if kind == "escalate" else (
                          f"The change to {u['drug']} made {u['age_hours']} hours ago is not yet acknowledged. Please open it and confirm.")
                    out.append({"kind": kind, "about_carer": carer, "notify": to, "drug": u["drug"], "age_hours": u["age_hours"],
                                "message": reword(tpl, facts), "delivered": sent})
        return out

    # ------------------------------------------------------------------ doses given: never twice for one slot
    @staticmethod
    def _ingredient(drug: str) -> str:
        """The ingredient a typed medicine name stands for ("Metformin HCl", "Glycomet" -> metformin), so the double-dose guard compares medicines and not spellings.
        Only a strong match counts (score 0.95 or more: an exact name, a salt form or a known alias); anything else stays as typed."""
        return _ingredient_of(norm(drug))

    async def _kin(self, person: str, drug: str) -> tuple[str, list[str], list[str]]:
        """(ingredient, every name this person's confirmed entries use for it, the union of those entries' current times). Two products of one ingredient
        (plain and a combination) are two entries with their own times; the guard looks at all of them."""
        ing = await asyncio.to_thread(self._ingredient, drug)
        rows = await self._q("MATCH (x:Dose {action:'set', status:'confirmed'})-[:FOR]->(:Person {id:$p}) OPTIONAL MATCH (x)-[:VIA]->(pr:Product) RETURN x.drug, x.cur, coalesce(pr.slots, x.slots)",
                             {"p": norm(person)}, scope="read")
        names, times = {norm(drug)}, set()
        for name, cur, slots in rows:
            if await asyncio.to_thread(self._ingredient, name) == ing:
                names.add(name)
                if cur:
                    times.update(slots or [])
        return ing, sorted(names), sorted(times)

    async def _canonical_slot(self, person: str, drug: str, slot: str, ing: str = "", times: Optional[list] = None) -> tuple[str, Optional[tuple]]:
        """Bring a typed slot to the medicine's own times, so 21:00 and 21:15 are one dose and not two.

        When the person has confirmed times for this ingredient (on any of its entries), a typed time is moved to the nearest of them (within SNAP_MIN minutes;
        farther is refused with the list). When no times are set, the app cannot know what a "slot" is, so a give within NEAR_MIN minutes of an earlier one by
        anyone counts as that same dose. Either way a give of the same ingredient under another spelling at the same slot is that dose too.
        Returns (slot, (earlier slot, who, when)) for the caller to refuse. This read is only the early answer: the write repeats the check atomically."""
        if not ing:
            ing, _names, times = await self._kin(person, drug)
        mins = lambda hhmm: int(hhmm[:2]) * 60 + int(hhmm[3:5])  # noqa: E731
        if times:
            want = mins(slot[11:16])
            best = min(times, key=lambda t: abs(mins(t) - want))
            if abs(mins(best) - want) > SNAP_MIN:
                raise ValueError(f"{slot[11:16]} is not one of this medicine's times ({', '.join(times)}); give it at one of those, or change the times first")
            slot = f"{slot[:10]} {best}"
        mine = datetime.strptime(slot, "%Y-%m-%d %H:%M")
        for s, d, by, at in await self._q("MATCH (g:Give {person:$p}) RETURN g.slot, g.drug, g.by, g.at", {"p": norm(person)}, scope="read"):
            same_name = norm(d) == norm(drug)
            if not same_name and await asyncio.to_thread(self._ingredient, d) != ing:
                continue
            try:
                gap = abs((datetime.strptime(s, "%Y-%m-%d %H:%M") - mine).total_seconds()) / 60
            except (TypeError, ValueError):
                continue
            if times:                                                  # the slot is already the medicine's own: only another spelling of it is a different claim
                if s == slot and not same_name:
                    return slot, (s, by, at)
            elif (s != slot or not same_name) and gap < NEAR_MIN:
                return slot, (s, by, at)
        return slot, None

    async def care_give(self, person: str, drug: str, slot: str) -> dict:
        """Record that the calling carer gave `drug` for dose slot `slot` (e.g. '2026-10-16 08:00'). A slot can be claimed once:
        the claim is one query that looks for an earlier give of the same ingredient close to this time and, if there is none, MERGEs the slot, so two
        carers racing get exactly one winner and the other is told who already recorded it."""
        slot, slot_ms = parse_slot(slot)
        ing, names, times = await self._kin(person, drug)
        on_record = await self._q(
            """MATCH (x:Dose {action:'set', status:'confirmed'})-[:FOR]->(:Person {id:$p})
               WHERE x.drug IN $d AND x.valid_from <= $ms + $slack AND (x.valid_to IS NULL OR x.valid_to >= $ms - $slack) RETURN x.id LIMIT 1""",
            {"d": names, "p": norm(person), "ms": slot_ms, "slack": 14 * 3_600_000}, scope="read")      # slack: the slot is local time, the record is UTC
        if not on_record:
            raise KeyError(f"{norm(drug) or 'that medicine'} was not on the record at that time, so a dose of it cannot be recorded as given")
        slot, near = await self._canonical_slot(person, drug, slot, ing, times)
        slot_ms = parse_slot(slot)[1]
        key = f"{norm(person)}|{norm(drug)}|{norm(slot)}"
        window = 0 if times else (NEAR_MIN - 1) * 60_000
        if not near:
            rows = await self._q(
                """OPTIONAL MATCH (e:Give {person:$p, ing:$ing}) WHERE e.key <> $k AND e.slot_ms IS NOT NULL AND abs(e.slot_ms - $ms) <= $w
                   WITH e ORDER BY e.at LIMIT 1
                   WITH e WHERE e IS NULL
                   MERGE (g:Give {key:$k}) ON CREATE SET g.by=$me, g.at=$t, g.person=$p, g.drug=$d, g.slot=$s, g.ing=$ing, g.slot_ms=$ms, g.won=true
                   WITH g, g.won AS fresh, g.by AS by, g.at AS at SET g.won=false RETURN fresh, by, at""",
                {"k": key, "me": norm(self.agent), "t": now_ms(), "p": norm(person), "d": norm(drug), "s": norm(slot), "ing": ing, "ms": slot_ms, "w": window})
            if rows:
                fresh, by, at = rows[0]
                if fresh:
                    watched = (await self._q("MATCH (w:Watch {key:$k}) RETURN count(w)", {"k": f"{norm(person)}|{norm(drug)}"}, scope="read"))[0][0] > 0
                    return {"given": True, "slot": slot, **({"needs_second_carer": True} if watched else {})}
                await self._q("MERGE (v:Prevented {key:$k}) ON CREATE SET v.person=$p, v.drug=$d, v.slot=$s, v.by=$me, v.first_by=$by, v.at=$t",
                              {"k": f"{key}|{norm(self.agent)}", "p": norm(person), "d": norm(drug), "s": norm(slot), "me": norm(self.agent), "by": by, "t": now_ms()}, checked=True)     # one record per carer and slot, however often they tap
                return {"given": False, "duplicate": True, "already_given_by": by, "at": at,
                        "note": "this slot was already recorded; check with them before giving another dose"}
            near = await self._near_give(person, ing, key, slot_ms, window)          # another carer's give of this ingredient, close to this time, got in first
            if not near:
                raise RuntimeError("the dose could not be recorded; nothing was saved")
        await self._q("MERGE (v:Prevented {key:$k}) ON CREATE SET v.person=$p, v.drug=$d, v.slot=$s, v.by=$me, v.first_by=$by, v.at=$t",
                      {"k": f"{norm(person)}|{norm(drug)}|{near[0]}|{norm(self.agent)}", "p": norm(person), "d": norm(drug), "s": norm(slot), "me": norm(self.agent), "by": near[1], "t": now_ms()}, checked=True)
        return {"given": False, "duplicate": True, "already_given_by": near[1], "at": near[2],
                "note": f"a dose of this was recorded for {near[0]}, within {NEAR_MIN} minutes of this one; check with them before giving another dose" if not times else
                        f"a dose of this was recorded for {near[0]} under another name; check with them before giving another dose"}

    async def _near_give(self, person: str, ing: str, key: str, slot_ms: int, window: int) -> Optional[tuple]:
        rows = await self._q("MATCH (e:Give {person:$p, ing:$ing}) WHERE e.key <> $k AND e.slot_ms IS NOT NULL AND abs(e.slot_ms - $ms) <= $w "
                             "RETURN e.slot, e.by, e.at ORDER BY e.at LIMIT 1", {"p": norm(person), "ing": ing, "k": key, "ms": slot_ms, "w": window}, scope="read")
        return tuple(rows[0]) if rows else None

    async def care_gives(self, person: str, limit: int = 50) -> list[dict]:
        rows = await self._q("MATCH (g:Give {person:$p}) OPTIONAL MATCH (w:Watch {key: g.person + '|' + g.drug}) "
                             "RETURN g.drug, g.slot, g.by, g.at, g.witness, w IS NOT NULL ORDER BY g.at DESC LIMIT $n",
                             {"p": norm(person), "n": limit}, scope="read")
        return [dict(drug=r[0], slot=r[1], by=r[2], at=r[3], witness=r[4], needs_second_carer=bool(r[5]) and not r[4]) for r in rows]

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

    async def care_recalls(self, person: str) -> dict:
        """Ongoing public recalls listed for the medicines on record. Only medicine names go out. Shown as published; whether one applies depends on the
        pack at home, which only a person (or the pharmacist) can check."""
        from carecircle import external
        tz = (await self.care_timezone())["tz"]
        if not any(tz.startswith(p) for p in ("America/", "US/", "Pacific/Honolulu")):       # openFDA lists US recalls only; for anyone else it would be noise, and no name should go out for nothing
            return {"checked": [], "available": False, "recalls": [], "region": "US only",
                    "note": f"Recall lookups use openFDA, which lists US recalls. This circle's time zone is {tz}, so none were looked up and no medicine name was sent."}
        reg = await self.care_regimen(person)
        drugs = sorted({r["drug"] for r in reg})
        found = await asyncio.gather(*[asyncio.to_thread(external.openfda_recalls, d) for d in drugs])
        return {"checked": drugs, "available": external.enabled(), "recalls": [x for f in found for x in f],
                "note": "A recall is about particular products and lots. Check the pack, and ask the pharmacist if unsure. This is not a statement about this person."}

    async def care_sole_knowers(self, person: str) -> dict:
        """For each medicine on record, who knows about its current entry (the carer who recorded it plus everyone who acknowledged it). An entry known
        to a single carer while others exist is a single point of failure: if that carer is away, nobody else has been told."""
        rows = await self._q(
            """MATCH (x:Dose {cur:true, status:'confirmed'})-[:FOR]->(:Person {id:$p})
               OPTIONAL MATCH (c:Person)-[:ACKED]->(x)
               RETURN x.id, x.drug, x.by, x.at, collect(DISTINCT c.id) ORDER BY x.drug""", {"p": norm(person)}, scope="read")
        carers = [r[0] for r in await self._q("MATCH (c:Person {role:'carer'}) RETURN c.id ORDER BY c.id", scope="read")]
        out, load = [], {}
        for did, drug, by, at, ackers in rows:
            knows = sorted({norm(by), *[norm(a) for a in ackers]} & set(carers))
            if len(carers) > 1 and len(knows) == 1:
                out.append({"dose": did, "drug": drug, "only": knows[0], "since": at})
                load[knows[0]] = load.get(knows[0], 0) + 1
        keystone = max(load, key=lambda k: load[k]) if load else None
        return {"carers": carers, "sole": out, "keystone": keystone, "keystone_count": load.get(keystone, 0) if keystone else 0}

    async def care_summary_counts(self, person: str) -> dict:
        """Plain counts over the record for a talk with a pharmacist: how complicated the regimen reads, a short anticholinergic list total (a subset), and
        how much of the regimen the interaction sources actually cover."""
        from carecircle import burden
        c = await self.care_check(person)
        stats = await self.care_reading_stats(person)
        return {"reading": stats, "load": burden.regimen_load(c["regimen"]), "anticholinergic": burden.anticholinergic_count(c["regimen"]), "coverage": c["coverage"],
                "note": "Counts of what is written and listed. They describe the record, not the person, and are not advice."}

    async def care_reading_stats(self, person: str) -> dict:
        """How often what was read from a photo, voice note or document was saved without a change by the carer who checked it. No text is kept, only
        counts, so it measures the reading on real use without storing anything personal."""
        rows = await self._q("MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p}) WHERE x.source_type <> 'typed' "
                             "RETURN x.source_type, count(x), sum(CASE WHEN x.edited = '' THEN 1 ELSE 0 END)", {"p": norm(person)}, scope="read")
        by = {r[0]: {"saved": int(r[1]), "unchanged": int(r[2])} for r in rows}
        saved = sum(v["saved"] for v in by.values())
        unchanged = sum(v["unchanged"] for v in by.values())
        return {"saved": saved, "unchanged": unchanged, "by_source": by,
                "statement": (f"Of {saved} entries read from photos, voice notes or documents, {unchanged} were saved exactly as read; the rest were corrected by the carer first."
                              if saved else "No entry has been read from a photo, voice note or document yet.")}

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
