"""Reminders on a phone or laptop without any chat app: the browser's own push service (Web Push, RFC 8030, with VAPID keys).

The server holds a VAPID key pair (CC_VAPID_PRIVATE / CC_VAPID_PUBLIC); with no keys the feature is simply off. A signed-in person allows notifications in
the browser, which hands the page a subscription (an endpoint on the browser vendor's push service plus two keys). We keep that in the control graph,
tied to the account, as (:PushSub {hash, endpoint, p256dh, auth, agent, at}). The message sent is the same fixed-template reminder text the chat bot sends
(numbers in it come from the record). A subscription the push service reports gone (404/410) is deleted at once."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Optional

from graphmem.db import now_ms


def public_key() -> str:
    return os.getenv("CC_VAPID_PUBLIC", "")


def enabled() -> bool:
    return bool(public_key() and os.getenv("CC_VAPID_PRIVATE")) and os.getenv("CC_PUSH", "1") != "0"


def new_keys() -> dict:
    """A fresh VAPID pair (run once; put the two values in the server's environment)."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid
    v = Vapid()
    v.generate_keys()
    raw_pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    pem = v.private_pem().decode()
    return {"CC_VAPID_PUBLIC": base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode(), "CC_VAPID_PRIVATE": pem.replace("\n", "\\n")}


def _sig(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


async def subscribe(gm, agent: str, endpoint: str, p256dh: str, auth: str) -> None:
    if not (endpoint.startswith("https://") and len(endpoint) < 1000 and p256dh and auth and len(p256dh) < 200 and len(auth) < 100):
        raise ValueError("that does not look like a browser push subscription")
    g = await gm._ctl()
    await g.query("MERGE (s:PushSub {hash:$h}) SET s.endpoint=$e, s.p256dh=$k, s.auth=$a, s.agent=$ag, s.at=$t",
                  {"h": _sig(endpoint), "e": endpoint, "k": p256dh, "a": auth, "ag": agent, "t": now_ms()})


async def unsubscribe(gm, agent: str, endpoint: str = "") -> int:
    g = await gm._ctl()
    q = "MATCH (s:PushSub {agent:$ag}) " + ("WHERE s.hash = $h " if endpoint else "") + "DELETE s RETURN count(s)"
    rows = (await g.query(q, {"ag": agent, "h": _sig(endpoint)} if endpoint else {"ag": agent})).result_set
    return rows[0][0] if rows else 0


async def subscriptions(gm, agent: str) -> list[dict]:
    g = await gm._ctl()
    rows = (await g.query("MATCH (s:PushSub {agent:$ag}) RETURN s.endpoint, s.p256dh, s.auth, s.hash", {"ag": agent})).result_set
    return [dict(endpoint=r[0], p256dh=r[1], auth=r[2], hash=r[3]) for r in rows]


def _send_one(sub: dict, payload: dict) -> Optional[bool]:
    """True sent, False subscription gone, None other failure."""
    from pywebpush import WebPushException, webpush
    try:
        webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}, data=json.dumps(payload),
                vapid_private_key=os.getenv("CC_VAPID_PRIVATE", "").replace("\\n", "\n"), vapid_claims={"sub": os.getenv("CC_VAPID_SUBJECT", "mailto:carecircle@example.com")}, ttl=3600, timeout=8)
        return True
    except WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        return False if code in (404, 410) else None
    except Exception:
        return None


async def push(gm, agent: str, text: str, tab: str = "circle") -> int:
    """Send one notification to every device this account allowed. Returns how many were delivered."""
    if not enabled():
        return 0
    sent = 0
    for sub in await subscriptions(gm, agent):
        ok = await asyncio.to_thread(_send_one, sub, {"title": "Care Circle", "body": text, "tab": tab})
        if ok:
            sent += 1
        elif ok is False:
            await unsubscribe(gm, agent, sub["endpoint"])
    return sent
