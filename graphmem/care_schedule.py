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

from .db import new_id, norm, now_ms
from .textcheck import product_name, shown_name

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
        args = {"id": dose_id, "s": slots, "a": bool(as_needed), "e": ends, "by": norm(self.agent), "t": now_ms()}
        # the times belong to the tablet (the product), so every ingredient of a combination shares them by construction
        await self._q("MATCH (:Dose {id:$id})-[:VIA]->(pr:Product) SET pr.slots=$s, pr.as_needed=$a, pr.ends_on=$e, pr.sched_by=$by, pr.sched_at=$t, pr.sched_first=coalesce(pr.sched_first, $t)",
                      args, checked=True)
        # a copy on its current entries, for one release, so a server rolled back to the previous version still reads the times
        await self._q("MATCH (:Dose {id:$id})-[:VIA]->(pr:Product)<-[:VIA]-(y:Dose {status:'confirmed', cur:true, action:'set'}) "
                      "SET y.slots=$s, y.as_needed=$a, y.ends_on=$e, y.sched_by=$by, y.sched_at=$t, y.sched_first=coalesce(y.sched_first, $t)", args, checked=True)
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
        origins = await self._origins(person)
        gives = {r[0] for r in await self._q("MATCH (g:Give {person:$p}) WHERE g.slot >= $a RETURN g.key", {"p": p, "a": first.isoformat()}, scope="read")}
        due = given = 0
        seen_products: set = set()
        for r in reg:
            if r["as_needed"] or not r["slots"]:
                continue
            if r.get("product"):
                key = (r["product"], tuple(r["slots"]), r.get("ends_on"))
                if key in seen_products:
                    continue                                        # another ingredient of the same tablet: counted once
                seen_products.add(key)
            origin = origins.get((r["drug"], r.get("product") or ""), r.get("since") or 0)
            started = sched.local_date(origin, tz) if origin else first
            for n in range(days):
                day = first + dt.timedelta(days=n)
                if day < started:
                    continue
                for hhmm in r["slots"]:
                    if r.get("ends_on") and day.isoformat() > r["ends_on"]:
                        continue
                    if origin and sched.slot_moment_ms(day, hhmm, tz) < origin:
                        continue                                    # before the entry was recorded: it cannot have been missed
                    if sched.slot_moment_ms(day, hhmm, tz) + 90 * 60_000 > t:        # a slot still inside its window is not a miss yet
                        continue
                    due += 1
                    given += f"{p}|{norm(r['drug'])}|{day.isoformat()} {hhmm}" in gives or f"{p}|{norm(r['drug'])}|{day.isoformat()} {hhmm}|also" in gives
        since_ms = sched.slot_moment_ms(first, "00:00", tz)
        rec = (await self._q("MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p}) WHERE x.created_at >= $s RETURN count(x)", {"p": p, "s": since_ms}, scope="read"))[0][0]
        mist = (await self._q("MATCH (x:Dose {status:'mistake'})-[:FOR]->(:Person {id:$p}) WHERE x.mistake_at >= $s RETURN count(x)", {"p": p, "s": since_ms}, scope="read"))[0][0]
        chk = await self.care_check(person, t)
        div = await self.care_divergence(person, t)
        unseen = sum(len(c["unacknowledged"]) for c in div["carers"].values())
        stopped = (await self._q("MATCH (v:Prevented {person:$p}) WHERE v.at >= $s RETURN count(v)", {"p": p, "s": since_ms}, scope="read"))[0][0]
        late = (await self._q("MATCH (:Person)-[a:ACKED]->(x:Dose)-[:FOR]->(:Person {id:$p}) WHERE a.at >= $s AND a.at - x.at > $h RETURN count(a)",
                              {"p": p, "s": since_ms, "h": 4 * 3_600_000}, scope="read"))[0][0]
        return {"days": days, "from": first.isoformat(), "to": today.isoformat(), "tz": tz,
                "doses_due": due, "doses_marked_given": given, "doses_not_marked": due - given,
                "entries_recorded": rec, "entries_marked_mistake": mist,
                "flagged_now": len(chk["direct"]) + len(chk["enzyme_paths"]), "possible_duplicates_now": len(chk.get("duplicates", [])), "changes_not_yet_seen": unseen,
                "double_doses_stopped": stopped, "changes_seen_late": late,
                "note": "Counts of what people recorded in this circle. A dose that was taken but not marked counts as not marked. \"Double doses stopped\" is how often a carer tried to mark a slot someone else had already marked; \"seen late\" is changes a carer acknowledged more than 4 hours after they were made. This says nothing about health and is not compared with anyone else."}

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
    @staticmethod
    def _groups(reg: list[dict]) -> list[dict]:
        """The checklist's rows: a medicine that came as a combination product (Telma-AM saved as telmisartan and amlodipine) is ONE row, one tablet with one tick;
        the entries stay one per ingredient underneath. {members, product, label, ingredients}."""
        out, byp = [], {}
        for r in reg:
            if not r.get("product"):
                out.append({"members": [r], "product": "", "label": "", "ingredients": []})
            elif (r.get("product_key") or r["product"]) in byp:                     # the tablet is a node: its entries are the ones that point at the same one
                byp[r.get("product_key") or r["product"]]["members"].append(r)
            else:
                byp[r.get("product_key") or r["product"]] = {"members": [r], "product": r["product"], "label": r["product"], "ingredients": []}
                out.append(byp[r.get("product_key") or r["product"]])
        for g in out:
            if g["product"] and len(g["members"]) > 1:                 # a combination: one tablet, several ingredients
                g["ingredients"] = [m["drug"] for m in g["members"]]
            elif g["product"]:                                         # a one-ingredient brand (Storvas): the medicine's own row, with its brand kept
                g["brand"], g["label"] = g["product"], ""
        return out

    async def _origins(self, person: str) -> dict:
        """When each (medicine, product) was first on record in its current run: the earliest confirmed entry since the last stop. A change of dose is a new
        entry but not a new start, so a slot earlier today under the old dose is not 'before the entry existed'."""
        rows = await self._q("MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p}) OPTIONAL MATCH (x)-[:VIA]->(pr:Product) RETURN x.drug, coalesce(pr.combo, x.product, ''), x.action, x.valid_from",
                             {"p": norm(person)}, scope="read")
        stops: dict = {}
        for d, pr, a, vf in rows:
            if a == "stop":
                stops[(d, pr)] = max(stops.get((d, pr), 0), vf)
        out: dict = {}
        for d, pr, a, vf in rows:
            if a == "set" and vf >= stops.get((d, pr), 0):
                out[(d, pr)] = min(out.get((d, pr), vf), vf)
        return out

    @staticmethod
    def _tracked_since(r: dict, confirmed_at: dict, now: int, origin: Optional[int] = None) -> int:
        """From when the record can speak about this entry's slots: when it was recorded, and when its times were FIRST confirmed (later edits of the times do not move it; and once that moment has passed; a look at
        an earlier moment ignores it, so a look-back does not change)."""
        c = confirmed_at.get(r["id"])
        return max(int(origin if origin is not None else (r.get("since") or 0)), int(c) if c is not None and int(c) <= now else 0)

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
        confirmed_at = {r[0]: r[1] for r in await self._q("MATCH (x:Dose {status:'confirmed'})-[:FOR]->(:Person {id:$p}) OPTIONAL MATCH (x)-[:VIA]->(pr:Product) "
                                                          "WITH x, coalesce(pr.sched_first, x.sched_first) AS f WHERE f IS NOT NULL RETURN x.id, f",
                                                          {"p": norm(person)}, scope="read")}
        origins = await self._origins(person)
        items, unscheduled, as_needed = [], [], []
        for g in self._groups(reg):
            ms, first = g["members"], g["members"][0]
            base = {"dose_id": first["id"], "dose_ids": [m["id"] for m in ms], "drug": first["drug"], "freq_text": first["freq_text"],
                    "dose_text": (first["dose_text"] or first.get("product_strength", "")) if not g["label"] else next((m.get("product_strength") for m in ms if m.get("product_strength")), "")}
            if g["label"]:
                base["label"], base["ingredients"] = g["label"], g["ingredients"]
            elif g.get("brand"):
                base["brand"] = g["brand"]
            if all(m["as_needed"] for m in ms):
                as_needed.append(base)
                continue
            slots = sorted({h for m in ms for h in m["slots"]})
            if not slots:
                unscheduled.append({**base, "suggestion": sched.suggest(first["freq_text"])})
                continue
            tracked = max(self._tracked_since(m, confirmed_at, t, origins.get((m["drug"], m.get("product") or ""))) for m in ms)
            for hhmm in slots:
                slot = f"{today.isoformat()} {hhmm}"
                moment = sched.slot_moment_ms(today, hhmm, tz)
                tablet = len(ms) > 1                                  # a tablet's own give may be the second source of an ingredient another product also gave
                gots = [(gives.get(f"{norm(person)}|{norm(m['drug'])}|{slot}|also") or gives.get(f"{norm(person)}|{norm(m['drug'])}|{slot}")) if tablet
                        else (gives.get(f"{norm(person)}|{norm(m['drug'])}|{slot}") or gives.get(f"{norm(person)}|{norm(m['drug'])}|{slot}|also")) for m in ms]
                got = next((x for x in gots if x), None)
                every = all(gots)                                    # a combination is given only when every ingredient has been marked
                items.append({**base, "time": hhmm, "slot": slot, "at": moment,
                              "state": sched.slot_state(t, moment, every, tracked), "given_by": got[0] if every and got else None, "given_at": got[1] if every and got else None,
                              "needs_second_carer": every and f"{norm(person)}|{norm(first['drug'])}" in watched and not got[2]})
        items.sort(key=lambda i: (i["at"], i.get("label") or i["drug"]))
        counts = {k: sum(1 for i in items if i["state"] == k) for k in ("given", "due", "not_marked", "upcoming", "before")}
        return {"person": norm(person), "tz": tz, "date": today.isoformat(), "items": items, "counts": counts, "unscheduled": unscheduled, "as_needed": as_needed}

    async def care_give_slot(self, person: str, dose_id: str, time: str, now: Optional[int] = None, both_prescribed: bool = False) -> dict:
        """Mark one of today's confirmed slots as given. Same once-per-slot claim as care_give: if someone already marked it, this says who. A combination tablet is one claim over all its ingredients: every one is recorded or none is, and a refusal says whether the same tablet or a shared ingredient was already recorded."""
        t = now_ms() if now is None else now
        rows = await self._q("MATCH (x:Dose {id:$id, status:'confirmed', cur:true, action:'set'})-[:FOR]->(:Person {id:$p}) OPTIONAL MATCH (x)-[:VIA]->(pr:Product) "
                             "RETURN x.drug, coalesce(pr.slots, x.slots), coalesce(pr.combo, x.product, ''), coalesce(pr.key, '')", {"id": dose_id, "p": norm(person)}, scope="read")
        if not rows:
            raise KeyError(dose_id)
        drug, slots, product, pkey = rows[0]
        members = [(drug, slots)]
        if product:                                                  # one tablet of a combination: every ingredient entry that points at the same product node is marked together
            members = [(r[0], r[1]) for r in await self._q(
                "MATCH (pr:Product {key:$pk})<-[:VIA]-(x:Dose {status:'confirmed', cur:true, action:'set'}) RETURN x.drug, coalesce(pr.slots, x.slots) ORDER BY x.drug",
                {"pk": pkey}, scope="read")]
        allowed = sorted({h for _d, sl in members for h in (sl or [])})
        if time not in allowed:
            raise ValueError(f"{time} is not one of this medicine's times ({', '.join(allowed) or 'none set'})")
        day = sched.local_date(t, await self._tz())
        if len(members) == 1:
            return await self.care_give(person, drug, f"{day.isoformat()} {time}", both_prescribed)
        return await self._give_tablet(person, [d for d, _sl in members], pkey, f"{day.isoformat()} {time}", both_prescribed)

    async def _give_tablet(self, person: str, drugs: list[str], pkey: str, slot: str, both_prescribed: bool = False) -> dict:
        """Mark one tablet of a combination as given: every ingredient, or none. It is ONE write that creates the gives only if no give of any of these ingredients
        is already on record for this slot, so two carers ticking at once have exactly one winner, and a tablet is never recorded as half given (an ingredient
        already given through another entry refuses the whole tick, and nothing at all is written)."""
        from .care import parse_slot
        slot, slot_ms = parse_slot(slot)
        p, me = norm(person), norm(self.agent)
        rows = [{"drug": norm(d), "ing": self._ingredient(d), "key": f"{p}|{norm(d)}|{norm(slot)}"} for d in drugs]
        made = await self._q(
            """UNWIND $rows AS x
               OPTIONAL MATCH (e:Give {person:$p}) WHERE e.key = x.key OR (e.ing = x.ing AND e.slot_ms IS NOT NULL AND e.slot_ms = $ms)
               WITH collect(e) AS clashes WHERE size(clashes) = 0
               UNWIND $rows AS x
               CREATE (:Give {key:x.key, by:$me, at:$t, person:$p, drug:x.drug, slot:$s, ing:x.ing, slot_ms:$ms, via:$pk})
               RETURN count(*)""",
            {"rows": rows, "p": p, "ms": slot_ms, "me": me, "t": now_ms(), "s": norm(slot), "pk": pkey})
        names = [r["drug"] for r in rows]
        if made and made[0][0]:                                            # an aggregate over no rows still answers [[0]]: that is a refusal
            watched = (await self._q("MATCH (w:Watch) WHERE w.key IN $k RETURN count(w)", {"k": [f"{p}|{r['drug']}" for r in rows]}, scope="read"))[0][0] > 0
            return {"given": True, "slot": slot, "ingredients": names, **({"needs_second_carer": True} if watched else {})}
        clash = await self._q(
            "MATCH (e:Give {person:$p}) WHERE e.key IN $keys OR (e.ing IN $ings AND e.slot_ms IS NOT NULL AND e.slot_ms = $ms) RETURN e.drug, e.by, e.at, coalesce(e.via, '') ORDER BY e.at LIMIT 10",
            {"p": p, "keys": [r["key"] for r in rows], "ings": [r["ing"] for r in rows], "ms": slot_ms}, scope="read")
        if not clash:
            raise RuntimeError("the tablet could not be recorded; nothing was saved")
        same_tablet = all(c[3] == pkey for c in clash)
        first = clash[0]
        if both_prescribed and not same_tablet:                       # the same ingredient from another product really was prescribed too: record this tablet as a second source, all or none
            made2 = await self._q(
                """UNWIND $rows AS x
                   OPTIONAL MATCH (e:Give {key: x.key + '|also'})
                   WITH collect(e) AS taken WHERE size(taken) = 0
                   UNWIND $rows AS x
                   CREATE (:Give {key: x.key + '|also', by:$me, at:$t, person:$p, drug:x.drug, slot:$s, ing:x.ing, slot_ms:$ms, via:$pk, override:true})
                   RETURN count(*)""",
                {"rows": rows, "p": p, "ms": slot_ms, "me": me, "t": now_ms(), "s": norm(slot), "pk": pkey})
            if made2 and made2[0][0]:
                return {"given": True, "slot": slot, "ingredients": names, "override": True,
                        "note": "recorded as a second source: you said both were prescribed. The record shows two doses of the shared ingredient at this time."}
        await self._q("MERGE (v:Prevented {key:$k}) ON CREATE SET v.person=$p, v.drug=$d, v.slot=$s, v.by=$me, v.first_by=$by, v.at=$t",
                      {"k": f"{p}|{pkey}|{norm(slot)}|{me}", "p": p, "d": names[0], "s": norm(slot), "me": me, "by": first[1], "t": now_ms()}, checked=True)
        already = sorted({c[0] for c in clash})
        note = ("this tablet was already recorded as given; check with them before giving another dose" if same_tablet else
                f"{', '.join(already)} was already recorded as given for this time through another entry (a different product, or by hand); "
                "check with them, and with the prescriber if both were meant, before giving another dose. Nothing was recorded for this tablet.")
        return {"given": False, "duplicate": True, "already_given_by": first[1], "at": first[2], "reason": "same_tablet" if same_tablet else "shared_ingredient",
                "ingredients": names, "already": already, "note": note}

    # ------------------------------------------------------------------ reminders about the checklist
    async def care_reminder_logged(self, n: dict, channels: list) -> None:
        """Keep a record that a reminder really went out: who was told, about which entry, when, and through what. Written by the delivery loop only (not an operation a
        caller can reach), so the helper can answer "has Meena been reminded?" and an entry can show the reminders sent about it."""
        if self._guard:
            await self._guard("write")
        rid = new_id("rem")
        await self._q("CREATE (:Reminder {id:$id, kind:$k, to:$to, about_carer:$ab, drug:$d, person:$p, dose:$ds, at:$t, channels:$ch, text:$tx})",
                      {"id": rid, "k": n.get("kind", ""), "to": norm(n.get("notify", "")), "ab": norm(n.get("about_carer", "")), "d": n.get("drug", ""), "p": n.get("person", ""),
                       "ds": n.get("dose", ""), "t": now_ms(), "ch": sorted(set(channels)), "tx": (n.get("message") or {}).get("text", "")[:300]}, checked=True)
        if n.get("dose"):
            await self._q("MATCH (r:Reminder {id:$id}), (x:Dose {id:$ds}) CREATE (r)-[:ABOUT]->(x)", {"id": rid, "ds": n["dose"]}, checked=True)

    async def care_reminders_sent(self, person: str, limit: int = 30) -> list[dict]:
        """The reminders that really went out for this person, newest first: who was told, about what, when and through which channel. A reminder that was claimed but
        never delivered is not here."""
        rows = await self._q("MATCH (r:Reminder {person:$p}) RETURN r.id, r.kind, r.to, r.about_carer, r.drug, r.dose, r.at, r.channels, r.text ORDER BY r.at DESC LIMIT $n",
                             {"p": norm(person), "n": max(1, min(int(limit), 200))}, scope="read")
        return [dict(id=r[0], kind=r[1], to=r[2], about_carer=r[3], drug=r[4], dose=r[5], at=r[6], channels=list(r[7] or []), text=r[8]) for r in rows]

    async def care_slot_edges(self, person: str, now: Optional[int] = None) -> list[int]:
        """The moments today and tomorrow when a dose slot changes state (an hour before it, at it, 90 minutes after it): when a reminder could next be due.
        Used by the delivery loop to leave a quiet circle alone until then."""
        import datetime as dt
        t = now_ms() if now is None else now
        tz = await self._tz()
        today = sched.local_date(t, tz)
        out: list[int] = []
        for r in await self.care_regimen(person, t):
            if r["as_needed"] or not r["slots"]:
                continue
            for n in (0, 1):
                for hhmm in r["slots"]:
                    m = sched.slot_moment_ms(today + dt.timedelta(days=n), hhmm, tz)
                    out += [m - 60 * 60_000, m, m + 90 * 60_000]
        return sorted(set(out))

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
                    out.append({"kind": "stock", "notify": c, "drug": s["drug"], "slot": "", "claim": key,
                                "message": {"text": f"{shown_name(s['drug'])}: about {s['days_left']} day{'s' if s['days_left'] != 1 else ''} of doses left on the record ({s['doses_left']}). Please check the pack.", "source": "template"}})
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
                what = f"{product_name(i['label']) if i.get('label') else shown_name(i['drug'])} {i['dose_text']}".strip()
                text = (f"{what}, {i['time']}: due now." if i["state"] == "due" else f"{what}, {i['time']}: not marked as given yet. Please check with the others and mark it if it was given.")
                out.append({"kind": "slot_" + i["state"], "notify": c, "drug": i["drug"], "slot": i["slot"], "claim": key, "dose": i["dose_id"], "person": norm(person), "message": {"text": text, "source": "template"}})
        return out
