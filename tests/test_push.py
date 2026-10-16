"""Browser notifications: keys decide whether the feature exists, subscriptions belong to an account, dead ones are dropped, delivery shares the one claim."""
import os

import pytest

from carecircle import webpush


@pytest.fixture
def keys(monkeypatch):
    k = webpush.new_keys()
    monkeypatch.setenv("CC_VAPID_PUBLIC", k["CC_VAPID_PUBLIC"])
    monkeypatch.setenv("CC_VAPID_PRIVATE", k["CC_VAPID_PRIVATE"])
    return k


def test_off_without_keys(monkeypatch):
    monkeypatch.delenv("CC_VAPID_PUBLIC", raising=False)
    assert not webpush.enabled()
    k = webpush.new_keys()
    assert len(k["CC_VAPID_PUBLIC"]) == 87 and "\n" not in k["CC_VAPID_PRIVATE"]
    monkeypatch.setenv("CC_VAPID_PRIVATE", k["CC_VAPID_PRIVATE"])
    assert "BEGIN PRIVATE KEY" in webpush._private_pem()
    import os
    os.environ["CC_VAPID_PRIVATE"] = k["CC_VAPID_PRIVATE"]
    assert "BEGIN PRIVATE KEY" in webpush._private_pem()


async def test_subscribe_validates_and_dead_endpoints_are_removed(gm, keys, monkeypatch):
    await gm.register_agent("pushy")
    for host in ("https://evil.example/x", "https://169.254.169.254/latest/meta-data", "https://fcm.googleapis.com.evil.example/x", "https://user:pw@fcm.googleapis.com/x",
                 "https://fcm.googleapis.com:8443/x", "https://localhost/x", "https://10.0.0.5/x", "https://notfcm.googleapis.com.attacker.io/x"):
        with pytest.raises(ValueError):                                          # the server later sends a request here: only browsers' push services are allowed
            await webpush.subscribe(gm, "pushy", host, "a", "b")
    for good in ("https://fcm.googleapis.com/fcm/send/abc", "https://updates.push.services.mozilla.com/wpush/v2/abc", "https://web.push.apple.com/abc", "https://par02p.notify.windows.com/w/?token=abc"):
        await webpush.subscribe(gm, "pushy", good, "k", "a")
    await webpush.unsubscribe(gm, "pushy")
    for bad in (("http://x/y", "a", "b"), ("https://fcm.googleapis.com/fcm/send/x", "", "b"), ("https://fcm.googleapis.com/fcm/send/x", "a", "")):
        with pytest.raises(ValueError):
            await webpush.subscribe(gm, "pushy", *bad)
    await webpush.subscribe(gm, "pushy", "https://fcm.googleapis.com/fcm/send/ok", "k1", "a1")
    await webpush.subscribe(gm, "pushy", "https://fcm.googleapis.com/fcm/send/gone", "k2", "a2")
    await webpush.subscribe(gm, "pushy", "https://fcm.googleapis.com/fcm/send/ok", "k1b", "a1b")                    # same endpoint: updated, not duplicated
    assert len(await webpush.subscriptions(gm, "pushy")) == 2
    sent = []
    monkeypatch.setattr(webpush, "_send_one", lambda sub, payload: sent.append(payload) or (False if sub["endpoint"].endswith("gone") else True))
    assert await webpush.push(gm, "pushy", "The change to warfarin made 5 hours ago is not yet acknowledged.") == 1
    assert sent[0]["body"].startswith("The change to warfarin") and [s["endpoint"] for s in await webpush.subscriptions(gm, "pushy")] == ["https://fcm.googleapis.com/fcm/send/ok"]
    assert await webpush.unsubscribe(gm, "pushy") == 1 and await webpush.subscriptions(gm, "pushy") == []
    for a in ("pushy",):
        g = await gm._ctl()
        await g.query("MATCH (a:Agent {id:$a}) DETACH DELETE a", {"a": a})


async def test_push_is_a_noop_when_disabled(gm, monkeypatch):
    monkeypatch.delenv("CC_VAPID_PUBLIC", raising=False)
    assert await webpush.push(gm, "nobody", "x") == 0


def _browser_subscription():
    """What a browser would hand us: a real P-256 public key and an auth secret, so the message is genuinely encrypted."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    return {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "p256dh": b64(pub), "auth": b64(os.urandom(16))}


class _Reply:
    def __init__(self, code):
        self.status_code, self.text, self.headers, self.ok, self.reason = code, "", {}, code < 400, "x"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("requests").HTTPError(response=self)


def test_a_message_is_really_signed_and_encrypted_with_the_server_key(keys, monkeypatch):
    """Everything but the network: the key we store must be usable by the library that signs. (It once was not: a PEM string was read as base64.)"""
    import requests
    seen = {}

    def fake_post(url, data=None, headers=None, **kw):
        seen.update(url=url, headers=headers, body=data)
        return _Reply(201)

    monkeypatch.setattr(requests, "post", fake_post)
    assert webpush._send_one(_browser_subscription(), {"title": "Care Circle", "body": "hello"}) is True
    assert seen["url"].startswith("https://fcm.googleapis.com/")
    auth = seen["headers"]["Authorization"]
    assert auth.startswith("vapid t=") and f"k={keys['CC_VAPID_PUBLIC']}" in auth            # signed, and the key matches what browsers were told
    assert b"hello" not in seen["body"]                                                     # the text is encrypted on the wire


@pytest.mark.parametrize("code,expected", [(404, False), (410, False), (500, None), (403, None)])
def test_what_the_push_service_answers_decides_what_happens(keys, monkeypatch, code, expected):
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Reply(code))
    assert webpush._send_one(_browser_subscription(), {"title": "t", "body": "b"}) is expected
