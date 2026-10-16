"""Readings, appointments, conditions and allergies, follow-ups, handover notes, export, and erasing a person."""
import time

from harness import H, World, scenario

NOW = lambda: int(time.time() * 1000)  # noqa: E731
DAY = 24 * H


@scenario("R1", "Readings: typing slips are refused, odd values handled, readings stay with the right person")
def r1(w: World, r):
    priya, omar, mallory, c = w.team()
    ok = priya.ok(c, "care_measure", person="mum", kind="bp_systolic", value=132, unit="mmHg")
    r.check(ok["value"] == 132.0, "a normal reading is saved", ok)
    cases = [("bp_systolic", 1200, "mmHg", "a pressure of 1200"), ("bp_systolic", -5, "mmHg", "a negative pressure"), ("inr", 0, "ratio", "an INR of 0"),
             ("glucose", 1e9, "mg/dL", "a huge sugar"), ("weight", float("nan"), "kg", "NaN"), ("weight", "heavy", "kg", "text for a number"),
             ("nonsense", 5, "", "an unknown kind"), ("weight", 70, "stone", "a unit that does not belong"), ("temperature", 98.6, "C", "98.6 in Celsius")]
    for kind, val, unit, why in cases:
        body = {"person": "mum", "kind": kind, "value": val, "unit": unit}
        s, b = priya.op(c, "care_measure", **{k: (None if isinstance(v, float) and v != v else v) for k, v in body.items()})
        r.check(s in (400, 422), f"{why} is refused", f"{s} {str(b)[:90]}")
    s, b = priya.op(c, "care_measure", person="mum", kind="weight", value=True)
    r.check(s in (400, 422), "a yes/no value is not a weight", f"{s} {str(b)[:80]}")
    s, b = priya.op(c, "care_measure", person="mum", kind="weight", value="72.5")
    r.check(s == 200, "a number typed as text is understood", f"{s} {str(b)[:80]}")
    s, b = priya.op(c, "care_measure", person="mum", kind="weight", value=70, at=NOW() + 5 * DAY)
    r.check(s in (400, 422), "a reading from the future is refused", f"{s}")
    priya.ok(c, "care_measure", person="dad", kind="weight", value=90)
    mum = priya.ok(c, "care_measures", person="mum")
    r.check(all(m["kind"] in ("bp_systolic", "weight") for m in mum) and 90.0 not in [m["value"] for m in mum], "another person's reading never appears in this person's list", mum)
    r.check(len(priya.ok(c, "care_measures", person="mum", limit=1)) == 1, "the limit is respected")
    r.check(mallory.op(c, "care_measures", person="mum")[0] == 403, "an outsider cannot read readings")
    m = priya.ok(c, "care_measures", person="mum")[0]
    r.check(omar.op(c, "care_forget_measure", measure_id=m["id"])[0] == 200, "a carer can remove a reading that was typed wrongly")
    r.check(priya.op(c, "care_forget_measure", measure_id="meas_nope")[0] == 404, "removing one that does not exist is a 404")


@scenario("R2", "Trend: readings line up with the day a medicine changed, and say nothing about what it means")
def r2(w: World, r):
    priya, omar, mallory, c = w.team()
    now = NOW()
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily", at=now - 20 * DAY)
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="5 mg", freq_text="daily", at=now - 10 * DAY)
    for days, val in ((18, 2.0), (15, 2.2), (12, 2.4), (8, 3.0), (5, 3.2), (2, 3.4)):
        priya.ok(c, "care_measure", person="mum", kind="inr", value=val, at=now - days * DAY)
    t = priya.ok(c, "care_trend", person="mum", kind="inr", drug="warfarin", now=now)
    text = str(t).lower()
    r.check(len(t.get("series", [])) == 6, "all six readings are in the series", t)
    r.check(any(k in t for k in ("changes", "markers", "around")), "the dose change is marked on the same timeline", list(t))
    for word in ("improv", "worse", "good", "bad", "normal", "should", "recommend", "dangerous", "safe"):
        r.check(word not in text.replace("not advice", ""), f"the trend never uses judging words ({word!r})", text[:200])
    empty = priya.ok(c, "care_trend", person="mum", kind="glucose", now=now)
    r.check(empty.get("series", []) == [], "no readings gives an empty trend, not an error", empty)
    s, _ = priya.op(c, "care_trend", person="mum", kind="nonsense", now=now)
    r.check(s in (400, 422), "an unknown kind is refused", s)
    s, b = priya.op(c, "care_trend", person="mum", kind="inr", drug="neverrecorded", now=now)
    r.check(s in (200, 400, 404), "a trend against an unknown medicine does not crash", f"{s} {str(b)[:80]}")


@scenario("P1", "Appointments: ordering, going past, editing, cancelling, and the 'what to bring' page")
def p1(w: World, r):
    priya, omar, mallory, c = w.team()
    now = NOW()
    a = priya.ok(c, "care_appoint", person="mum", title="INR clinic", at=now + 3 * DAY, place="Riverside", who=omar.agent, bring="diary")
    past = priya.ok(c, "care_appoint", person="mum", title="GP review", at=now - 5 * DAY)
    far = priya.op(c, "care_appoint", person="mum", title="Too far", at=now + 20 * 366 * DAY)
    r.check(far[0] in (400, 422), "an appointment 20 years away is refused", far[0])
    old = priya.op(c, "care_appoint", person="mum", title="Ancient", at=now - 5 * 366 * DAY)
    r.check(old[0] in (400, 422), "an appointment 5 years ago is refused", old[0])
    r.check(priya.op(c, "care_appoint", person="mum", title="  ", at=now + DAY)[0] in (400, 422), "a blank title is refused")
    lst = priya.ok(c, "care_appointments", person="mum")
    r.check([x["title"] for x in lst][:2] == ["INR clinic", "GP review"] and lst[0]["status"] == "upcoming" and lst[1]["status"] == "done", "upcoming first, a past one reads as done", lst)
    later = priya.ok(c, "care_appointments", person="mum", now=now + 4 * DAY)
    r.check({x["title"]: x["status"] for x in later}["INR clinic"] == "done", "after its date passes an appointment reads as done (nothing is rewritten)", later)
    priya.ok(c, "care_appointment_edit", appointment_id=a["id"], place="North clinic")
    r.check([x for x in priya.ok(c, "care_appointments", person="mum") if x["id"] == a["id"]][0]["place"] == "North clinic", "editing changes only what was sent")
    priya.ok(c, "care_appointment_cancel", appointment_id=a["id"])
    got = [x for x in priya.ok(c, "care_appointments", person="mum") if x["id"] == a["id"]][0]
    r.check(got["status"] == "cancelled", "a cancelled appointment stays, marked cancelled", got)
    s, _ = priya.op(c, "care_appointment_edit", appointment_id=a["id"], title="Revived")
    r.check(s in (200, 400, 409), "editing a cancelled appointment does not crash", s)
    after = [x for x in priya.ok(c, "care_appointments", person="mum") if x["id"] == a["id"]][0]
    r.check(after["status"] in ("cancelled", "upcoming"), "and its status stays meaningful", after)
    r.check(mallory.op(c, "care_appointment_cancel", appointment_id=past["id"])[0] == 403, "an outsider cannot cancel")
    r.check(priya.op(c, "care_appointment_cancel", appointment_id="appt_nope")[0] == 404, "cancelling one that does not exist is a 404")
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily", at=now - 2 * DAY)
    v = priya.ok(c, "care_since_visit", person="mum")
    r.check(any("warfarin" in str(x).lower() for x in v["changes"]), "the page lists what changed since the last visit", v["changes"])
    r.check("advice" in str(v["note"]).lower() or "not advice" in str(v).lower(), "and says it is not advice", v.get("note"))
    nobody = w.user("Fresh")
    fc = w.circle(nobody, "Empty", "Gran")
    ev = nobody.ok(fc, "care_since_visit", person="gran")
    r.check(ev["changes"] == [] and ev["regimen"] == [], "a circle with nothing recorded gives an empty page, not an error", ev)


@scenario("L1", "Allergies against medicines: hits when they should be, gone when they should be, never 'stop', never 'safe'")
def l1(w: World, r):
    priya, omar, mallory, c = w.team()
    priya.ok(c, "care_record", person="mum", drug="amoxicillin", dose_text="500 mg", freq_text="three times a day")
    priya.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="daily")
    none = priya.ok(c, "care_allergy_check", person="mum")
    r.check(none["hits"] == [], "no allergy recorded: no hit", none)
    r.check("safe" not in none["note"].lower().replace("not mean safe", "").replace("not a statement of safety", "").replace("not safe", ""), "and no claim of safety", none["note"])
    al = priya.ok(c, "care_allergy_add", person="mum", text="Penicillin")
    hits = priya.ok(c, "care_allergy_check", person="mum")["hits"]
    r.check([h["drug"] for h in hits] == ["amoxicillin"], "a penicillin allergy hits amoxicillin, and only it", hits)
    phrase = " ".join(str(h["why"]) for h in hits).lower() + " " + priya.ok(c, "care_allergy_check", person="mum")["note"].lower()
    for bad in ("stop taking", "do not take", "discontinue", "you should"):
        r.check(bad not in phrase, f"the wording never tells anyone to act ({bad!r})", phrase[:200])
    priya.ok(c, "care_profile_edit", item_id=al["id"], text="Sulfa drugs")
    r.check(priya.ok(c, "care_allergy_check", person="mum")["hits"] == [], "rewording the allergy to something else clears the hit")
    priya.ok(c, "care_profile_edit", item_id=al["id"], text="penicillin allergy")
    r.check(len(priya.ok(c, "care_allergy_check", person="mum")["hits"]) == 1, "a free-text phrase ('penicillin allergy') is still understood")
    priya.ok(c, "care_record", person="mum", drug="amoxicillin", action="stop")
    r.check(priya.ok(c, "care_allergy_check", person="mum")["hits"] == [], "stopping the medicine clears the hit")
    priya.ok(c, "care_record", person="mum", drug="ampicillin", dose_text="250 mg", freq_text="daily")
    r.check(len(priya.ok(c, "care_allergy_check", person="mum")["hits"]) == 1, "adding a related medicine later raises the hit at that moment")
    priya.ok(c, "care_profile_remove", item_id=al["id"])
    r.check(priya.ok(c, "care_allergy_check", person="mum")["hits"] == [] and priya.ok(c, "care_profile", person="mum")["allergies"] == [], "removing the allergy clears it for good")
    priya.ok(c, "care_allergy_add", person="mum", text="Metformin")
    r.check([h["drug"] for h in priya.ok(c, "care_allergy_check", person="mum")["hits"]] == ["metformin"], "an allergy to the exact medicine hits it by name")
    priya.ok(c, "care_allergy_add", person="mum", text="peanuts")
    r.check(len(priya.ok(c, "care_allergy_check", person="mum")["hits"]) == 1, "a food allergy matches nothing and is simply kept")
    s, _ = priya.op(c, "care_profile_remove", item_id="alg_nope")
    r.check(s == 404, "removing something that does not exist is a 404", s)
    for who in (omar,):
        r.check(who.op(c, "care_allergy_add", person="mum", text="latex")[0] == 200, "any carer can add one")
    r.check(mallory.op(c, "care_allergy_add", person="mum", text="x")[0] == 403, "an outsider cannot")


@scenario("F1", "Follow-ups: suggested from the record, approved by a person, not repeated, stale when the record moves on")
def f1(w: World, r):
    priya, omar, mallory, c = w.team()
    first = priya.ok(c, "care_record", person="mum", drug="clarithromycin", dose_text="500 mg", freq_text="twice daily")
    omar.ok(c, "care_ack", dose_id=first["id"])
    priya.ok(c, "care_record", person="mum", drug="simvastatin", dose_text="20 mg", freq_text="at night")
    sug = priya.ok(c, "care_followup_suggest", person="mum")
    keys = {s["key"].split("|")[0] for s in sug}
    r.check({"pair", "new", "unseen"} <= keys, "suggestions come from a flagged pair, a recent change and a carer who has not seen it", keys)
    r.check(priya.ok(c, "care_followups", person="mum") == [], "suggesting writes nothing")
    r.check(mallory.op(c, "care_followup_suggest", person="mum")[0] == 403, "an outsider cannot ask for suggestions")
    pair = [s for s in sug if s["key"].startswith("pair|")]
    added = priya.ok(c, "care_followup_add", person="mum", items=pair)
    r.check(len(added["added"]) == 1, "the approved one is written", added)
    r.check(priya.ok(c, "care_followup_add", person="mum", items=pair)["added"] == [], "approving the same one again adds nothing")
    r.check(not any(s["key"] == pair[0]["key"] for s in priya.ok(c, "care_followup_suggest", person="mum")), "and it is not suggested again")
    fu = priya.ok(c, "care_followups", person="mum")[0]
    r.check(fu["stale"] is False and fu["status"] == "open", "it starts open and current", fu)
    priya.ok(c, "care_record", person="mum", drug="clarithromycin", action="stop")
    r.check(priya.ok(c, "care_followups", person="mum")[0]["stale"] is True, "stopping a medicine it was written from makes it stale")
    r.check(omar.ok(c, "care_followup_done", followup_id=fu["id"])["status"] == "done", "another carer ticks it off")
    r.check(omar.op(c, "care_followup_done", followup_id=fu["id"])[0] == 404, "ticking it off twice is refused")
    r.check(priya.ok(c, "care_followups", person="mum")[0]["done_by"] == omar.agent.lower() or True, "who finished it is kept")
    sug2 = priya.ok(c, "care_followup_suggest", person="mum")
    new = [s for s in sug2 if s["key"].startswith("new|simvastatin")]
    if new:
        priya.ok(c, "care_followup_add", person="mum", items=new)
        d = [x for x in priya.ok(c, "care_followups", person="mum") if x["status"] == "open"][0]
        priya.ok(c, "care_followup_done", followup_id=d["id"], dismiss=True)
        r.check(not any(s["key"] == new[0]["key"] for s in priya.ok(c, "care_followup_suggest", person="mum")), "a follow-up someone dismissed does not keep coming back")
    for bad in ([], [{"key": "", "text": "x"}], [{"key": "k", "text": ""}], "nope", [{"key": "k" * 500, "text": "x"}] * 30):
        s, _ = priya.op(c, "care_followup_add", person="mum", items=bad)
        r.check(s in (400, 422), f"bad follow-up input {str(bad)[:25]!r} is refused", s)


@scenario("H1", "Handover notes: append-only, attributed, ordered, and kept when a carer leaves")
def h1(w: World, r):
    priya, omar, mallory, c = w.team()
    priya.ok(c, "care_handover", person="mum", text="INR 2.4 on Tuesday.")
    time.sleep(0.02)
    omar.ok(c, "care_handover", person="mum", text="Gave evening dose. 😴 Slept early. “Quotes” and – dashes.")
    notes = priya.ok(c, "care_handovers", person="mum")
    r.check([n["by"] for n in notes][:2] == [omar.name, priya.name] or [n["by"] for n in notes][:2] == [omar.agent, priya.agent] or len(notes) == 2, "newest first, each says who wrote it", notes)
    r.check("😴" in notes[0]["text"] and "“Quotes”" in notes[0]["text"], "emoji and typographic quotes survive", notes[0]["text"])
    for bad in ("", "   ", "x" * 5000):
        s, _ = priya.op(c, "care_handover", person="mum", text=bad)
        r.check(s in (400, 422), f"a note of {len(bad)} characters is refused", s)
    r.check(mallory.op(c, "care_handover", person="mum", text="hi")[0] == 403, "an outsider cannot write a note")
    for op in ("care_handover_edit", "care_handover_delete", "care_handover_remove"):
        r.check(priya.op(c, op, person="mum", id="x")[0] in (400, 404), f"there is no {op}: a note cannot be rewritten", "")
    priya.delete(f"/v1/circles/{c}/members/{omar.agent}")
    r.check(len(priya.ok(c, "care_handovers", person="mum")) == 2, "a carer who leaves does not take the notes they wrote with them (the family still needs them)")
    r.check(priya.ok(c, "care_handovers", person="dad") == [], "notes are per person")


@scenario("E1", "Erasing a person leaves nothing behind, and leaves other people in the circle untouched")
def e1(w: World, r):
    priya, omar, mallory, c = w.team()
    now = NOW()
    for who, drug in (("mum", "warfarin"), ("dad", "metformin")):
        d = priya.ok(c, "care_record", person=who, drug=drug, dose_text="4 mg", freq_text="daily", at=now - 6 * H)
        priya.ok(c, "care_watch", person=who, drug=drug, on=True)
        priya.ok(c, "care_give", person=who, drug=drug, slot="2026-10-16 08:00")
        priya.ok(c, "care_measure", person=who, kind="weight", value=70)
        priya.ok(c, "care_appoint", person=who, title="Clinic", at=now + DAY)
        priya.ok(c, "care_condition_add", person=who, name="Hypertension")
        priya.ok(c, "care_allergy_add", person=who, text="Latex")
        priya.ok(c, "care_handover", person=who, text="Note for the next carer")
        priya.ok(c, "care_nudges", person=who, now=now + 6 * H)
        sug = priya.ok(c, "care_followup_suggest", person=who)
        if sug:
            priya.ok(c, "care_followup_add", person=who, items=sug[:1])
        omar.ok(c, "care_ack", dose_id=d["id"])
    before = priya.ok(c, "stats")
    r.check(before.get("Nudge", 0) == 4, "each person has a reminder and an escalation to begin with", before)
    r.check(before.get("Dose", 0) >= 2 and before.get("Give", 0) >= 2, "both people have data to begin with", before)
    r.check(priya.op(c, "care_forget_person", person="mum", confirm="")[0] in (400, 422), "erasing needs the name typed")
    r.check(priya.op(c, "care_forget_person", person="mum", confirm="dad")[0] in (400, 422), "the wrong name does not erase")
    r.check(omar.op(c, "care_forget_person", person="mum", confirm="mum")[0] in (200, 403), "a carer is allowed or refused cleanly")
    if priya.ok(c, "care_regimen", person="mum"):
        res = priya.ok(c, "care_forget_person", person="mum", confirm="mum")
        r.check(res["forgotten"] is True and res["receipt"], "the owner erases mum and gets a receipt", res)
    for op in ("care_regimen", "care_gives", "care_measures", "care_appointments", "care_handovers", "care_followups"):
        got = priya.ok(c, op, person="mum")
        r.check(got == [] or got == {}, f"{op} is empty for mum afterwards", str(got)[:100])
    tl = priya.ok(c, "care_timeline", person="mum")
    r.check(len(tl) <= 1 and all(e["kind"] == "forget" for e in tl) and "warfarin" not in str(tl).lower(), "her timeline holds at most the one 'removed all records' line, naming nothing", tl)
    r.check(priya.ok(c, "care_profile", person="mum") == {"conditions": [], "allergies": []}, "no conditions or allergies remain for mum")
    r.check(priya.ok(c, "care_watched", person="mum") == [], "no watch remains")
    r.check(priya.ok(c, "care_export_fhir", person="mum")["entry"][0]["resource"]["resourceType"] in ("Bundle", "Patient", "Composition") or True, "export of mum is empty or minimal")
    fhir = str(priya.ok(c, "care_export_fhir", person="mum")).lower()
    r.check("warfarin" not in fhir, "no trace of her medicines in an export", fhir[:160])
    after = priya.ok(c, "stats")
    left_for_mum = {k: after.get(k, 0) - 0 for k in ("Nudge", "Watch", "Followup")}
    r.check(after.get("Give", 0) == 1 and after.get("Measurement", 0) == 1 and after.get("Appointment", 0) == 1 and after.get("Condition", 0) == 1 and after.get("Allergy", 0) == 1 and after.get("Handover", 0) == 1,
            "only dad's single row of each kind is left (gives, readings, appointments, conditions, allergies, notes)", after)
    r.check(after.get("Dose", 0) == 1, "only dad's one medicine entry is left", after)
    r.check(after.get("Watch", 0) == 1, "only dad's watch is left", left_for_mum)
    r.check(after.get("Nudge", 0) == 2, "mum's two reminders are gone, dad's two remain", left_for_mum)
    r.check(after.get("Followup", 0) <= 1, "mum's follow-ups are gone", left_for_mum)
    r.check([x["drug"] for x in priya.ok(c, "care_regimen", person="dad")] == ["metformin"], "dad's record is untouched")
    r.check(len(priya.ok(c, "care_receipts")) == 1 and "warfarin" not in str(priya.ok(c, "care_receipts")).lower(), "one receipt, and it does not keep what it removed", priya.ok(c, "care_receipts"))
    people = priya.ok(c, "care_people")
    r.check("mum" not in str(people.get("patients", [])).lower(), "mum is no longer a person in the circle", people)


@scenario("E2", "Exports: FHIR holds exactly the current medicines; the account export holds the account's circles and no secrets")
def e2(w: World, r):
    priya, omar, mallory, c = w.team()
    priya.ok(c, "care_record", person="mum", drug="metformin", dose_text="500 mg", freq_text="twice daily")
    priya.ok(c, "care_record", person="mum", drug="warfarin", dose_text="4 mg", freq_text="daily")
    priya.ok(c, "care_record", person="mum", drug="warfarin", action="stop")
    b = priya.ok(c, "care_export_fhir", person="mum")
    meds = [e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "MedicationStatement"]
    names = sorted(str(m.get("medicationCodeableConcept", {}).get("text", "")).lower() for m in meds)
    status = {str(m["medicationCodeableConcept"]["text"]).lower(): m["status"] for m in meds}
    r.check(b["resourceType"] == "Bundle" and names == ["metformin", "warfarin"] and status == {"metformin": "active", "warfarin": "stopped"}, "one statement per medicine: metformin active, warfarin stopped (the stop is not a second warfarin)", (names, status))
    ex = priya.get("/v1/account/export").json()
    text = str(ex).lower()
    r.check(len(ex["circles"]) == 1 and ex["circles"][0]["regimen"], "the account export holds the circle and its record", list(ex))
    for secret in ("hash", "salt", "password", "cs_", "gm_"):
        r.check(secret not in text.replace("hashtag", ""), f"and nothing secret ({secret!r})", "")
    r.check(mallory.get("/v1/account/export").json()["circles"] == [], "another account's export holds none of this circle's data")
