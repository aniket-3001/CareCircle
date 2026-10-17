"""Reminders on a phone or laptop without any chat app: the browser's own push service (Web Push, RFC 8030, with VAPID keys).

The server holds a VAPID key pair (CC_VAPID_PRIVATE / CC_VAPID_PUBLIC); with no keys the feature is simply off. A signed-in person allows notifications in
the browser, which hands the page a subscription (an endpoint on the browser vendor's push service plus two keys). We keep that in the control graph,
tied to the account, as (:PushSub {hash, endpoint, p256dh, auth, agent, at}). The message sent is the same fixed-template reminder text the chat bot sends
(numbers in it come from the record). A subscription the push service reports gone (404/410) is deleted at once."""
from __future__ import annotations

import asyncio
import hashlib
from urllib.parse import urlparse
import json
import logging
import os
from typing import Optional

from graphmem.db import now_ms

log = logging.getLogger("carecircle.webpush")


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
    return {"CC_VAPID_PUBLIC": base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode(), "CC_VAPID_PRIVATE": base64.b64encode(pem.encode()).decode()}   # one line: a multi-line PEM breaks .env files


def _private_pem() -> str:
    """The private key is kept as one base64 line; a plain PEM (with real or escaped newlines) is still accepted."""
    import base64
    raw = os.getenv("CC_VAPID_PRIVATE", "")
    return raw.replace("\\n", "\n") if "BEGIN" in raw else base64.b64decode(raw).decode()


def _sig(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


# Where a browser's push subscription can legitimately point: the push services run by the browser makers. The server later sends a request to this
# address, so a person must not be able to aim it at any other server (an internal service, or one they run to learn this server's address).
PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com", "push.services.mozilla.com", "push.apple.com", "notify.windows.com")


def allowed_endpoint(endpoint: str) -> bool:
    try:
        u = urlparse(endpoint)
        host = (u.hostname or "").lower()
        return (u.scheme == "https" and not u.username and not u.password and u.port in (None, 443)
                and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS))
    except ValueError:
        return False


async def subscribe(gm, agent: str, endpoint: str, p256dh: str, auth: str) -> None:
    if not (endpoint.startswith("https://") and len(endpoint) < 1000 and p256dh and auth and len(p256dh) < 200 and len(auth) < 100):
        raise ValueError("that does not look like a browser push subscription")
    if not allowed_endpoint(endpoint):
        raise ValueError("that address is not a browser's push service")
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


def _vapid():
    """The signing key as an object. pywebpush reads a plain string as base64 DER, never as a PEM, so handing it the PEM text fails to parse."""
    from py_vapid import Vapid
    return Vapid.from_pem(_private_pem().encode())


def _send_one(sub: dict, payload: dict) -> Optional[bool]:
    """True sent, False subscription gone, None other failure (logged without any key or address)."""
    from pywebpush import WebPushException, webpush
    try:
        webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}, data=json.dumps(payload),
                vapid_private_key=_vapid(), vapid_claims={"sub": os.getenv("CC_VAPID_SUBJECT") or "mailto:carecircle@example.com"}, ttl=3600, timeout=8)
        return True
    except WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (404, 410):
            return False
        log.warning("push not delivered: the push service answered %s", code)
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("push not delivered: %s", type(e).__name__)
        return None


async def push_status(gm, agent: str, text: str, tab: str = "circle") -> dict:
    """Send one notification to every device this account allowed. {sent, failed, gone}: `failed` counts devices whose push service did not take it (a 5xx, a
    timeout, a refused connection), which is NOT the same as having no device, and `gone` those it reported unsubscribed (removed)."""
    out = {"sent": 0, "failed": 0, "gone": 0}
    if not enabled():
        return out
    for sub in await subscriptions(gm, agent):
        ok = await asyncio.to_thread(_send_one, sub, {"title": "Care Circle", "body": text, "tab": tab})
        if ok:
            out["sent"] += 1
        elif ok is False:
            out["gone"] += 1
            await unsubscribe(gm, agent, sub["endpoint"])
        else:
            out["failed"] += 1
    return out


async def push(gm, agent: str, text: str, tab: str = "circle") -> int:
    """How many devices were delivered to (see push_status for the ones that failed)."""
    return (await push_status(gm, agent, text, tab))["sent"]
