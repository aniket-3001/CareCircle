"""Telegram front door: the same circle, reached by chatting. No app to install.

The bot is a thin shell: every decision comes from the circle graph. A chat is linked to (agent key, circle). Text, photos and voice notes
become PROPOSALS shown with their source quote; nothing is saved until the person taps Confirm. Nothing here ever gives dosing advice.

`Bot.handle(update)` works over an injected `api` so it is fully testable offline; `poll()` runs it against the real Telegram API.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from typing import Optional

from carecircle import intake
from carecircle.safety import scan_advice

HELP = ("Care Circle records and cross-checks medicines for the person you look after. It never says what to take or stop.\n"
        "/link <key> <circle> - connect this chat\n/who - people in the circle\n/regimen <person> - what is on record now\n"
        "/check <person> - possible interactions (with sources)\n/history - what happened, newest first\n/ack - acknowledge pending changes\n"
        "/gave <person> <medicine> <slot> - record a dose given\nSend a photo, voice note or text about a medicine to add it.")


class TgApi:
    """Real Telegram HTTP client (stdlib only). Tests inject a fake with the same methods."""

    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.file_base = f"https://api.telegram.org/file/bot{token}/"

    def call(self, method: str, **params) -> dict:
        req = urllib.request.Request(self.base + method, data=json.dumps(params).encode(), headers={"content-type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=60))["result"]

    def send(self, chat: int, text: str, buttons: Optional[list] = None) -> None:
        extra = {"reply_markup": {"inline_keyboard": buttons}} if buttons else {}
        self.call("sendMessage", chat_id=chat, text=text[:3900], **extra)

    def download(self, file_id: str) -> tuple[bytes, str]:
        path = self.call("getFile", file_id=file_id)["file_path"]
        return urllib.request.urlopen(self.file_base + path, timeout=60).read(), path


class _OffLoop:
    """Telegram's client is blocking (urllib, up to 60 s). The bot shares one process with the web server, so every send runs in a worker thread:
    a slow Telegram answer then delays that one message, not every request on the server."""

    def __init__(self, api):
        self._api = api

    async def send(self, chat: int, text: str, buttons: Optional[list] = None) -> None:
        await asyncio.to_thread(self._api.send, chat, text, buttons)

    def __getattr__(self, name):
        return getattr(self._api, name)


class Bot:
    def __init__(self, gm, api, checker):
        self.gm, self.api, self.checker = gm, _OffLoop(api), checker

    async def _hold(self, cid: str, chat: int, data: dict) -> None:
        """Proposals wait for a human in the control graph, not in memory, so a restart or deploy does not expire the Confirm button."""
        g = await self.gm._ctl()
        await g.query("MATCH (o:TgPending) WHERE o.at < $old DELETE o", {"old": int(time.time()) - 7 * 86400})
        await g.query("CREATE (:TgPending {id:$i, chat:$c, data:$d, at:$t})", {"i": cid, "c": chat, "d": json.dumps(data), "t": int(time.time())})

    async def _take(self, cid: str, chat: int) -> Optional[dict]:
        g = await self.gm._ctl()
        r = (await g.query("MATCH (o:TgPending {id:$i, chat:$c}) WITH o, o.data AS d DELETE o RETURN d", {"i": cid, "c": chat})).result_set
        return json.loads(r[0][0]) if r else None

    async def _link(self, chat: int) -> Optional[dict]:
        g = await self.gm._ctl()
        r = (await g.query("MATCH (c:TgChat {chat:$c}) RETURN c.agent, c.circle", {"c": chat})).result_set
        return {"agent": r[0][0], "circle": r[0][1]} if r else None

    async def handle(self, u: dict) -> None:
        if "callback_query" in u:
            return await self._callback(u["callback_query"])
        m = u.get("message") or {}
        chat = (m.get("chat") or {}).get("id")
        if chat is None:
            return
        text = (m.get("text") or "").strip()
        if text.startswith("/start") or text.startswith("/help"):
            return await self.api.send(chat, HELP)
        if text.startswith("/link"):
            return await self._cmd_link(chat, text.split())
        link = await self._link(chat)
        if not link:
            return await self.api.send(chat, "Please link this chat first: /link <key> <circle>")
        if text.startswith("/circles"):
            return await self._cmd_circles(chat, link, text.split())
        mem = self.gm.open(link["agent"], link["circle"])
        arg = (text.split() + ["", ""])[1]
        if not arg and text.startswith(("/regimen", "/check", "/ack", "/history")):
            arg = await self._patient(mem)                          # "/regimen" alone means the circle's person
        try:
            if text.startswith("/who"):
                p = await mem.care_people()
                return await self.api.send(chat, f"Cared for: {', '.join(p['patients']) or '-'}\nCarers: {', '.join(p['carers']) or '-'}")
            if text.startswith("/regimen"):
                reg = await mem.care_regimen(arg)
                return await self.api.send(chat, "\n".join(f"- {r['drug']} {r['dose_text']} {r['freq_text']} (by {r['by']}, via {r['source']})"
                                                     for r in reg) or "Nothing on record yet.")
            if text.startswith("/check"):
                return await self.api.send(chat, self._format_check(await mem.care_check(arg)))
            if text.startswith("/history"):
                tl = await mem.care_timeline(arg or await self._patient(mem), limit=8)
                return await self.api.send(chat, chr(10).join(f"- {e['text']} ({e['ago']})" for e in tl) or "Nothing recorded yet.")
            if text.startswith("/ack"):
                return await self._cmd_ack(chat, mem, arg)
            if text.startswith("/gave"):
                parts = text.split(maxsplit=3)
                if len(parts) < 4:
                    return await self.api.send(chat, "Usage: /gave <person> <medicine> <slot>, e.g. /gave asha metformin 2026-10-16 08:00")
                r = await mem.care_give(parts[1], parts[2], parts[3])
                return await self.api.send(chat, "Recorded." if r["given"] else f"Already recorded by {r['already_given_by']}. {r['note']}")
            if "photo" in m or "voice" in m or "audio" in m or "document" in m:
                return await self._media(chat, m)
            if text and not text.startswith("/"):
                return await self._propose(chat, intake._done("typed", text, "text"), None)
        except KeyError:
            return await self.api.send(chat, "I could not find that.")
        await self.api.send(chat, HELP)

    @staticmethod
    async def _patient(mem) -> str:
        patients = (await mem.care_people())["patients"]
        return patients[0] if patients else "mum"

    async def _cmd_link(self, chat, parts):
        """`/link <code>` with the six-character code from the Account page (preferred), or `/link <key> <circle>` for an API key."""
        if len(parts) < 2:
            return await self.api.send(chat, "Usage: /link <code from your Account page>")
        g = await self.gm._ctl()
        if not parts[1].startswith("gm_"):
            from carecircle.accounts import Accounts
            acc = Accounts(self.gm)
            if not await acc.hit(f"tglink|{chat}", 8, 900):
                return await self.api.send(chat, "Too many tries. Wait a few minutes.")
            agent = await acc.redeem_telegram_code(parts[1])
            if not agent:
                return await self.api.send(chat, "That code is not valid or has expired. Make a new one on the Account page.")
            circles = await acc.circles(agent)
            if not circles:
                return await self.api.send(chat, "Your account has no circle yet. Create one in the app, then link again.")
            want = parts[2].lower() if len(parts) > 2 else ""
            pick = next((c for c in circles if c["id"] == want or c["name"].lower() == want), circles[0])
            # one chat per account: linking a new one replaces the old one, which is told
            old = [r[0] for r in (await g.query("MATCH (c:TgChat {agent:$a}) WHERE c.chat <> $c RETURN c.chat", {"a": agent, "c": chat})).result_set]
            await g.query("MATCH (c:TgChat {agent:$a}) WHERE c.chat <> $c DELETE c", {"a": agent, "c": chat})
            await g.query("MERGE (c:TgChat {chat:$c}) SET c.agent=$a, c.circle=$t", {"c": chat, "a": agent, "t": pick["id"]})
            for o in old:
                await self.api.send(o, "This chat was unlinked: the account now uses another Telegram chat. Link again from the Account page if you want it back.")
            return await self.api.send(chat, f"Linked to {pick['name']}. Send a photo, voice note or text about a medicine. /circles lists your circles.")
        if len(parts) < 3:
            return await self.api.send(chat, "Usage: /link <key> <circle>")
        agent = await self.gm.authenticate(parts[1])
        if not agent or parts[2] not in await self.gm.tenants_of(agent):
            return await self.api.send(chat, "That key does not give access to that circle.")
        await g.query("MERGE (c:TgChat {chat:$c}) SET c.agent=$a, c.circle=$t", {"c": chat, "a": agent, "t": parts[2]})
        await self.api.send(chat, f"Linked as {agent} to circle {parts[2]}. Send a photo, voice note or text about a medicine.")

    async def _cmd_circles(self, chat, link, parts):
        from carecircle.accounts import Accounts
        acc = Accounts(self.gm)
        circles = await acc.circles(link["agent"])
        if not circles:
            return await self.api.send(chat, "This chat is linked with a key, not an account, so it has one circle.")
        if len(parts) > 1 and parts[1].isdigit() and 1 <= int(parts[1]) <= len(circles):
            pick = circles[int(parts[1]) - 1]
            g = await self.gm._ctl()
            await g.query("MATCH (c:TgChat {chat:$c}) SET c.circle=$t", {"c": chat, "t": pick["id"]})
            return await self.api.send(chat, f"Now using {pick['name']}.")
        nl = chr(10)
        await self.api.send(chat, nl.join(f"{n}. {c['name']}{' (here)' if c['id'] == link['circle'] else ''}" for n, c in enumerate(circles, 1)) + nl + "Send /circles <number> to switch.")

    async def _media(self, chat, m):
        item = (m.get("photo") or [None])[-1] or m.get("voice") or m.get("audio") or m.get("document")
        data, path = await asyncio.to_thread(self.api.download, item["file_id"])
        name = (m.get("document") or {}).get("file_name") or path
        src = await asyncio.to_thread(intake.read_source, data, name, "")
        await self._propose(chat, src, data if src["kind"] == "image" else None)

    async def _propose(self, chat, src, image):
        if src["status"] != "ok":
            return await self.api.send(chat, src.get("note") or "I could not read that. Please type the medicine name.")
        props = await asyncio.to_thread(intake.propose, src["text"], self.checker, image, "jpeg")
        if not props:
            return await self.api.send(chat, "I did not find a medicine name. Please type it.")
        kinds = {"image": "photo", "voice": "voice", "document": "document"}
        link = await self._link(chat)
        who = await self._patient(self.gm.open(link["agent"], link["circle"])) if link else "mum"   # the circle's person
        sid = ""
        if link and kinds.get(src["kind"]):                          # keep what was read, so the saved entry can be checked against it and points back at it
            sid = await self.gm.open(link["agent"], link["circle"]).care_store_source(src["kind"], src["text"])
        for p in props[:4]:
            cid = os.urandom(4).hex()
            top = p["drug_candidates"][0]["name"]
            await self._hold(cid, chat, {"drug": top, "dose_text": p.get("dose_text", ""), "freq_text": p.get("freq_text", ""),
                                 "quote": p["quote"], "source_ref": sid, "source_type": kinds.get(src["kind"], "typed")})
            alt = ", ".join(c["name"] for c in p["drug_candidates"][1:])
            await self.api.send(chat, f"I read: {top} {p.get('dose_text', '')} {p.get('freq_text', '')}\nFrom: \"{p['quote'][:120]}\""
                                f"{' (quote verified)' if p.get('verified') else ' (could not verify the quote)'}"
                                f"{chr(10) + 'Other matches: ' + alt if alt else ''}\nIs this right? It is saved only when you confirm.",
                          [[{"text": f"Confirm for {who}", "callback_data": f"ok|{cid}|{who}"}, {"text": "Discard", "callback_data": f"no|{cid}|"}]])

    async def _callback(self, cq):
        chat = cq["message"]["chat"]["id"]
        kind, cid, person = (cq.get("data", "||").split("|") + ["", ""])[:3]
        link = await self._link(chat)
        p = await self._take(cid, chat)
        if not link or not p or kind != "ok":
            return await self.api.send(chat, "Discarded." if kind == "no" else "That request expired.")
        mem = self.gm.open(link["agent"], link["circle"])
        r = await mem.care_record(person or await self._patient(mem), p["drug"], dose_text=p["dose_text"], freq_text=p["freq_text"],
                                  source_type=p["source_type"], quote=p["quote"], source_ref=p.get("source_ref", ""),
                                  source_text=p.get("source_text", ""))
        if r["status"] == "pending":
            await mem.care_confirm(r["id"])                          # the person just confirmed by tapping
        await self.api.send(chat, f"Saved {p['drug']} for {person or 'the person'}. Other carers will be asked to acknowledge it.")

    async def _cmd_ack(self, chat, mem, person):
        div = await mem.care_divergence(person or await self._patient(mem))
        me = (await self._link(chat))["agent"].lower()
        todo = div["carers"].get(me, {}).get("unacknowledged", [])
        for u in todo:
            await mem.care_ack(u["dose"])
        await self.api.send(chat, f"Acknowledged {len(todo)} change(s)." if todo else "Nothing waiting for you.")

    @staticmethod
    def _format_check(c: dict) -> str:
        j = c["judgement"]
        lines = [j["statement"]] + [f"- {x}" for x in j["reasons"]]
        for f in c["direct"]:
            lines.append(f"- {f['drugs'][0]} + {f['drugs'][1]}: {f['level']} ({f['source']})")
        for f in c["enzyme_paths"]:
            lines.append(f"- {f['meaning']} [{f['source']}]")
        lines.append(c["notice"])
        out = "\n".join(lines)
        assert not scan_advice(out), "advice slipped into a message"
        return out

    async def deliver_nudges(self, now: Optional[int] = None) -> int:
        """Send each due reminder once (care_nudges claims it) to every place its recipient asked for it: the linked chat and any browser that allowed
        notifications. One claim, several channels, so a reminder is never produced twice however many ways it is delivered."""
        from . import webpush
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
        sent = 0
        from .accounts import Accounts
        hold = await Accounts(self.gm).quiet_now(now if now is not None else int(time.time() * 1000))
        for circle, members in circles.items():
            mem = self.gm.open(sorted(members)[0], circle)
            for person in (await mem.care_people())["patients"]:
                for n in [*await mem.care_nudges(person, now=now, hold=hold), *await mem.care_slot_nudges(person, now=now, hold=hold)]:
                    text = n["message"]["text"]
                    for chat in chats.get(n["notify"], []):
                        await self.api.send(chat, text)
                        sent += 1
                    for agent in members:
                        if agent.lower() == n["notify"]:
                            sent += await webpush.push(self.gm, agent, text)
        return sent


async def poll(gm, token: str, nudge_every: float = 20.0) -> None:                       # pragma: no cover - needs a real bot token
    """Long-poll Telegram and deliver due reminders. Neither loop may die: every failure is logged and retried after a pause."""
    from graphmem.care import checker
    api = TgApi(token)
    bot = Bot(gm, api, checker())

    async def updates():
        offset = 0
        while True:
            try:
                for u in await asyncio.to_thread(api.call, "getUpdates", offset=offset, timeout=25):
                    offset = u["update_id"] + 1
                    try:
                        await bot.handle(u)
                    except Exception as e:
                        print("handler error", type(e).__name__, e, flush=True)
            except Exception as e:
                print("poll error", type(e).__name__, e, flush=True)
                await asyncio.sleep(3)

    async def reminders():
        while True:
            try:
                n = await bot.deliver_nudges()
                if n:
                    print("reminders sent", n, flush=True)
            except Exception as e:
                print("reminder error", type(e).__name__, e, flush=True)
            await asyncio.sleep(nudge_every)

    print("telegram bot polling", flush=True)
    await asyncio.gather(updates(), reminders())
