"""Delivering reminders: one loop, independent of Telegram, safe to run in more than one process, and not lost when a send fails.

  claim      care_nudges / care_slot_nudges mark a reminder as used the moment it is produced (so two loops can never both send it).
  at least once   if every channel for a reminder fails, the claim is handed back (up to MAX_TRIES times) so the next pass sends it; if one channel got
                  through, the reminder stays used. A reminder with nowhere to go (no linked chat, no allowed browser) is used, not retried for ever.
  due-at     a circle with nothing to do is not asked again until something could be due: the next slot window or at most CHECK_CAP_S, or sooner when a
                  write through this process touches it (`touch`). That turns "ask every circle every 20 s" into "ask each circle every few minutes".
  one runner a lease in the control graph lets only one process run the loop at a time, so a second worker does not double the work (the claims would
                  still stop a double send).
  no bot needed   Web Push needs no Telegram token, so the loop starts whenever either channel exists.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import time
from typing import Awaitable, Callable, Optional

from graphmem.db import now_ms

MAX_TRIES = 5
CHECK_CAP_S = 15 * 60
LEASE_S = 60
SendChat = Callable[[int, str], Awaitable[None]]


class Reminders:
    def __init__(self, gm, send_chat: Optional[SendChat] = None):
        self.gm, self.send_chat = gm, send_chat
        self.wake: dict[str, int] = {}                              # circle -> the earliest time anything could be due there
        self.me = secrets.token_hex(6)

    def touch(self, circle: str) -> None:
        """Something was written in this circle: look at it on the next pass."""
        self.wake.pop(circle, None)

    # ------------------------------------------------------------------ the lease
    async def lease(self, now_s: Optional[float] = None) -> bool:
        """True when this process holds (or just took) the right to run the loop. One conditional write, so racing processes cannot both win."""
        t = int(time.time() if now_s is None else now_s)
        g = await self.gm._ctl()
        rows = (await g.query(
            """MERGE (l:Lease {key:'reminders'})
               ON CREATE SET l.holder = $me, l.until = $u
               WITH l, (l.holder = $me OR l.until < $t) AS ok
               FOREACH (_ IN CASE WHEN ok THEN [1] ELSE [] END | SET l.holder = $me, l.until = $u)
               RETURN l.holder""", {"me": self.me, "u": t + LEASE_S, "t": t})).result_set
        return rows[0][0] == self.me

    # ------------------------------------------------------------------ one pass
    async def deliver(self, now: Optional[int] = None, use_wake: bool = True) -> int:
        """Send each due reminder to every place its recipient asked for it: the linked chat and any browser that allowed notifications."""
        from . import webpush
        from .accounts import Accounts
        t = now if now is not None else now_ms()
        g = await self.gm._ctl()
        chats: dict[str, list] = {}
        circles: dict[str, set] = {}
        for chat, agent, circle in (await g.query("MATCH (c:TgChat) RETURN c.chat, c.agent, c.circle")).result_set:
            chats.setdefault(agent.lower(), []).append(chat)
            circles.setdefault(circle, set()).add(agent)
        if webpush.enabled():
            subbed = {r[0] for r in (await g.query("MATCH (s:PushSub) RETURN DISTINCT s.agent")).result_set}
            for agent, circle in (await g.query("MATCH (a:Account)-[:MEMBER]->(t:Tenant) RETURN a.agent, t.id")).result_set:
                if agent in subbed:
                    circles.setdefault(circle, set()).add(agent)
        hold = await Accounts(self.gm).quiet_now(t)
        sent = 0
        for circle, members in circles.items():
            if use_wake and self.wake.get(circle, 0) > t:
                continue                                            # nothing can be due there yet
            mem = self.gm.open(sorted(members)[0], circle)
            for person in (await mem.care_people())["patients"]:
                for n in [*await mem.care_nudges(person, now=now, hold=hold), *await mem.care_slot_nudges(person, now=now, hold=hold)]:
                    sent += await self._send(mem, n, members, chats, webpush)
            if use_wake:
                self.wake[circle] = await self._next_wake(mem, t)
        return sent

    async def _send(self, mem, n: dict, members: set, chats: dict, webpush) -> int:
        text = n["message"]["text"]
        got, tried, failed, via = 0, 0, 0, []
        for chat in chats.get(n["notify"], []):
            if self.send_chat is None:
                continue
            tried += 1
            try:
                await self.send_chat(chat, text)
                got += 1
                via.append("telegram")
            except Exception as e:
                failed += 1
                print("reminder send error", type(e).__name__, flush=True)
        for agent in members:
            if agent.lower() == n["notify"] and webpush.enabled():
                tried += 1
                try:
                    r = await webpush.push_status(self.gm, agent, text)
                    got += r["sent"]
                    via += ["browser"] * r["sent"]
                    failed += r["failed"]                           # a 503 or a timeout is a failure to retry; a device that is gone, or none allowed, is "nowhere to go"
                except Exception as e:
                    failed += 1
                    print("reminder push error", type(e).__name__, flush=True)
        if got == 0 and failed > 0 and n.get("claim"):
            await mem.care_nudge_release(n["claim"], MAX_TRIES)     # every attempt failed: hand the reminder back so the next pass sends it
        if got > 0:
            try:
                await mem.care_reminder_logged(n, via)               # it went out: keep that, so "has Meena been reminded?" has an answer
            except Exception as e:                                   # never let the log stop a delivery
                print("reminder log error", type(e).__name__, flush=True)
        return got

    async def _next_wake(self, mem, t: int) -> int:
        """The next moment anything could be due in this circle: a slot becoming due (an hour before it) or going unmarked (90 minutes after), else the cap."""
        wake = t + CHECK_CAP_S * 1000
        try:
            for person in (await mem.care_people())["patients"]:
                for m in await mem.care_slot_edges(person, t):
                    if m > t:
                        wake = min(wake, m)
        except Exception:
            return t                                                # on any doubt, look again next pass
        return wake

    # ------------------------------------------------------------------ the loop
    async def run(self, every: float = 20.0) -> None:                                           # pragma: no cover - a long-running loop
        """Neither a failed pass nor a lost lease may end the loop."""
        print("reminder loop started", flush=True)
        while True:
            try:
                if await self.lease():
                    n = await self.deliver()
                    if n:
                        print("reminders sent", n, flush=True)
            except Exception as e:
                print("reminder error", type(e).__name__, e, flush=True)
            await asyncio.sleep(every)


def wanted() -> bool:
    from . import webpush
    return bool(os.getenv("TELEGRAM_BOT_TOKEN")) or webpush.enabled()
