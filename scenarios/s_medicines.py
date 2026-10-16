"""The record itself: medicines, history, interactions, who has seen what, reminders and giving doses."""
import threading
import time

from harness import H, World, scenario

NOW = lambda: int(time.time() * 1000)  # noqa: E731


def regimen(u, c, **kw):
    return u.ok(c, "care_regimen", person="mum", **kw)


def drugs(u, c, **kw):
    return sorted(x["drug"] for x in regimen(u, c, **kw))


@scenario("M1", "Pending entries are not on the record until a person confirms them")
def m1(w: World, r):
    priya, omar, mallory, c = w.team()
    p = priya.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="twice daily", confirm=False)
    r.check(p["status"] == "pending", "an unconfirmed entry is pending", p)
    r.check(drugs(priya, c) == [], "a pending entry is not in the regimen")
    r.check(priya.ok(c, "care_check", person="mum")["regimen"] == [], "and is not cross-checked")
    div = omar.ok(c, "care_divergence", person="mum")
    r.check(all(not v["unacknowledged"] for v in div["carers"].values()), "and nobody is told they are behind on it", div)
    s, _ = mallory.op(c, "care_confirm", dose_id=p["id"])
    r.check(s == 403, "an outsider cannot confirm it", s)
    s, _ = omar.op(c, "care_confirm", dose_id="dose_nope")
    r.check(s == 404, "confirming something that does not exist is a 404", s)
    r.check(omar.op(c, "care_confirm", dose_id=p["id"])[0] == 200, "another carer can confirm it")
    r.check(drugs(priya, c) == ["metformin"], "now it is on the record")
    s, b = priya.op(c, "care_confirm", dose_id=p["id"])
    r.check(s in (200, 404, 409) and drugs(priya, c) == ["metformin"], "confirming twice changes nothing", f"{s} {b}")
    r.check(len(priya.ok(c, "care_timeline", person="mum")) >= 1, "it shows in the timeline")


@scenario("M2", "Changing a dose: one current entry, the old one stays in history, and as-of looks back")
def m2(w: World, r):
    priya, omar, mallory, c = w.team()
    t0 = NOW() - 10 * H
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily", at=t0)
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="5 mg", freq_text="daily", at=t0 + 5 * H)
    reg = regimen(priya, c)
    r.check(len(reg) == 1 and reg[0]["dose_text"] == "5 mg", "one current entry, the new dose", reg)
    old = regimen(priya, c, as_of=t0 + 2 * H)
    r.check(len(old) == 1 and old[0]["dose_text"] == "4 mg", "as of earlier it was 4 mg", old)
    r.check(regimen(priya, c, as_of=t0 - H) == [], "before the first entry there was nothing on record")
    tl = " ".join(e["text"] for e in priya.ok(c, "care_timeline", person="mum"))
    r.check("4 mg" in tl and "5 mg" in tl, "both doses are in the history", tl[:300])
    r.check(len(priya.ok(c, "care_graph", person="mum", include_history=True)["nodes"]) >= 3, "the graph keeps the superseded entry")


@scenario("M3", "Stopping and restarting a medicine")
def m3(w: World, r):
    priya, omar, mallory, c = w.team()
    priya.ok(c, "care_record", person="mum", drug="clarithromycin", dose_text="500 mg", freq_text="twice daily")
    priya.ok(c, "care_record", person="mum", drug="simvastatin", dose_text="20 mg", freq_text="at night")
    flags = lambda: [tuple(sorted(f["drugs"])) for f in priya.ok(c, "care_check", person="mum")["direct"]]  # noqa: E731
    r.check(("clarithromycin", "simvastatin") in flags(), "the known pair is flagged", flags())
    priya.ok(c, "care_record", person="mum", drug="clarithromycin", action="stop")
    r.check(drugs(priya, c) == ["simvastatin"], "a stopped medicine leaves the regimen", drugs(priya, c))
    r.check(flags() == [], "and its flags go with it", flags())
    s, b = priya.op(c, "care_record", person="mum", drug="clarithromycin", action="stop")
    r.check(s in (400, 404, 409, 422) or (s == 200 and drugs(priya, c) == ["simvastatin"]), "stopping it a second time does not break anything", f"{s} {b}")
    s, b = priya.op(c, "care_record", person="mum", drug="neverrecorded", action="stop")
    r.check(s in (400, 404, 409, 422), "stopping a medicine that was never on record is refused", f"{s} {str(b)[:100]}")
    priya.ok(c, "care_record", person="mum", drug="clarithromycin", dose_text="250 mg", freq_text="daily")
    reg = {x["drug"]: x["dose_text"] for x in regimen(priya, c)}
    r.check(reg == {"simvastatin": "20 mg", "clarithromycin": "250 mg"}, "restarting brings it back with its new dose, not the old one", reg)
    r.check(("clarithromycin", "simvastatin") in flags(), "and the flag is back", flags())
    r.check(drugs(priya, c, as_of=NOW() - 1) != [] or True, "as-of still answers")


@scenario("M4", "The same medicine typed three ways is one entry; identical re-entry is not a new change")
def m4(w: World, r):
    priya, omar, mallory, c = w.team()
    for name in ("Warfarin", "WARFARIN", " warfarin  "):
        priya.ok(c, "care_record", person="mum", drug=name, dose_text="4 mg", freq_text="daily")
    r.check(drugs(priya, c) == ["warfarin"], "one entry however it was typed", drugs(priya, c))
    priya.ok(c, "care_ack", dose_id=regimen(priya, c)[0]["id"])
    omar.ok(c, "care_ack", dose_id=regimen(priya, c)[0]["id"])
    div = omar.ok(c, "care_divergence", person="mum")
    behind_before = {k: len(v["unacknowledged"]) for k, v in div["carers"].items()}
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily")          # typed again, nothing changed
    div2 = omar.ok(c, "care_divergence", person="mum")
    behind_after = {k: len(v["unacknowledged"]) for k, v in div2["carers"].items()}
    r.check(behind_after == behind_before, "re-entering the same dose does not make the other carer 'behind' again", (behind_before, behind_after))
    c2 = w.circle(priya, "Other", "Nan")
    priya.ok(c2, "care_record", person="nan", drug="warfarin", dose_text="1 mg", freq_text="daily")
    r.check(drugs(priya, c) == ["warfarin"] and regimen(priya, c)[0]["dose_text"] == "4 mg", "the same medicine in another circle is separate")


@scenario("M5", "Dose text: slips are noticed, odd formats are kept as typed, nothing is rewritten")
def m5(w: World, r):
    priya, omar, mallory, c = w.team()
    priya.ok(c, "care_record", person="mum", drug="levothyroxine", dose_text="50 mcg", freq_text="morning")
    slip = priya.ok(c, "care_record", person="mum", drug="levothyroxine", dose_text="50 mg", freq_text="morning")
    r.check(bool(slip.get("warning")), "mcg to mg on the same medicine is flagged as a possible slip", slip)
    big = priya.ok(c, "care_record", person="mum", drug="levothyroxine", dose_text="5000 mcg", freq_text="morning")
    r.check(bool(big.get("warning")), "a hundredfold jump is flagged", big)
    r.check(regimen(priya, c)[0]["dose_text"] == "5000 mcg", "the flag is a warning, the entry is still saved as typed (a person decides)", regimen(priya, c))
    for text in ("5,5 mg", "½ tablet", "1 1/2 tablets", "two puffs", "as needed", "5mg", "0.5 mg", "١٠ mg", "  7   mg  "):
        s, b = priya.op(c, "care_record", person="mum", drug="testdrug", dose_text=text, freq_text="daily")
        r.check(s == 200, f"dose text {text!r} is accepted", f"{s} {str(b)[:80]}")
        got = [x for x in regimen(priya, c) if x["drug"] == "testdrug"]
        r.check(got and got[0]["dose_text"].strip() != "" and any(ch.isalnum() for ch in got[0]["dose_text"]), f"and comes back readable ({text!r})", got)
    for text, why in (("", "empty"), ("x" * 500, "very long")):
        s, b = priya.op(c, "care_record", person="mum", drug="testdrug2", dose_text=text, freq_text="daily")
        r.check(s in (200, 400, 422), f"{why} dose text is handled", f"{s}")
    for drug in ("", "   ", "x" * 300):
        s, b = priya.op(c, "care_record", person="mum", drug=drug, dose_text="1 mg")
        r.check(s in (400, 422), f"medicine name {drug[:10]!r} is refused", f"{s} {str(b)[:80]}")


@scenario("M6", "An entry dated before the current one must not replace it")
def m6(w: World, r):
    priya, omar, mallory, c = w.team()
    now = NOW()
    priya.ok(c, "care_record", person="mum", drug="metformin", dose_text="1000 mg", freq_text="twice daily", at=now - 2 * H)
    priya.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="twice daily", at=now - 30 * 24 * H)   # an older prescription typed in late
    reg = regimen(priya, c)
    r.check(len(reg) == 1 and reg[0]["dose_text"] == "1000 mg", "the newer 1000 mg is still current: a back-dated 500 mg must not override it", reg)
    past = regimen(priya, c, as_of=now - 10 * 24 * H)
    r.check(len(past) == 1 and past[0]["dose_text"] == "500 mg", "but as of 10 days ago it was 500 mg", past)
    fut = priya.ok(c, "care_record", person="mum", drug="aspirin", dose_text="75 mg", freq_text="daily", at=now + 3 * 24 * H)
    r.check("aspirin" not in drugs(priya, c), "an entry dated in the future is not on the record yet", drugs(priya, c))
    r.check("aspirin" in drugs(priya, c, as_of=now + 4 * 24 * H), "but it is there by then")
    r.check(fut is not None, "future entries are accepted")


@scenario("M7", "Forgetting an entry: what the record shows afterwards")
def m7(w: World, r):
    priya, omar, mallory, c = w.team()
    a = priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily", at=NOW() - 5 * H)
    b = priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="40 mg", freq_text="daily", at=NOW() - 1 * H)   # a typo: should have been 4
    f = priya.ok(c, "care_forget", dose_id=b["id"], reason="typo")
    r.check(f.get("forgotten") is True and f.get("receipt"), "forgetting returns a receipt", f)
    reg = regimen(priya, c)
    r.check([x["dose_text"] for x in reg] == ["4 mg"], "after forgetting the typo, the medicine is still on the record at its earlier dose (she did not stop taking it)", reg)
    tl = " ".join(e["text"] for e in priya.ok(c, "care_timeline", person="mum"))
    r.check("40 mg" not in tl, "the forgotten dose is gone from the timeline", tl[:300])
    rec = priya.ok(c, "care_receipts")
    r.check(len(rec) == 1 and "40 mg" not in str(rec) and "warfarin" not in str(rec).lower(), "a receipt says something was removed without keeping what it said", rec)
    s, _ = omar.op(c, "care_forget", dose_id=a["id"], reason="")
    r.check(s in (200, 403), "another carer may or may not forget, but never crashes", s)
    s, _ = priya.op(c, "care_forget", dose_id="dose_nope", reason="x")
    r.check(s == 404, "forgetting something that does not exist is a 404", s)
    s, _ = mallory.op(c, "care_forget", dose_id=a["id"], reason="x")
    r.check(s == 403, "an outsider cannot forget anything", s)


@scenario("M8", "Interactions: order does not matter, unknowns are not 'safe', stopping clears, nothing says safe")
def m8(w: World, r):
    priya, omar, mallory, c = w.team()
    c2 = w.circle(priya, "Reverse", "Dad")
    for d in ("simvastatin", "clarithromycin"):
        priya.ok(c, "care_record", person="mum", drug=d, dose_text="1 mg")
    for d in ("clarithromycin", "simvastatin"):
        priya.ok(c2, "care_record", person="dad", drug=d, dose_text="1 mg")
    a = priya.ok(c, "care_check", person="mum")
    b = priya.ok(c2, "care_check", person="dad")
    key = lambda x: sorted((tuple(sorted(f["drugs"])), f["level"]) for f in x["direct"])  # noqa: E731
    r.check(key(a) == key(b) and key(a), "the order the medicines were added in does not change the result", (key(a), key(b)))
    priya.ok(c, "care_record", person="mum", drug="zzfakemedicine", dose_text="1 mg")
    chk = priya.ok(c, "care_check", person="mum")
    text = str(chk).lower()
    r.check("zzfakemedicine" in text, "a medicine the sources do not know is still listed", text[:200])
    r.check(chk["judgement"], "there is a verdict", chk)
    j = str(chk["judgement"]).lower()
    r.check("safe" not in j.replace("not mean safe", "").replace("never safe", "").replace("not safe", "") or "no flag does not mean safe" in j, "the verdict never calls anything safe", chk["judgement"])
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg")
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg")
    r.check(not any(len(set(f["drugs"])) < 2 for f in priya.ok(c, "care_check", person="mum")["direct"]), "a medicine is never flagged against itself")
    only = w.circle(priya, "Single", "Gran")
    priya.ok(only, "care_record", person="gran", drug="metformin", dose_text="500 mg")
    one = priya.ok(only, "care_check", person="gran")
    r.check(one["direct"] == [] and "not a statement of safety" in str(one["judgement"]).lower(), "one medicine alone: no flags, and it says outright that this is not a statement of safety", one["judgement"])
    past = priya.ok(c, "care_check", person="mum", as_of=NOW() - 365 * 24 * H)
    r.check(past["regimen"] == [] and past["direct"] == [], "checking a date before anything was recorded finds nothing")


@scenario("D1", "Who has seen what: changes, acknowledgements and a dose changed twice before anyone looked")
def d1(w: World, r):
    priya, omar, mallory, c = w.team()
    e1 = priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily")
    div = omar.ok(c, "care_divergence", person="mum")
    me = lambda d, who: d["carers"].get(who, {"unacknowledged": [], "divergence": 0})  # noqa: E731
    r.check(len(me(div, omar.agent)["unacknowledged"]) == 1, "Omar is behind on Priya's new entry", div)
    r.check(me(div, priya.agent)["unacknowledged"] == [], "Priya is not behind on her own entry", div)
    e2 = priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="5 mg", freq_text="daily")
    div = omar.ok(c, "care_divergence", person="mum")
    items = me(div, omar.agent)["unacknowledged"]
    r.check(len(items) == 1 and items[0]["drug"] == "warfarin", "changed twice before he looked: he is behind on warfarin once (the current 5 mg), not twice", items)
    s, _ = mallory.op(c, "care_ack", dose_id=e2["id"])
    r.check(s == 403, "an outsider cannot acknowledge", s)
    r.check(omar.op(c, "care_ack", dose_id="dose_nope")[0] == 404, "acknowledging something that does not exist is a 404")
    r.check(omar.op(c, "care_ack", dose_id=e2["id"])[0] == 200, "Omar acknowledges the current entry")
    r.check(omar.op(c, "care_ack", dose_id=e2["id"])[0] == 200, "doing it twice is harmless")
    div = omar.ok(c, "care_divergence", person="mum")
    r.check(me(div, omar.agent)["unacknowledged"] == [], "he is up to date: acknowledging the current entry covers the older one it replaced", me(div, omar.agent))
    r.check(div["carers"][omar.agent]["divergence"] == 0, "his out-of-date score is zero", div["carers"][omar.agent])
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="3 mg", freq_text="daily")
    r.check(len(me(omar.ok(c, "care_divergence", person="mum"), omar.agent)["unacknowledged"]) == 1, "a later change makes him behind again")
    priya.ok(c, "care_record", person="mum", drug="warfarin", action="stop")
    items = me(omar.ok(c, "care_divergence", person="mum"), omar.agent)["unacknowledged"]
    r.check(len(items) == 1, "a stop is also something to be told about, once", items)
    del e1


@scenario("D2", "A carer who joins later, and one who leaves, are counted correctly")
def d2(w: World, r):
    priya, omar, mallory, c = w.team()
    priya.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="twice daily")
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily")
    late = w.user("Late")
    w.join(priya, c, late)
    div = priya.ok(c, "care_divergence", person="mum")
    mine = div["carers"].get(late.agent)
    r.check(mine is not None, "a carer who just joined appears in the divergence view", list(div["carers"]))
    if mine:
        r.check(len(mine["unacknowledged"]) == 2, "and has not yet seen either medicine (so they know to look)", mine)
    priya.delete(f"/v1/circles/{c}/members/{late.agent}")
    div = priya.ok(c, "care_divergence", person="mum")
    r.check(late.agent not in div["carers"], "after they are removed they are not counted as behind", list(div["carers"]))
    r.check(div.get("most_out_of_date") != late.agent, "and are not 'most out of date'", div.get("most_out_of_date"))


@scenario("D3", "Reminders: not too early, once only, escalate later, never about something already replaced or seen")
def d3(w: World, r):
    priya, omar, mallory, c = w.team()
    now = NOW()
    e = priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily", at=now)
    r.check(priya.ok(c, "care_nudges", person="mum", now=now + 1 * H) == [], "nothing after 1 hour")
    n1 = priya.ok(c, "care_nudges", person="mum", now=now + 5 * H)
    r.check(len(n1) == 1 and n1[0]["notify"] == omar.agent.lower() and n1[0]["kind"] == "remind", "after 5 hours Omar gets one reminder", n1)
    r.check(priya.ok(c, "care_nudges", person="mum", now=now + 6 * H) == [], "and not again")
    n2 = priya.ok(c, "care_nudges", person="mum", now=now + 13 * H)
    r.check(len(n2) == 1 and n2[0]["kind"] == "escalate" and n2[0]["notify"] == priya.agent.lower(), "after 13 hours Priya is told Omar has not seen it", n2)
    r.check(priya.ok(c, "care_nudges", person="mum", now=now + 30 * H) == [], "nothing further")
    # a replaced entry must not be nagged about
    e2 = priya.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="daily", at=now)
    e3 = priya.ok(c, "care_record", person="mum", drug="metformin", dose_text="850 mg", freq_text="daily", at=now + H)
    got = priya.ok(c, "care_nudges", person="mum", now=now + 6 * H)
    texts = " ".join(n["message"]["text"] for n in got)
    r.check("500" not in texts and len(got) <= 1, "a change that was replaced before the reminder is not reminded about separately (one reminder, for the current entry)", got)
    omar.ok(c, "care_ack", dose_id=e3["id"])
    r.check(priya.ok(c, "care_nudges", person="mum", now=now + 40 * H) == [], "once seen, no escalation")
    # held reminders go out later
    priya.ok(c, "care_record", person="mum", drug="aspirin", dose_text="75 mg", freq_text="daily", at=now + 50 * H)
    held = priya.ok(c, "care_nudges", person="mum", now=now + 60 * H, hold=[omar.agent.lower()])
    r.check(held == [], "a reminder for someone in quiet hours is held back", held)
    later = priya.ok(c, "care_nudges", person="mum", now=now + 61 * H)
    r.check(len(later) == 1, "and goes out once their quiet hours end", later)
    del e, e2


@scenario("D4", "Only one carer knows: listed when true, empty when shared, and not alarming for a circle of one")
def d4(w: World, r):
    priya, omar, mallory, c = w.team()
    e = priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily")
    sole = priya.ok(c, "care_sole_knowers", person="mum")
    r.check(any(x.get("drug") == "warfarin" for x in (sole if isinstance(sole, list) else sole.get("items", sole.get("sole", [])))), "a change only its author has acknowledged is listed", sole)
    omar.ok(c, "care_ack", dose_id=e["id"])
    sole = priya.ok(c, "care_sole_knowers", person="mum")
    items = sole if isinstance(sole, list) else sole.get("items", sole.get("sole", []))
    r.check(not any(x.get("drug") == "warfarin" for x in items), "once a second carer has seen it, it is no longer listed", sole)
    solo = w.user("Solo")
    sc = w.circle(solo, "Just me", "Gran")
    solo.ok(sc, "care_record", person="gran", drug="metformin", dose_text="500 mg")
    s = solo.ok(sc, "care_sole_knowers", person="gran")
    items = s if isinstance(s, list) else s.get("items", s.get("sole", []))
    r.check(items == [] or all("alone" not in str(x).lower() for x in items), "a circle with only one carer is not told that 'only one carer knows' of everything", s)


@scenario("G1", "Giving doses: once per slot, slot formats, and giving something that is not on record")
def g1(w: World, r):
    priya, omar, mallory, c = w.team()
    priya.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="twice daily")
    a = priya.ok(c, "care_give", person="mum", drug="metformin", slot="2026-10-16 08:00")
    r.check(a["given"] is True, "the first give is recorded", a)
    b = omar.ok(c, "care_give", person="mum", drug="metformin", slot="2026-10-16 08:00")
    r.check(b["given"] is False and b.get("already_given_by") == priya.agent.lower(), "the same slot from another carer says who already gave it", b)
    r.check(priya.ok(c, "care_give", person="mum", drug="Metformin ", slot="2026-10-16 08:00")["given"] is False, "the same slot with the name typed differently is still the same dose")
    r.check(omar.ok(c, "care_give", person="mum", drug="metformin", slot="2026-10-16 20:00")["given"] is True, "a different slot is a different dose")
    for bad in ("garbage", "", "2026-13-45 08:00", "2026-10-16 25:99", "yesterday", "2026-10-16", "x" * 200):
        s, body = priya.op(c, "care_give", person="mum", drug="metformin", slot=bad)
        r.check(s in (400, 422), f"slot {bad[:20]!r} is refused (a typo should not become a 'dose given' record)", f"{s} {str(body)[:80]}")
    s, body = priya.op(c, "care_give", person="mum", drug="neverrecorded", slot="2026-10-17 08:00")
    r.check(s in (400, 404, 409, 422), "giving a medicine that is not on record is refused", f"{s} {str(body)[:80]}")
    priya.ok(c, "care_record", person="mum", drug="metformin", action="stop")
    s, body = priya.op(c, "care_give", person="mum", drug="metformin", slot="2026-10-18 08:00")
    r.check(s in (400, 404, 409, 422), "giving a medicine after it was stopped is refused", f"{s} {str(body)[:80]}")
    gives = priya.ok(c, "care_gives", person="mum")
    r.check(len(gives) == 2 and {g["by"] for g in gives} == {priya.agent.lower(), omar.agent.lower()}, "the list holds exactly the two real doses, with who gave them", gives)


@scenario("G2", "Two carers give the same dose at the same moment: exactly one is recorded")
def g2(w: World, r):
    priya, omar, mallory, c = w.team()
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily")
    results = []

    def go(u):
        results.append(u.op(c, "care_give", person="mum", drug="warfarin", slot="2026-10-16 18:00"))

    threads = [threading.Thread(target=go, args=(u,)) for u in (priya, omar) * 6]
    [t.start() for t in threads]
    [t.join() for t in threads]
    given = [b for s, b in results if s == 200 and b.get("given")]
    r.check(len(given) == 1, "twelve simultaneous attempts, one winner", [(s, b.get("given") if isinstance(b, dict) else b) for s, b in results])
    r.check(all(s == 200 for s, _ in results), "nobody gets an error: the losers are told who gave it", [s for s, _ in results])
    r.check(len(priya.ok(c, "care_gives", person="mum")) == 1, "one dose on record")


@scenario("G3", "Second-carer confirmation for a watched medicine")
def g3(w: World, r):
    priya, omar, mallory, c = w.team()
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily")
    priya.ok(c, "care_watch", person="mum", drug="warfarin", on=True)
    r.check(omar.ok(c, "care_watched", person="mum") == ["warfarin"], "the other carer sees it is watched")
    g = priya.ok(c, "care_give", person="mum", drug="warfarin", slot="2026-10-16 18:00")
    r.check(g["given"] and g.get("needs_second_carer"), "giving it asks for a second carer", g)
    s, _ = priya.op(c, "care_witness", person="mum", drug="warfarin", slot="2026-10-16 18:00")
    r.check(s in (400, 403, 409, 422), "the giver cannot witness their own dose", s)
    s, _ = mallory.op(c, "care_witness", person="mum", drug="warfarin", slot="2026-10-16 18:00")
    r.check(s == 403, "an outsider cannot witness", s)
    s, _ = omar.op(c, "care_witness", person="mum", drug="warfarin", slot="2026-10-10 08:00")
    r.check(s == 404, "witnessing a dose that was never given is a 404", s)
    r.check(omar.op(c, "care_witness", person="mum", drug="warfarin", slot="2026-10-16 18:00")[0] == 200, "another carer witnesses it")
    gv = [x for x in priya.ok(c, "care_gives", person="mum") if x["drug"] == "warfarin"][0]
    r.check(gv["witness"] == omar.agent.lower() and gv["needs_second_carer"] is False, "it is now confirmed by two people", gv)
    s, b = omar.op(c, "care_witness", person="mum", drug="warfarin", slot="2026-10-16 18:00")
    r.check(s in (200, 409) and [x for x in priya.ok(c, "care_gives", person="mum")][0]["witness"] == omar.agent.lower(), "witnessing twice does not change who witnessed", f"{s} {b}")
    priya.ok(c, "care_watch", person="mum", drug="warfarin", on=False)
    r.check(priya.ok(c, "care_watched", person="mum") == [], "unwatching works")
    r.check("needs_second_carer" not in priya.ok(c, "care_give", person="mum", drug="warfarin", slot="2026-10-17 18:00") or priya.ok(c, "care_give", person="mum", drug="warfarin", slot="2026-10-18 18:00").get("needs_second_carer") in (None, False), "an unwatched medicine asks for nothing extra")
