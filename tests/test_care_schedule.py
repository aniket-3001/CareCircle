"""The schedule on a real circle graph: confirm times, read the day's checklist, mark slots given once, remind, end a course."""
import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from carecircle import schedule as s
from conftest import tid
from graphmem import ops
from graphmem.policy import PermissionDenied

H = 3_600_000
IST = "Asia/Kolkata"


def at(day: date, hhmm: str, tz=IST):
    return s.slot_moment_ms(day, hhmm, tz)


async def circle(gm, tz=IST):
    t = tid(gm, "sch")
    for a, sc in (("sc-a", ("read", "write", "admin")), ("sc-b", ("read", "write")), ("sc-ro", ("read",))):
        await gm.grant(a, t, sc)
    a, b = gm.open("sc-a", t), gm.open("sc-b", t)
    await a.care_set_timezone(tz)
    return t, a, b, gm.open("sc-ro", t)


async def entry(m, drug="metformin", dose="500 mg", freq="twice daily", at_ms=1_000):
    return (await m.care_record("asha", drug, dose_text=dose, freq_text=freq, source_type="typed", at=at_ms))["id"]


async def test_times_are_confirmed_by_a_person_and_the_checklist_lists_them_in_clock_order(gm):
    t, a, b, ro = await circle(gm)
    day = date(2026, 10, 17)
    met, ator = await entry(a), await entry(a, "atorvastatin", "20 mg", "at bedtime")
    now = at(day, "06:00")
    today = await a.care_today("asha", now)
    assert today["items"] == [] and {u["drug"] for u in today["unscheduled"]} == {"metformin", "atorvastatin"}       # nothing is scheduled until a person confirms it
    sug = {u["drug"]: u["suggestion"]["times"] for u in today["unscheduled"]}
    assert sug == {"metformin": ["08:00", "20:00"], "atorvastatin": ["21:00"]}
    await a.care_schedule_set(met, ["08:00", "20:00"])
    await b.care_schedule_set(ator, ["22:00"])                                  # the times on the pack, not the suggestion
    today = await a.care_today("asha", now)
    assert [(i["time"], i["drug"], i["state"]) for i in today["items"]] == [
        ("08:00", "metformin", "upcoming"), ("20:00", "metformin", "upcoming"), ("22:00", "atorvastatin", "upcoming")]
    assert today["date"] == "2026-10-17" and today["tz"] == IST and today["unscheduled"] == []


async def test_a_slot_is_given_once_and_the_second_carer_is_told_who_did_it_even_at_a_different_minute(gm):
    t, a, b, ro = await circle(gm)
    day = date(2026, 10, 17)
    met = await entry(a)
    await a.care_schedule_set(met, ["08:00", "20:00"])
    first = await a.care_give_slot("asha", met, "20:00", now=at(day, "20:05"))
    assert first["given"] is True
    second = await b.care_give_slot("asha", met, "20:00", now=at(day, "20:20"))             # a quarter of an hour later: the typed-time guard missed this
    assert second["given"] is False and second["already_given_by"] == "sc-a"
    today = await b.care_today("asha", at(day, "20:30"))
    by = {i["time"]: i for i in today["items"]}
    assert by["20:00"]["state"] == "given" and by["20:00"]["given_by"] == "sc-a" and by["08:00"]["state"] == "not_marked"
    with pytest.raises(ValueError):
        await a.care_give_slot("asha", met, "21:00", now=at(day, "20:30"))                  # not one of its times
    with pytest.raises(KeyError):
        await a.care_give_slot("asha", "dose_nope", "08:00", now=at(day, "20:30"))


async def test_many_carers_giving_one_slot_at_once_produce_one_winner(gm):
    t, a, b, ro = await circle(gm)
    day = date(2026, 10, 17)
    met = await entry(a)
    await a.care_schedule_set(met, ["08:00"])
    for i in range(6):
        await gm.grant(f"sc-x{i}", t, ("read", "write"))
    res = await asyncio.gather(*[gm.open(f"sc-x{i}", t).care_give_slot("asha", met, "08:00", now=at(day, "08:01")) for i in range(6)])
    assert sum(r["given"] for r in res) == 1


async def test_the_day_belongs_to_the_circles_time_zone(gm):
    """16 Oct 20:30 UTC is 02:00 on the 17th in India, so India's slots of the 17th are the ones that count there; in New York it is still the 16th."""
    t, a, b, ro = await circle(gm)
    met = await entry(a, freq="once daily")
    await a.care_schedule_set(met, ["08:00"])
    now = int(datetime(2026, 10, 16, 20, 30, tzinfo=timezone.utc).timestamp() * 1000)
    assert (await a.care_today("asha", now))["date"] == "2026-10-17"
    await a.care_set_timezone("America/New_York")
    assert (await a.care_today("asha", now))["date"] == "2026-10-16"
    with pytest.raises(ValueError):
        await a.care_set_timezone("Not/AZone")
    assert (await a.care_timezone()) == {"tz": "America/New_York", "set": True}


async def test_unscheduled_as_needed_and_unreadable_are_reported_and_never_produce_slots(gm):
    t, a, b, ro = await circle(gm)
    await entry(a, "ibuprofen", "400 mg", "when needed")
    pn = await entry(a, "paracetamol-x", "500 mg", "as needed")
    await a.care_schedule_set(pn, [], as_needed=True)
    weekly = await entry(a, "alendronate", "70 mg", "once a week")
    today = await a.care_today("asha", at(date(2026, 10, 17), "09:00"))
    assert today["items"] == [] and [x["drug"] for x in today["as_needed"]] == ["paracetamol-x"]
    un = {u["drug"]: u["suggestion"] for u in today["unscheduled"]}
    assert un["alendronate"]["times"] == [] and not un["alendronate"]["understood"] and un["ibuprofen"]["as_needed"]
    with pytest.raises(ValueError):
        await a.care_schedule_set(weekly, ["08:00"], as_needed=True)                      # both: refused
    with pytest.raises(ValueError):
        await a.care_schedule_set(weekly, ["8am"])


async def test_a_confirmed_schedule_survives_a_dose_change_with_the_same_frequency_but_not_a_different_one(gm):
    t, a, b, ro = await circle(gm)
    e1 = await entry(a, at_ms=1_000)
    await a.care_schedule_set(e1, ["07:30", "19:30"])
    e2 = await entry(a, dose="850 mg", at_ms=2_000)                                   # a new strength, same written frequency
    reg = {r["id"]: r for r in await a.care_regimen("asha")}
    assert reg[e2]["slots"] == ["07:30", "19:30"] and e1 not in reg
    e3 = await entry(a, dose="850 mg", freq="three times daily", at_ms=3_000)         # a different frequency: the times are not carried
    assert (await a.care_regimen("asha"))[0]["slots"] == [] and e3


async def test_a_short_course_leaves_the_regimen_and_the_checks_after_its_last_day_but_stays_in_the_history(gm):
    t, a, b, ro = await circle(gm)
    now_real = int(time.time() * 1000)
    abx = await entry(a, "clarithromycin", "500 mg", "twice daily for 7 days", at_ms=now_real - H)
    today_real = s.local_date(now_real, IST)
    await a.care_schedule_set(abx, ["08:00", "20:00"], ends_on=(today_real + timedelta(days=2)).isoformat())
    assert [r["drug"] for r in await a.care_regimen("asha", now_real)] == ["clarithromycin"]
    assert [r["drug"] for r in await a.care_regimen("asha", now_real + 3 * 24 * H)] == []           # three days on: the course is over
    assert (await a.care_check("asha", now_real + 3 * 24 * H))["regimen"] == []
    tl = " ".join(e["text"] for e in await a.care_timeline("asha"))
    assert "Clarithromycin" in tl                                                    # the history keeps it
    with pytest.raises(ValueError):
        await a.care_schedule_set(abx, ["08:00"], ends_on="2020-01-01")
    with pytest.raises(ValueError):
        await a.care_schedule_set(abx, ["08:00"], ends_on="soon")


async def test_reminders_for_slots_come_once_per_carer_never_for_a_given_slot_and_respect_quiet_hours(gm):
    t, a, b, ro = await circle(gm)
    day = date(2026, 10, 17)
    met = await entry(a)
    await a.care_schedule_set(met, ["08:00"])
    await a.care_ack(met)                                                           # makes the carers known to the graph
    await b.care_ack(met)
    assert await a.care_slot_nudges("asha", at(day, "06:00")) == []                  # not due yet
    due = await a.care_slot_nudges("asha", at(day, "08:10"))
    assert sorted(n["notify"] for n in due) == ["sc-a", "sc-b"] and all("due now" in n["message"]["text"] for n in due)
    assert await b.care_slot_nudges("asha", at(day, "08:20")) == []                  # produced once
    late = await a.care_slot_nudges("asha", at(day, "09:45"))
    assert len(late) == 2 and all("not marked as given yet" in n["message"]["text"] for n in late)
    await a.care_give_slot("asha", met, "08:00", now=at(day, "09:50"))
    assert await a.care_slot_nudges("asha", at(day, "10:30")) == []                  # given: nothing more
    met2 = await entry(a, "warfarin", "5 mg", "once daily", at_ms=2_000)
    await a.care_schedule_set(met2, ["08:00"])
    held = await a.care_slot_nudges("asha", at(day, "08:10"), hold={"sc-a"})
    assert [n["notify"] for n in held if n["drug"] == "warfarin"] == ["sc-b"]        # a carer in quiet hours is left unclaimed, to be told when they end
    assert [n["notify"] for n in await a.care_slot_nudges("asha", at(day, "08:12")) if n["drug"] == "warfarin"] == ["sc-a"]
    with pytest.raises(PermissionDenied):
        await ro.care_slot_nudges("asha", at(day, "08:10"))


async def test_a_read_only_key_cannot_set_a_schedule_or_give_a_slot_but_can_read_the_day(gm):
    t, a, b, ro = await circle(gm)
    met = await entry(a)
    await a.care_schedule_set(met, ["08:00"])
    for op, args in (("care_schedule_set", {"dose_id": met, "times": ["09:00"]}), ("care_give_slot", {"person": "asha", "dose_id": met, "time": "08:00"}),
                     ("care_set_timezone", {"tz": "UTC"}), ("care_slot_nudges", {"person": "asha"})):
        with pytest.raises(PermissionDenied):
            await ops.invoke(gm, "sc-ro", t, op, args)
    assert (await ops.invoke(gm, "sc-ro", t, "care_today", {"person": "asha"}))["items"]
    assert (await ops.invoke(gm, "sc-ro", t, "care_schedule_suggest", {"freq_text": "BD"}))["times"] == ["08:00", "20:00"]


async def test_the_bot_delivers_a_due_slot_to_each_linked_carer_once(gm):
    from carecircle.checks import Checker
    from carecircle.telegram import Bot

    class Api:
        def __init__(self):
            self.out = []

        def send(self, chat, text, buttons=None):
            self.out.append((chat, text))

    t, a, b, ro = await circle(gm)
    day = date(2026, 10, 17)
    met = await entry(a)
    await a.care_schedule_set(met, ["08:00"])
    await a.care_ack(met)
    await b.care_ack(met)
    ka, kb = await gm.issue_key("sc-a"), await gm.issue_key("sc-b")
    api = Api()
    bot = Bot(gm, api, Checker())
    await bot.handle({"message": {"chat": {"id": 91}, "text": f"/link {ka} {t}"}})
    await bot.handle({"message": {"chat": {"id": 92}, "text": f"/link {kb} {t}"}})
    api.out.clear()
    n = await bot.deliver_nudges(now=at(day, "08:10"))
    assert n == 2 and sorted(c for c, _ in api.out) == [91, 92] and all("08:00: due now" in x for _, x in api.out)
    assert "advice" not in " ".join(x for _, x in api.out).lower()
    assert await bot.deliver_nudges(now=at(day, "08:15")) == 0                         # once


async def test_the_one_click_demo_circle_opens_with_a_checklist_not_an_empty_one(gm):
    from carecircle import demo
    d = await demo.start(gm)
    gm._created.append(d["circle"])
    m = gm.open(d["agents"]["ravi"], d["circle"])
    today = await m.care_today(d["person"])                                  # now: the demo entries are recorded as of the moment it starts
    assert today["unscheduled"] == [] and len(today["items"]) == 5
    assert {"08:00", "20:00"} <= {i["time"] for i in today["items"] if i["drug"] == "metformin"}
    assert [i["time"] for i in today["items"]] == sorted(i["time"] for i in today["items"])


async def test_doses_left_run_down_as_doses_are_marked_given_and_a_nearly_empty_pack_is_said_once(gm):
    t, a, b, ro = await circle(gm)
    day = date(2026, 10, 17)
    met = await entry(a, at_ms=at(day, "00:00") - 5 * 24 * H)
    await a.care_schedule_set(met, ["08:00", "20:00"])
    await a.care_stock_set(met, 7)                                                   # counted: 7 doses in the pack
    s0 = (await a.care_stock("asha", at(day, "07:00")))[0]
    assert (s0["doses_left"], s0["per_day"], s0["days_left"]) == (7, 2, 3)           # 7 doses at 2 a day: about 3 days
    await a.care_give_slot("asha", met, "08:00", now=at(day, "08:05"))
    s1 = (await a.care_stock("asha", at(day, "09:00")))[0]
    assert (s1["doses_left"], s1["days_left"]) == (6, 3)                              # one marked given: 6 left
    with pytest.raises(PermissionDenied):
        await ro.care_stock_set(met, 3)
    for bad in (-1, 10_000, True, "5"):
        with pytest.raises(ValueError):
            await a.care_stock_set(met, bad)
    first = [n for n in await a.care_slot_nudges("asha", now=at(day, "09:00")) if n["kind"] == "stock"]
    assert len(first) == len({n["notify"] for n in first}) >= 1                 # one per carer, none repeated
    assert "about 3 days of doses left" in first[0]["message"]["text"]
    again = [n for n in await a.care_slot_nudges("asha", now=at(day, "09:30")) if n["kind"] == "stock"]
    assert again == []                                                               # said once per carer for this count
    await a.care_stock_set(met, 40)                                                  # a new pack was counted
    assert [n for n in await a.care_slot_nudges("asha", now=at(day, "10:00")) if n["kind"] == "stock"] == []


async def test_the_week_in_counts_matches_what_was_marked_and_what_was_due(gm):
    t, a, b, ro = await circle(gm)
    day = date(2026, 10, 17)
    met = await entry(a, at_ms=at(day - timedelta(days=10), "00:00"))
    await a.care_schedule_set(met, ["08:00", "20:00"])
    for d, hhmm in ((day - timedelta(days=1), "08:00"), (day - timedelta(days=1), "20:00"), (day - timedelta(days=2), "08:00")):
        await a.care_give("asha", "metformin", f"{d.isoformat()} {hhmm}")
    now = at(day, "12:00")                                                    # today's 08:00 is due and unmarked; 20:00 has not come
    out = await a.care_outcomes("asha", 3, now)
    # three days (15th, 16th, 17th). Due: two on the 15th, two on the 16th, and today's 08:00 = 5. Marked: the 15th 08:00 and both on the 16th = 3.
    assert out["from"] == (day - timedelta(days=2)).isoformat() and out["doses_due"] == 5 and out["doses_marked_given"] == 3 and out["doses_not_marked"] == 2
    assert "nothing about health" in out["note"] or "says nothing about health" in out["note"]
    for bad in (0, 91, True):
        with pytest.raises(ValueError):
            await a.care_outcomes("asha", bad, now)
