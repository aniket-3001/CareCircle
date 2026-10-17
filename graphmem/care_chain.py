"""A stored, append-only log of what was written about a person, chained by hash, inside the circle's own graph.

  (:Chain {k:'head', seq, hash})                          where the log ends now
  (:Event {seq, kind, ref, by, at, body, prev, hash})     one per write; hash = SHA-256(prev | seq | kind | ref | by | at | body)

`body` is a hash of the content, never the content: for an entry it is a hash of the medicine, strength, frequency, time, writer and quoted line as they were
written; for an erase it is the receipt's keyed hash. So the log shows THAT something was written, changed or erased, and when, without holding what it said.

An append moves the head only if nobody else moved it first (a compare-and-set in one query), so two writers cannot both extend the same link, in this process
or another. `care_chain_verify` walks the log from the start, recomputes every link, and compares each entry's body hash with the entry as it stands now: an
edited, removed or re-ordered event breaks a link, and an entry rewritten after it was logged no longer matches its event. It cannot see an entry that was added
without being logged, or one written before the log began (it counts those).

Not a blockchain and not an outside timestamp: whoever can write to the circle's graph can write a log that is consistent with a rewrite. It makes quiet changes
by a carer or a bug visible; it does not defend against the database owner.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Optional

from .db import norm, now_ms

GENESIS = hashlib.sha256(b"carecircle-chain-v1").hexdigest()
MAX_TRIES = 12


def entry_body(key: bytes, drug: str, product: str, dose_text: str, freq_text: str, action: str, valid_from: int, by: str, quote: str) -> str:
    """A keyed hash (the circle's own secret, as for erase receipts): a short line such as 'warfarin 5 mg' cannot be found by hashing guesses."""
    return hmac.new(key, json.dumps([drug, product or "", dose_text or "", freq_text or "", action, int(valid_from), by, quote or ""], ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8"), hashlib.sha256).hexdigest()


def link(prev: str, seq: int, kind: str, ref: str, by: str, at: int, body: str) -> str:
    return hashlib.sha256("|".join([prev, str(seq), kind, ref, by, str(at), body]).encode("utf-8")).hexdigest()


ENTRY_FIELDS = "x.drug, coalesce(x.product, ''), x.dose_text, x.freq_text, x.action, x.valid_from, x.by, x.quote"


class CareChainMixin:
    async def _chain_append(self, kind: str, ref: str, body: str) -> int:
        """Add one event to the end of the log. Returns its sequence number. Retries when another writer got there first."""
        by = norm(self.agent)
        for _ in range(MAX_TRIES):
            try:
                head = await self._q("MERGE (h:Chain {k:'head'}) ON CREATE SET h.seq = 0, h.hash = $g RETURN h.seq, h.hash", {"g": GENESIS}, checked=True)
            except Exception as e:   # two writers made the head at once; the constraint let one win, so read it on the next pass
                if "constraint" not in str(e).lower():
                    raise
                continue
            seq0, prev = int(head[0][0]), head[0][1]
            seq, at = seq0 + 1, now_ms()
            h = link(prev, seq, kind, ref, by, at, body)
            rows = await self._q(
                """MATCH (c:Chain {k:'head'}) WHERE c.seq = $s0 AND c.hash = $prev
                   CREATE (:Event {seq:$seq, kind:$kind, ref:$ref, by:$by, at:$at, body:$body, prev:$prev, hash:$h})
                   SET c.seq = $seq, c.hash = $h RETURN $seq""",
                {"s0": seq0, "prev": prev, "seq": seq, "kind": kind, "ref": ref, "by": by, "at": at, "body": body, "h": h}, checked=True)
            if rows:
                return seq
        raise RuntimeError("the history log is busy; try again")

    async def _chain_entry(self, dose_id: str, kind: str = "entry") -> None:
        """Log an entry as it now stands."""
        rows = await self._q(f"MATCH (x:Dose {{id:$id}}) RETURN {ENTRY_FIELDS}", {"id": dose_id}, checked=True)
        if rows:
            await self._chain_append(kind, dose_id, entry_body(await self._receipt_key(), *rows[0]))

    async def _chain_note(self, kind: str, ref: str, *parts: str) -> None:
        """Log something other than an entry (a mistake mark, an undo, an erase): the body is a keyed hash of the given words."""
        await self._chain_append(kind, ref, hmac.new(await self._receipt_key(), json.dumps(list(parts), ensure_ascii=False).encode("utf-8"), hashlib.sha256).hexdigest())

    async def care_chain_verify(self, person: str = "") -> dict:
        """Walk the log from the start and say whether it is intact, and whether each logged entry still matches what is stored now."""
        evs = await self._q("MATCH (e:Event) RETURN e.seq, e.kind, e.ref, e.by, e.at, e.body, e.prev, e.hash ORDER BY e.seq", scope="read")
        head = await self._q("MATCH (h:Chain {k:'head'}) RETURN h.seq, h.hash", scope="read")
        key = await self._receipt_key()
        prev, bad, entries, adopted = GENESIS, None, 0, 0
        for n, (seq, kind, ref, by, at, body, p, h) in enumerate(evs, 1):
            if seq != n:
                bad = {"seq": n, "why": "an event is missing or out of order"}
                break
            if p != prev or link(prev, seq, kind, ref, by, at, body) != h:
                bad = {"seq": seq, "why": "this event was changed after it was written"}
                break
            prev = h
            if kind in ("entry", "adopted"):
                entries += 1
                adopted += kind == "adopted"
                now = await self._q(f"MATCH (x:Dose {{id:$id}}) RETURN {ENTRY_FIELDS}", {"id": ref}, scope="read")
                if now and entry_body(key, *now[0]) != body:
                    bad = {"seq": seq, "why": "the entry was changed after it was logged"}
                    break
        if bad is None and head and (head[0][0] != len(evs) or head[0][1] != prev):
            bad = {"seq": len(evs), "why": "the end of the log does not match its last event (events were removed)"}
        logged = {e[2] for e in evs if e[1] in ("entry", "adopted")}
        all_ids = {r[0] for r in await self._q("MATCH (x:Dose) RETURN x.id", scope="read")}
        return {"ok": bad is None, "events": len(evs), "entries_logged": entries, "entries_adopted": adopted, "entries_not_logged": len(all_ids - logged),
                "first_problem": bad, "head": prev if evs else "",
                "note": "Checks the log is unbroken and that each logged entry still reads as it did. It does not show an entry is true, and it cannot see an entry that was never logged "
                        "(entries from before the log began are counted). An entry added to the log late ('adopted') is covered from that moment on; nothing can show what it said before."}

    async def care_chain_adopt(self) -> dict:
        """Put entries that were written before the log began into it, as they read now, marked 'adopted'. From then on a change to them is caught; what they said
        before is not knowable (there was nothing to compare with), and the event records who adopted them and when, so it cannot pass for an original write."""
        done = {e[0] for e in await self._q("MATCH (e:Event) WHERE e.kind IN ['entry','adopted'] RETURN e.ref", scope="read")}
        rows = await self._q(f"MATCH (x:Dose) RETURN x.id, {ENTRY_FIELDS} ORDER BY x.created_at, x.id", scope="read")
        key, n = await self._receipt_key(), 0
        for r in rows:
            if r[0] not in done:
                await self._chain_append("adopted", r[0], entry_body(key, *r[1:]))
                n += 1
        return {"adopted": n, "note": "Entries from before the log began were added to it as they read now; changes to them are caught from this moment."}

    async def care_chain_events(self, limit: int = 50) -> list[dict]:
        """The newest events of the log (what kind, which entry, who, when; never the content)."""
        rows = await self._q("MATCH (e:Event) RETURN e.seq, e.kind, e.ref, e.by, e.at ORDER BY e.seq DESC LIMIT $n", {"n": max(1, min(int(limit), 500))}, scope="read")
        return [{"seq": r[0], "kind": r[1], "ref": r[2], "by": r[3], "at": r[4]} for r in rows]
