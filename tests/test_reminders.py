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
