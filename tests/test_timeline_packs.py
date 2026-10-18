"""The history shows a prescription as one line. Round 3: it had two lines for one prescription, one per ingredient of the strip."""
from conftest import tid


async def circle(gm):
    t = tid(gm, "tp")
    await gm.grant("tp-a", t, ("read", "write", "admin"))
    await gm.grant("tp-b", t, ("read", "write", "admin"))
    return gm.open("tp-a", t), gm.open("tp-b", t)


async def test_one_prescription_is_one_line_in_the_history(gm):
    a, b = await circle(gm)
    ids = []
    for ing in ("telmisartan", "amlodipine"):
        ids.append((await a.care_record("asha", ing, freq_text="once daily", product="Telma-AM", product_strength="40/5 mg"))["id"])
    await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily")
    tl = await a.care_timeline("asha", limit=50)
    rec = [e for e in tl if e["kind"] == "record"]
    assert [e["text"] for e in rec if "Telma-AM" in e["text"]] == ["Tp recorded Telma-AM (Amlodipine + Telmisartan) 40/5 mg once daily, typed in."]
    assert len(rec) == 2                                                                                      # the strip, and metformin
    strip = next(e for e in rec if "Telma-AM" in e["text"])
    assert set(strip["doses"]) == set(ids) and strip["dose"] in ids                                          # every entry is still reachable from the line


async def test_acknowledging_a_strip_and_giving_a_tablet_are_one_line_each(gm):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    a, b = await circle(gm)
    ids = [(await a.care_record("asha", i, freq_text="once daily", product="Telma-AM"))["id"] for i in ("telmisartan", "amlodipine")]
    for i in ids:
        await b.care_ack(i)
    hhmm = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M")
    await a.care_schedule_set(ids[0], [hhmm])
    await b.care_give_slot("asha", ids[0], hhmm)
    tl = await a.care_timeline("asha", limit=50)
    acks = [e["text"] for e in tl if e["kind"] == "ack"]
    gives = [e["text"] for e in tl if e["kind"] == "give"]
    assert acks == ["Tp acknowledged the entry for Telma-AM."] and len(gives) == 1 and "Amlodipine + Telmisartan" in gives[0] and "one tablet" in gives[0], (acks, gives)


async def test_two_different_prescriptions_at_different_moments_stay_separate_lines(gm):
    a, b = await circle(gm)
    await a.care_record("asha", "telmisartan", freq_text="once daily", product="Telma-AM", at=1_000)
    await a.care_record("asha", "amlodipine", freq_text="once daily", product="Telma-AM", at=1_000 + 10 * 60_000)        # ten minutes later: a different moment
    rec = [e for e in await a.care_timeline("asha", limit=50) if e["kind"] == "record"]
    assert len(rec) == 2
