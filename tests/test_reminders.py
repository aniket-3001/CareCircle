"""The reminder loop: a failed send is tried again, a quiet circle is left alone until something could be due, only one runner at a time, and no bot is needed."""
from datetime import date, timedelta

import pytest

from conftest import tid
from carecircle import reminders, schedule as s
from carecircle.reminders import Reminders, MAX_TRIES

IST = "Asia/Kolkata"
H = 3_600_000


def at(day, hhmm):
    return s.slot_moment_ms(day, hhmm, IST)


async def circle(gm, link=True):
    t = tid(gm, "rm")
    await gm.grant("ravi", t, ("read", "write", "admin"))
    m = gm.open("ravi", t)
    await m.care_set_timezone(IST)
    r = await m.care_record("asha", "metformin", dose_text="500 mg", freq_text="once daily", at=at(date(2026, 10, 10), "00:00"))
    await m.care_schedule_set(r["id"], ["08:00"])
    ctl = await gm._ctl()
    if link:
        await ctl.query("MERGE (a:Agent {id:'ravi'}) CREATE (:TgChat {chat:7001, agent:'ravi', circle:$c})", {"c": t})
    return t, m


async def test_a_failed_send_is_handed_back_and_tried_again_then_delivered_once(gm):
    t, m = await circle(gm)
    day, got, fail = date(2026, 10, 17), [], [True]

    async def send(chat, text):
        if fail[0]:
            raise RuntimeError("telegram down")
        got.append((chat, text))
    r = Reminders(gm, send)
    now = at(day, "08:10")
    assert await r.deliver(now, use_wake=False) == 0 and got == []                    # claimed, send failed, handed back
    fail[0] = False
    assert await r.deliver(now + 60_000, use_wake=False) == 1 and "08:00: due now" in got[0][1]
    assert await r.deliver(now + 120_000, use_wake=False) == 0                        # delivered once, not again


async def test_a_destination_that_keeps_failing_is_given_up_on_after_a_few_tries(gm):
    t, m = await circle(gm)
    calls = []

    async def send(chat, text):
        calls.append(1)
        raise RuntimeError("blocked")
    r = Reminders(gm, send)
    now = at(date(2026, 10, 17), "08:10")
    for i in range(MAX_TRIES + 4):
        await r.deliver(now + i * 1000, use_wake=False)
    assert len(calls) == MAX_TRIES + 1                                                # the first claim plus MAX_TRIES hand-backs, then it stays used


async def test_a_quiet_circle_is_left_alone_until_a_slot_could_be_due_or_something_is_written(gm):
    t, m = await circle(gm)
    asked = []
    real = type(m).care_slot_nudges

    async def spy(self, *a, **k):
        asked.append(1)
        return await real(self, *a, **k)
    type(m).care_slot_nudges = spy
    try:
        async def send(chat, text):
            pass
        r = Reminders(gm, send)
        day = date(2026, 10, 17)
        await r.deliver(at(day, "03:00"))                                              # nothing due: the circle is asked once
        await r.deliver(at(day, "03:05"))
        await r.deliver(at(day, "03:10"))
        assert len(asked) == 1                                                         # and then left alone
        r.touch(t)
        await r.deliver(at(day, "03:15"))
        assert len(asked) == 2                                                         # a write wakes it
        await r.deliver(at(day, "07:05"))                                              # the slot opens at 07:00: it is looked at again
        assert len(asked) == 3
    finally:
        type(m).care_slot_nudges = real


async def test_only_one_process_holds_the_lease_and_it_passes_on_when_the_holder_stops(gm):
    await (await gm._ctl()).query("MATCH (l:Lease {key:'reminders'}) DELETE l")          # the lease is shared by the whole database: start clean
    a, b = Reminders(gm), Reminders(gm)
    assert await a.lease(1000) is True
    assert await b.lease(1010) is False                                               # a still holds it
    assert await a.lease(1020) is True                                                # a renews
    assert await b.lease(1020 + 61) is True                                           # a stopped renewing: b takes over


async def test_the_loop_needs_no_telegram_token_when_web_push_is_on(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("CC_VAPID_PUBLIC", "x")
    monkeypatch.setenv("CC_VAPID_PRIVATE", "y")
    assert reminders.wanted() is True
    monkeypatch.delenv("CC_VAPID_PUBLIC")
    assert reminders.wanted() is False


class FakePush:
    """Stands in for carecircle.webpush inside the delivery loop: each call answers from a script of per-device outcomes."""
    def __init__(self, script):
        self.script, self.calls = list(script), 0

    def enabled(self):
        return True

    async def push_status(self, gm, agent, text, tab="circle"):
        self.calls += 1
        return self.script.pop(0) if self.script else {"sent": 0, "failed": 0, "gone": 0}


async def test_a_web_push_the_service_refused_is_handed_back_and_delivered_on_the_next_pass(gm):
    """N4: a 503 or a timeout made push return 0 without raising, the loop read that as 'no device', and the reminder stayed used up."""
    t, m = await circle(gm, link=False)
    day = date(2026, 10, 17)
    now = at(day, "08:10")
    r = Reminders(gm, None)
    fake = FakePush([{"sent": 0, "failed": 1, "gone": 0}, {"sent": 1, "failed": 0, "gone": 0}])
    n = (await m.care_slot_nudges("asha", now=now))
    assert n and n[0]["notify"] == "ravi"
    assert await r._send(m, n[0], {"ravi"}, {}, fake) == 0                          # the push service answered 503: nothing delivered
    again = await m.care_slot_nudges("asha", now=now + 60_000)
    assert [x["claim"] for x in again] == [n[0]["claim"]]                           # handed back: produced again
    assert await r._send(m, again[0], {"ravi"}, {}, fake) == 1
    assert await m.care_slot_nudges("asha", now=now + 120_000) == []                # delivered once, not again


async def test_a_device_that_is_gone_or_no_device_is_nowhere_to_go_and_not_retried(gm):
    t, m = await circle(gm, link=False)
    now = at(date(2026, 10, 17), "08:10")
    r = Reminders(gm, None)
    n = (await m.care_slot_nudges("asha", now=now))
    assert await r._send(m, n[0], {"ravi"}, {}, FakePush([{"sent": 0, "failed": 0, "gone": 1}])) == 0
    assert await m.care_slot_nudges("asha", now=now + 60_000) == []                 # the push service said unsubscribed: not retried for ever


async def test_push_status_counts_a_service_failure_apart_from_a_gone_device(monkeypatch):
    from carecircle import webpush
    monkeypatch.setattr(webpush, "enabled", lambda: True)

    async def subs(gm, agent):
        return [{"endpoint": f"https://fcm.googleapis.com/{i}", "p256dh": "k", "auth": "a"} for i in range(3)]

    async def gone(gm, agent, endpoint="") -> int:
        return 1
    outcomes = iter([None, False, True])
    monkeypatch.setattr(webpush, "subscriptions", subs)
    monkeypatch.setattr(webpush, "unsubscribe", gone)
    monkeypatch.setattr(webpush, "_send_one", lambda sub, payload: next(outcomes))
    assert await webpush.push_status(None, "ravi", "x") == {"sent": 1, "failed": 1, "gone": 1}


async def test_the_preview_does_not_call_a_handed_back_or_given_up_reminder_delivered(gm):
    """H21 claimed this and the preview said 'delivered' for a reminder whose send had failed."""
    t = tid(gm, "rv")
    for a in ("ravi", "meena"):
        await gm.grant(a, t, ("read", "write", "admin"))
    ra, rb = gm.open("ravi", t), gm.open("meena", t)
    await rb.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily", at=1_000)
    await ra.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily", at=2_000)
    now = 2_000 + 6 * H
    sent = await ra.care_nudges("asha", now=now)
    assert sent and {x["notify"]: x["delivered"] for x in await ra.care_reminders("asha", now=now)}[sent[0]["notify"]] is True      # claimed and not handed back: sent
    await ra.care_nudge_release(sent[0]["claim"], MAX_TRIES)
    assert {x["notify"]: x["delivered"] for x in await ra.care_reminders("asha", now=now)}[sent[0]["notify"]] is False      # handed back: not delivered
    for _ in range(MAX_TRIES + 1):
        await ra.care_nudge_release(sent[0]["claim"], MAX_TRIES)
    assert {x["notify"]: x["delivered"] for x in await ra.care_reminders("asha", now=now)}[sent[0]["notify"]] is False      # given up: still not delivered
