"""The schedule: what a medicine's written frequency looks like as times on a clock, once a person has confirmed them.

  (:Dose {..., slots: ['08:00','20:00'], as_needed, ends_on: '2026-10-23', sched_by, sched_at})       times a carer confirmed for THIS entry
  (:Setting {key:'tz', value:'Asia/Kolkata'})                                                          the circle's time zone: it decides which day a slot belongs to

The app never invents a time. carecircle.schedule suggests times from the written frequency; care_schedule_set stores the ones a person confirms. The
checklist (care_today) lists today's confirmed slots and whether each is marked given. Giving a slot uses the same once-per-slot claim as care_give, with the
slot written from the schedule and the circle's own date, so two carers can no longer record the same dose under two different typed times.

Wording is about the RECORD ("not marked given yet"), never about the person's health, and nothing here says what to take or skip."""
from __future__ import annotations

from typing import Optional

from carecircle import schedule as sched

from .db import norm, now_ms

DEFAULT_TZ = "Asia/Kolkata"            # used until a circle sets its own; the web app sets it from the browser on first use
H = 3_600_000


class CareScheduleMixin:
    # ------------------------------------------------------------------ time zone
    async def _tz(self) -> str:
        rows = await self._q("MATCH (s:Setting {key:'tz'}) RETURN s.value", scope="read", checked=True)
        return rows[0][0] if rows else DEFAULT_TZ

    async def care_timezone(self) -> dict:
        """The circle's time zone (IANA name) and whether anyone has set it yet."""
        rows = await self._q("MATCH (s:Setting {key:'tz'}) RETURN s.value", scope="read")
        return {"tz": rows[0][0] if rows else DEFAULT_TZ, "set": bool(rows)}

    async def care_set_timezone(self, tz: str) -> dict:
        """Set the circle's time zone, e.g. 'Asia/Kolkata'. It decides which day a dose slot belongs to."""
        sched.zone(tz)                                                    # refuses a name that is not a zone
        await self._q("MERGE (s:Setting {key:'tz'}) SET s.value=$v, s.by=$by, s.at=$t", {"v": tz, "by": norm(self.agent), "t": now_ms()})
        return {"tz": tz, "set": True}

    # ------------------------------------------------------------------ suggestions and confirmation
    async def care_schedule_suggest(self, freq_text: str) -> dict:
        """Times suggested by a written frequency ('twice daily' -> 08:00 and 20:00), for a person to confirm or change. Reads nothing from the circle."""
        if self._guard:
            await self._guard("read")
        return sched.suggest(freq_text)

    async def care_schedule_set(self, dose_id: str, times: list, as_needed: bool = False, ends_on: str = "") -> dict:
        """Confirm when this entry is taken: the clock times (HH:MM, 24-hour), or `as_needed` for a medicine with no fixed times, and optionally the last
        day of a short course (YYYY-MM-DD, the circle's local date). Replaces what was set before. Needs the entry to be current."""
        rows = await self._q("MATCH (x:Dose {id:$id, status:'confirmed', cur:true, action:'set'}) RETURN x.drug, x.valid_from", {"id": dose_id}, scope="write")
        if not rows:
            raise KeyError(dose_id)
        if as_needed and times:
            raise ValueError("a medicine taken as needed has no fixed times: send either times or as_needed")
        slots = [] if as_needed else sched.clean_times(times)
        tz = await self._tz()
        ends = ""
        if ends_on:
            try:
                day = __import__("datetime").date.fromisoformat(ends_on)
            except ValueError:
                raise ValueError("ends_on looks like 2026-10-23") from None
            if day < sched.local_date(now_ms(), tz) - __import__("datetime").timedelta(days=1) or day.year > 2100:
                raise ValueError("the last day of a course cannot be in the past")
            ends = day.isoformat()
        await self._q("MATCH (x:Dose {id:$id}) SET x.slots=$s, x.as_needed=$a, x.ends_on=$e, x.sched_by=$by, x.sched_at=$t",
                      {"id": dose_id, "s": slots, "a": bool(as_needed), "e": ends, "by": norm(self.agent), "t": now_ms()}, checked=True)
        return {"id": dose_id, "drug": rows[0][0], "times": slots, "as_needed": bool(as_needed), "ends_on": ends or None}

    # ------------------------------------------------------------------ what the record shows for the last days (counts from the graph, no claims about health)
    async def care_outcomes(self, person: str, days: int = 7, now: Optional[int] = None) -> dict:
        """Counts from the record over the last `days` local days: doses marked given against the times that were due, entries recorded or marked as mistakes, and
        what is flagged now. It counts what people recorded in this circle; it does not say anyone is better or worse, and it is not a comparison with other circles."""
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 90:
            raise ValueError("days is a whole number from 1 to 90")
        import datetime as dt
        t = now_ms() if now is None else now
        tz = await self._tz()
        today = sched.local_date(t, tz)
        first = today - dt.timedelta(days=days - 1)
        p = norm(person)
        reg = await self.care_regimen(person, t)
        gives = {r[0] for r in await self._q("MATCH (g:Give {person:$p}) WHERE g.slot >= $a RETURN g.key", {"p": p, "a": first.isoformat()}, scope="read")}
        due = given = 0
        for r in reg:
            if r["as_needed"] or not r["slots"]:
                continue
            started = sched.local_date(r["since"], tz) if r.get("since") else first
            for n in range(days):
                day = first + dt.timedelta(days=n)
                if day < started:
                    continue
                for hhmm in r["slots"]:
                    if r.get("ends_on") and day.isoformat() > r["ends_on"]:
                        continue
                    if sched.slot_moment_ms(day, hhmm, tz) + 90 * 60_000 > t:        # a slot still inside its window is not a miss yet
                        continue
                    due += 1
                    given += f"{p}|{norm(r['drug'])}|{day.isoformat()} {hhmm}" in gives
        since_ms = sched.slot_moment_ms(first, "00:00", tz)
        rec = (await self._q("MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p}) WHERE x.created_at >= $s RETURN count(x)", {"p": p, "s": since_ms}, scope="read"))[0][0]
        mist = (await self._q("MATCH (x:Dose {status:'mistake'})-[:FOR]->(:Person {id:$p}) WHERE x.mistake_at >= $s RETURN count(x)", {"p": p, "s": since_ms}, scope="read"))[0][0]
        chk = await self.care_check(person, t)
        div = await self.care_divergence(person, t)
        unseen = sum(len(c["unacknowledged"]) for c in div["carers"].values())
        return {"days": days, "from": first.isoformat(), "to": today.isoformat(), "tz": tz,
                "doses_due": due, "doses_marked_given": given, "doses_not_marked": due - given,
                "entries_recorded": rec, "entries_marked_mistake": mist,
                "flagged_now": len(chk["direct"]) + len(chk["enzyme_paths"]), "possible_duplicates_now": len(chk.get("duplicates", [])), "changes_not_yet_seen": unseen,
                "note": "Counts of what people recorded in this circle. A dose that was taken but not marked counts as not marked. This says nothing about health and is not compared with anyone else."}

    # ------------------------------------------------------------------ how many doses are left in the pack
    async def care_stock_set(self, dose_id: str, doses_left: int) -> dict:
        """Record how many doses are left in the pack of this entry (counted by a person, today). Doses marked given after this are taken off it."""
        if isinstance(doses_left, bool) or not isinstance(doses_left, int) or not 0 <= doses_left <= 9999:
            raise ValueError("doses left is a whole number from 0 to 9999")
        rows = await self._q("MATCH (x:Dose {id:$id, status:'confirmed', cur:true, action:'set'}) RETURN x.drug", {"id": dose_id}, scope="write")
        if not rows:
            raise KeyError(dose_id)
        await self._q("MATCH (x:Dose {id:$id}) SET x.stock=$n, x.stock_at=$t, x.stock_by=$by", {"id": dose_id, "n": doses_left, "t": now_ms(), "by": norm(self.agent)}, checked=True)
        return {"id": dose_id, "drug": rows[0][0], "doses_left": doses_left}

    async def care_stock(self, person: str, now: Optional[int] = None) -> list[dict]:
        """For each current entry with a pack count: the doses left now (the count minus the doses marked given since it was counted) and, when it has fixed
        times, about how many days that lasts. It works from what people recorded: a pack can also be used up another way, so it says 'about' and 'on the record'."""
        t = now_ms() if now is None else now
        tz = await self._tz()
        reg = {r["id"]: r for r in await self.care_regimen(person, t)}
        out = []
        for did, drug, n, at in await self._q(
                "MATCH (x:Dose {status:'confirmed', cur:true, action:'set'})-[:FOR]->(:Person {id:$p}) WHERE x.stock IS NOT NULL RETURN x.id, x.drug, x.stock, x.stock_at",
                {"p": norm(person)}, scope="read"):
            r = reg.get(did)
            if r is None:                                                    # a course that has ended is not listed
                continue
            used = (await self._q("MATCH (g:Give {person:$p, drug:$d}) WHERE g.at >= $s RETURN count(g)", {"p": norm(person), "d": norm(drug), "s": at}, scope="read"))[0][0]
            left = max(0, int(n) - int(used))
            per_day = len(r["slots"] or [])
            days = left // per_day if per_day else None
            out.append({"dose_id": did, "drug": drug, "doses_left": left, "counted": int(n), "counted_at": at, "per_day": per_day, "days_left": days,
                        "runs_out_on": (sched.local_date(t, tz) + __import__("datetime").timedelta(days=days)).isoformat() if days is not None else None})
        out.sort(key=lambda x: (x["days_left"] is None, x["days_left"] if x["days_left"] is not None else 0, x["drug"]))
        return out

    # ------------------------------------------------------------------ the checklist
    async def care_today(self, person: str, now: Optional[int] = None) -> dict:
        """Today's confirmed dose slots in the circle's time zone, in clock order, each with its state: given (and by whom), due, not marked given yet, or
        upcoming. Also the medicines that have no times yet ('unscheduled') and those taken as needed. It reports what is recorded; it does not advise."""
        t = now_ms() if now is None else now
        tz = await self._tz()
        today = sched.local_date(t, tz)
        reg = await self.care_regimen(person, t)
        gives = {r[0]: (r[1], r[2], r[3]) for r in await self._q(
            "MATCH (g:Give {person:$p}) WHERE g.slot STARTS WITH $d RETURN g.key, g.by, g.at, g.witness", {"p": norm(person), "d": today.isoformat()}, scope="read")}
        watched = {r[0] for r in await self._q("MATCH (w:Watch) WHERE w.key STARTS WITH $k RETURN w.key", {"k": norm(person) + "|"}, scope="read")}
        items, unscheduled, as_needed = [], [], []
        for r in reg:
            if r["as_needed"]:
                as_needed.append({"dose_id": r["id"], "drug": r["drug"], "dose_text": r["dose_text"], "freq_text": r["freq_text"]})
                continue
            if not r["slots"]:
                unscheduled.append({"dose_id": r["id"], "drug": r["drug"], "dose_text": r["dose_text"], "freq_text": r["freq_text"], "suggestion": sched.suggest(r["freq_text"])})
                continue
            for hhmm in r["slots"]:
                slot = f"{today.isoformat()} {hhmm}"
                moment = sched.slot_moment_ms(today, hhmm, tz)
                got = gives.get(f"{norm(person)}|{norm(r['drug'])}|{slot}")
                items.append({"dose_id": r["id"], "drug": r["drug"], "dose_text": r["dose_text"], "freq_text": r["freq_text"], "time": hhmm, "slot": slot, "at": moment,
                              "state": sched.slot_state(t, moment, got is not None), "given_by": got[0] if got else None, "given_at": got[1] if got else None,
                              "needs_second_carer": bool(got) and f"{norm(person)}|{norm(r['drug'])}" in watched and not got[2]})
        items.sort(key=lambda i: (i["at"], i["drug"]))
        counts = {k: sum(1 for i in items if i["state"] == k) for k in ("given", "due", "not_marked", "upcoming")}
        return {"person": norm(person), "tz": tz, "date": today.isoformat(), "items": items, "counts": counts, "unscheduled": unscheduled, "as_needed": as_needed}

    async def care_give_slot(self, person: str, dose_id: str, time: str, now: Optional[int] = None) -> dict:
        """Mark one of today's confirmed slots as given. Same once-per-slot claim as care_give: if someone already marked it, this says who."""
        t = now_ms() if now is None else now
        rows = await self._q("MATCH (x:Dose {id:$id, status:'confirmed', cur:true, action:'set'})-[:FOR]->(:Person {id:$p}) RETURN x.drug, x.slots",
                             {"id": dose_id, "p": norm(person)}, scope="read")
        if not rows:
            raise KeyError(dose_id)
        drug, slots = rows[0]
        if time not in (slots or []):
            raise ValueError(f"{time} is not one of this medicine's times ({', '.join(slots or []) or 'none set'})")
        day = sched.local_date(t, await self._tz())
        return await self.care_give(person, drug, f"{day.isoformat()} {time}")

    # ------------------------------------------------------------------ reminders about the checklist
    async def care_slot_nudges(self, person: str, now: Optional[int] = None, hold: Optional[set] = None) -> list[dict]:
        """Reminders for today's slots, each produced once per carer: when a slot is due ('Metformin 08:00 is due') and when it is still not marked given
        90 minutes later. Said about the record, not about the person. A slot already marked given produces none."""
        if self._guard:
            await self._guard("write")
        t = now_ms() if now is None else now
        today = await self.care_today(person, t)
        carers = [r[0] for r in await self._q("MATCH (c:Person {role:'carer'}) RETURN c.id ORDER BY c.id", scope="read", checked=True)]
        out = []
        for s in await self.care_stock(person, t):                         # a pack with about three days or fewer left on the record: said once per carer per count
            if s["days_left"] is None or s["days_left"] > 3:
                continue
            for c in carers:
                if hold and c.lower() in hold:
                    continue
                key = f"stock|{norm(person)}|{norm(s['drug'])}|{s['counted_at']}|{c}"
                r = await self._q("MERGE (n:Nudge {key:$k}) ON CREATE SET n.at=$t, n.fresh=true WITH n, n.fresh AS fresh SET n.fresh=false RETURN fresh", {"k": key, "t": t}, checked=True)
                if r[0][0]:
                    out.append({"kind": "stock", "notify": c, "drug": s["drug"], "slot": "",
                                "message": {"text": f"{s['drug'].capitalize()}: about {s['days_left']} day{'s' if s['days_left'] != 1 else ''} of doses left on the record ({s['doses_left']}). Please check the pack.", "source": "template"}})
        for i in today["items"]:
            if i["state"] not in ("due", "not_marked"):
                continue
            for c in carers:
                if hold and c.lower() in hold:
                    continue
                key = f"slot|{i['state']}|{norm(person)}|{norm(i['drug'])}|{i['slot']}|{c}"
                r = await self._q("MERGE (n:Nudge {key:$k}) ON CREATE SET n.at=$t, n.fresh=true WITH n, n.fresh AS fresh SET n.fresh=false RETURN fresh",
                                  {"k": key, "t": t}, checked=True)
                if not r[0][0]:
                    continue
                what = f"{i['drug'].capitalize()} {i['dose_text']}".strip()
                text = (f"{what}, {i['time']}: due now." if i["state"] == "due" else f"{what}, {i['time']}: not marked as given yet. Please check with the others and mark it if it was given.")
                out.append({"kind": "slot_" + i["state"], "notify": c, "drug": i["drug"], "slot": i["slot"], "message": {"text": text, "source": "template"}})
        return out
