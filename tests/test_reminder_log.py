"""A reminder that really went out is kept, linked to the entry it was about, so the helper can say who was told what and when, and the entry can show it."""
from datetime import date

from conftest import tid
from carecircle import assistant, schedule as s
from carecircle.reminders import Reminders

IST = "Asia/Kolkata"
H = 3_600_000


async def circle(gm):
    t = tid(gm, "rl")
    await gm.grant("ravi", t, ("read", "write", "admin"))
    await gm.grant("meena", t, ("read", "write", "admin"))
    ravi, meena = gm.open("ravi", t), gm.open("meena", t)
    await ravi.care_set_timezone(IST)
    ctl = await gm._ctl()
    await ctl.query("MERGE (a:Agent {id:'meena'}) CREATE (:TgChat {chat:9101, agent:'meena', circle:$c})", {"c": t})
    return t, ravi, meena


async def test_a_delivered_reminder_is_logged_against_the_entry_and_the_helper_can_say_so(gm):
    t, ravi, meena = await circle(gm)
    day = date(2026, 9, 20)
    await meena.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily", at=s.slot_moment_ms(day, "00:00", IST))
    e = (await ravi.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime", at=s.slot_moment_ms(day, "01:00", IST)))["id"]
    got = []

    async def send(chat, text):
        got.append((chat, text))
    r = Reminders(gm, send)
    sent = await r.deliver(s.slot_moment_ms(day, "09:00", IST), use_wake=False)
    assert sent >= 1 and got and got[0][0] == 9101
    log = await ravi.care_reminders_sent("asha")
    mine = [x for x in log if x["dose"] == e]
    assert mine and mine[0]["to"] == "meena" and mine[0]["channels"] == ["telegram"] and mine[0]["drug"] == "warfarin" and "warfarin" in mine[0]["text"].lower()
    assert [x["kind"] for x in (await ravi.care_entry_notes(e))["reminders"]] == ["remind"]                   # the entry shows who was reminded
    now = s.slot_moment_ms(day, "09:05", IST)
    said = (await ravi.care_chat_ask("asha", "Has Meena been reminded about warfarin?", now=now))["text"]
    assert "Meena was told about Warfarin" in said and "telegram" in said, said
    none = (await ravi.care_chat_ask("asha", "Has Ravi been reminded?", now=now))["text"]
    assert "No reminder to Ravi has gone out" in none, none


async def test_a_reminder_that_could_not_be_delivered_is_not_logged_as_sent(gm):
    t, ravi, meena = await circle(gm)
    day = date(2026, 9, 20)
    await meena.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily", at=s.slot_moment_ms(day, "00:00", IST))
    await ravi.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime", at=s.slot_moment_ms(day, "01:00", IST))

    async def down(chat, text):
        raise RuntimeError("telegram down")
    await Reminders(gm, down).deliver(s.slot_moment_ms(day, "09:00", IST), use_wake=False)
    assert await ravi.care_reminders_sent("asha") == []


async def test_erasing_the_entry_or_the_person_removes_the_reminder_log_about_it(gm):
    t, ravi, meena = await circle(gm)
    day = date(2026, 9, 20)
    await meena.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily", at=s.slot_moment_ms(day, "00:00", IST))
    e = (await ravi.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime", at=s.slot_moment_ms(day, "01:00", IST)))["id"]

    async def send(chat, text):
        pass
    await Reminders(gm, send).deliver(s.slot_moment_ms(day, "09:00", IST), use_wake=False)
    assert any(x["dose"] == e for x in await ravi.care_reminders_sent("asha"))
    await ravi.care_forget(e, reason="entered twice")
    assert not any(x["dose"] == e for x in await ravi.care_reminders_sent("asha"))
    await ravi.care_forget_person("asha", confirm="asha")
    assert await ravi.care_reminders_sent("asha") == []
