"""Browser notifications: keys decide whether the feature exists, subscriptions belong to an account, dead ones are dropped, delivery shares the one claim."""
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
    assert len(k["CC_VAPID_PUBLIC"]) == 87 and "PRIVATE KEY" in k["CC_VAPID_PRIVATE"]


async def test_subscribe_validates_and_dead_endpoints_are_removed(gm, keys, monkeypatch):
    await gm.register_agent("pushy")
    for bad in (("http://x/y", "a", "b"), ("https://push.example/x", "", "b"), ("https://push.example/x", "a", "")):
        with pytest.raises(ValueError):
            await webpush.subscribe(gm, "pushy", *bad)
    await webpush.subscribe(gm, "pushy", "https://push.example/ok", "k1", "a1")
    await webpush.subscribe(gm, "pushy", "https://push.example/gone", "k2", "a2")
    await webpush.subscribe(gm, "pushy", "https://push.example/ok", "k1b", "a1b")                    # same endpoint: updated, not duplicated
    assert len(await webpush.subscriptions(gm, "pushy")) == 2
    sent = []
    monkeypatch.setattr(webpush, "_send_one", lambda sub, payload: sent.append(payload) or (False if sub["endpoint"].endswith("gone") else True))
    assert await webpush.push(gm, "pushy", "The change to warfarin made 5 hours ago is not yet acknowledged.") == 1
    assert sent[0]["body"].startswith("The change to warfarin") and [s["endpoint"] for s in await webpush.subscriptions(gm, "pushy")] == ["https://push.example/ok"]
    assert await webpush.unsubscribe(gm, "pushy") == 1 and await webpush.subscriptions(gm, "pushy") == []
    for a in ("pushy",):
        g = await gm._ctl()
        await g.query("MATCH (a:Agent {id:$a}) DETACH DELETE a", {"a": a})


async def test_push_is_a_noop_when_disabled(gm, monkeypatch):
    monkeypatch.delenv("CC_VAPID_PUBLIC", raising=False)
    assert await webpush.push(gm, "nobody", "x") == 0
