"""Telegram front door: the same circle, reached by chatting. No app to install.

The bot is a thin shell: every decision comes from the circle graph. A chat is linked to (agent key, circle). Text, photos and voice notes
become PROPOSALS shown with their source quote; nothing is saved until the person taps Confirm. Nothing here ever gives dosing advice.

`Bot.handle(update)` works over an injected `api` so it is fully testable offline; `poll()` runs it against the real Telegram API.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from typing import Optional

from carecircle import intake
from carecircle.safety import scan_advice

HELP = ("Care Circle records and cross-checks medicines for the person you look after. It never says what to take or stop.\n"
        "/link <key> <circle> - connect this chat\n/who - people in the circle\n/regimen <person> - what is on record now\n"
        "/check <person> - possible interactions (with sources)\n/ack - acknowledge pending changes\n"
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


class Bot:
    def __init__(self, gm, api, checker):
        self.gm, self.api, self.checker = gm, api, checker
        self.pending: dict[str, dict] = {}                 # callback id -> proposal awaiting a human

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
            return self.api.send(chat, HELP)
        if text.startswith("/link"):
            return await self._cmd_link(chat, text.split())
        link = await self._link(chat)
        if not link:
            return self.api.send(chat, "Please link this chat first: /link <key> <circle>")
        mem = self.gm.open(link["agent"], link["circle"])
        arg = (text.split() + ["", ""])[1]
        try:
            if text.startswith("/who"):
                p = await mem.care_people()
                return self.api.send(chat, f"Cared for: {', '.join(p['patients']) or '-'}\nCarers: {', '.join(p['carers']) or '-'}")
            if text.startswith("/regimen"):
                reg = await mem.care_regimen(arg)
                return self.api.send(chat, "\n".join(f"- {r['drug']} {r['dose_text']} {r['freq_text']} (by {r['by']}, via {r['source']})"
                                                     for r in reg) or "Nothing on record yet.")
            if text.startswith("/check"):
                return self.api.send(chat, self._format_check(await mem.care_check(arg)))
            if text.startswith("/ack"):
                return await self._cmd_ack(chat, mem, arg)
            if text.startswith("/gave"):
                parts = text.split(maxsplit=3)
                if len(parts) < 4:
                    return self.api.send(chat, "Usage: /gave <person> <medicine> <slot>, e.g. /gave mum metformin 2026-10-16 08:00")
                r = await mem.care_give(parts[1], parts[2], parts[3])
                return self.api.send(chat, "Recorded." if r["given"] else f"Already recorded by {r['already_given_by']}. {r['note']}")
            if "photo" in m or "voice" in m or "audio" in m or "document" in m:
                return await self._media(chat, m)
            if text and not text.startswith("/"):
                return await self._propose(chat, intake._done("typed", text, "text"), None)
        except KeyError:
            return self.api.send(chat, "I could not find that.")
        self.api.send(chat, HELP)

    async def _cmd_link(self, chat, parts):
        if len(parts) < 3:
            return self.api.send(chat, "Usage: /link <key> <circle>")
        agent = await self.gm.authenticate(parts[1])
        if not agent or parts[2] not in await self.gm.tenants_of(agent):
            return self.api.send(chat, "That key does not give access to that circle.")
        g = await self.gm._ctl()
        await g.query("MERGE (c:TgChat {chat:$c}) SET c.agent=$a, c.circle=$t", {"c": chat, "a": agent, "t": parts[2]})
        self.api.send(chat, f"Linked as {agent} to circle {parts[2]}. Send a photo, voice note or text about a medicine.")

    async def _media(self, chat, m):
        item = (m.get("photo") or [None])[-1] or m.get("voice") or m.get("audio") or m.get("document")
        data, path = await asyncio.to_thread(self.api.download, item["file_id"])
        name = (m.get("document") or {}).get("file_name") or path
        src = await asyncio.to_thread(intake.read_source, data, name, "")
        await self._propose(chat, src, data if src["kind"] == "image" else None)

    async def _propose(self, chat, src, image):
        if src["status"] != "ok":
            return self.api.send(chat, src.get("note") or "I could not read that. Please type the medicine name.")
        props = await asyncio.to_thread(intake.propose, src["text"], self.checker, image, "jpeg")
        if not props:
            return self.api.send(chat, "I did not find a medicine name. Please type it.")
        kinds = {"image": "photo", "voice": "voice", "document": "document"}
        for p in props[:4]:
            cid = os.urandom(4).hex()
            top = p["drug_candidates"][0]["name"]
            self.pending[cid] = {"drug": top, "dose_text": p.get("dose_text", ""), "freq_text": p.get("freq_text", ""),
                                 "quote": p["quote"], "source_text": src["text"], "source_type": kinds.get(src["kind"], "typed")}
            alt = ", ".join(c["name"] for c in p["drug_candidates"][1:])
            self.api.send(chat, f"I read: {top} {p.get('dose_text', '')} {p.get('freq_text', '')}\nFrom: \"{p['quote'][:120]}\""
                                f"{' (quote verified)' if p.get('verified') else ' (could not verify the quote)'}"
                                f"{chr(10) + 'Other matches: ' + alt if alt else ''}\nIs this right? It is saved only when you confirm.",
                          [[{"text": "Confirm for mum", "callback_data": f"ok|{cid}|mum"}, {"text": "Discard", "callback_data": f"no|{cid}|"}]])

    async def _callback(self, cq):
        chat = cq["message"]["chat"]["id"]
        kind, cid, person = (cq.get("data", "||").split("|") + ["", ""])[:3]
        link = await self._link(chat)
        p = self.pending.pop(cid, None)
        if not link or not p or kind != "ok":
            return self.api.send(chat, "Discarded." if kind == "no" else "That request expired.")
        mem = self.gm.open(link["agent"], link["circle"])
        r = await mem.care_record(person or "mum", p["drug"], dose_text=p["dose_text"], freq_text=p["freq_text"],
                                  source_type=p["source_type"], quote=p["quote"], source_text=p["source_text"])
        if r["status"] == "pending":
            await mem.care_confirm(r["id"])                          # the person just confirmed by tapping
        self.api.send(chat, f"Saved {p['drug']} for {person or 'mum'}. Other carers will be asked to acknowledge it.")

    async def _cmd_ack(self, chat, mem, person):
        div = await mem.care_divergence(person or "mum")
        me = (await self._link(chat))["agent"].lower()
        todo = div["carers"].get(me, {}).get("unacknowledged", [])
        for u in todo:
            await mem.care_ack(u["dose"])
        self.api.send(chat, f"Acknowledged {len(todo)} change(s)." if todo else "Nothing waiting for you.")

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
        """Send each due reminder once (care_nudges claims them) to the linked chat of the person to notify."""
        g = await self.gm._ctl()
        links = (await g.query("MATCH (c:TgChat) RETURN c.chat, c.agent, c.circle")).result_set
        by_circle: dict[str, list] = {}
        for chat, agent, circle in links:
            by_circle.setdefault(circle, []).append((chat, agent))
        sent = 0
        for circle, members in by_circle.items():
            mem = self.gm.open(members[0][1], circle)
            for person in (await mem.care_people())["patients"]:
                for n in await mem.care_nudges(person, now=now):
                    for chat, agent in members:
                        if agent.lower() == n["notify"]:
                            self.api.send(chat, n["message"]["text"])
                            sent += 1
        return sent


async def poll(gm, token: str) -> None:                       # pragma: no cover - needs a real bot token
    from graphmem.care import checker
    api = TgApi(token)
    bot, offset = Bot(gm, api, checker()), 0
    while True:
        for u in await asyncio.to_thread(api.call, "getUpdates", offset=offset, timeout=30):
            offset = u["update_id"] + 1
            try:
                await bot.handle(u)
            except Exception as e:
                print("handler error", type(e).__name__, e)
        await bot.deliver_nudges()
