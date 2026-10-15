"""Ten weeks of realistic (synthetic) history for the shared demo circle: a 78-year-old with high blood pressure, type 2 diabetes, high
cholesterol, an underactive thyroid, reflux and atrial fibrillation, looked after by two carers. Entries come from the sources a family really
has: a discharge letter, pharmacy labels, a clinic's phone call, a shop bottle. Every quoted line below occurs in its source text, so the
verification step passes honestly. Nothing here is advice: it is what the carers were told, recorded as they would have recorded it.

Times are relative to when the circle is built, so the story always ends "now": one change is not yet seen by Ravi and one not by Meena."""
from __future__ import annotations

from datetime import datetime, timedelta

from graphmem.db import norm

H = 3_600_000
D = 24 * H

DISCHARGE = """CITY GENERAL HOSPITAL  -  DISCHARGE MEDICATION LIST
Patient: ASHA (synthetic)   Age 78   Ward 4B
Diagnoses: hypertension, type 2 diabetes, hypercholesterolaemia, hypothyroidism, reflux
1. Metformin 500 mg tablets - one tablet twice daily with meals
2. Amlodipine 5 mg tablets - one tablet once daily
3. Atorvastatin 20 mg tablets - one tablet at bedtime
4. Lisinopril 10 mg tablets - one tablet once daily in the morning
5. Levothyroxine 50 mcg tablets - one tablet each morning on an empty stomach
6. Omeprazole 20 mg capsules - one capsule once daily before breakfast
Review with your GP in 2 weeks."""

WARFARIN_LABEL = """CITY PHARMACY   Rx 20931
ASHA (synthetic)
WARFARIN 3 MG TABLETS
TAKE ONE TABLET EVERY EVENING OR AS DIRECTED BY THE ANTICOAGULANT CLINIC
QTY 28   REFILLS 2"""

INR_CALL = ("Meena said: the anticoagulant clinic nurse rang this morning, the INR was a little low so she said warfarin goes up "
            "to four milligrams every evening starting tonight, and they will test again in a week")

BP_CALL = ("Ravi said: the doctor looked at the blood pressure diary and said to increase amlodipine from five to ten milligrams "
           "once a day from tomorrow")

CLINIC_LETTER = """Riverside Medical Practice
Re: ASHA (synthetic)  -  cholesterol review
Following the repeat blood tests we have changed:
Atorvastatin 40 mg tablets - one tablet at bedtime (previously 20 mg)
Please attend for a repeat test in 3 months."""

IBUPROFEN_BOTTLE = "Shop bottle: Ibuprofen 400 mg tablets. Adults take one tablet up to twice a day with food. Not more than 3 days without advice."

CLARI_LABEL = """URGENT CARE PHARMACY   Rx 55012
ASHA (synthetic)
CLARITHROMYCIN 500 MG TABLETS
TAKE ONE TABLET TWICE DAILY FOR 7 DAYS
QTY 14   REFILLS 0"""

THYROID_LETTER = """Riverside Medical Practice
Re: ASHA (synthetic)  -  thyroid blood test
Levothyroxine 75 mcg tablets - one tablet each morning on an empty stomach (previously 50 mcg)
Repeat thyroid test in 8 weeks."""

CETIRIZINE_LABEL = """GREEN CROSS PHARMACY   Rx 77310
ASHA (synthetic)
CETIRIZINE 10 MG TABLETS
TAKE ONE TABLET AT NIGHT WHEN NEEDED FOR ITCHING
QTY 10"""


def _slot(day: datetime, hhmm: str) -> str:
    return f"{day:%Y-%m-%d} {hhmm}"


async def build(ravi, meena, person: str, now: int) -> None:
    """Write the history through the same public operations the app uses (care_record / care_ack / care_give)."""
    handle = {"ravi": ravi, "meena": meena}
    ts = lambda days_ago, hours=0: now - int(days_ago * D) - hours * H          # noqa: E731

    async def rec(who, days_ago, drug, dose, freq, src="typed", quote="", text="", action="set"):
        r = await handle[who].care_record(person, drug, action=action, dose_text=dose, freq_text=freq, source_type=src, quote=quote,
                                          source_text=text, at=ts(days_ago))
        return r["id"]

    async def ack(who, dose_id, days_ago, extra_hours=0.0):
        await handle[who].care_ack(dose_id)
        await handle[who]._q("MATCH (:Person {id:$me})-[a:ACKED]->(x:Dose {id:$id}) SET a.at=$t",
                             {"me": norm(handle[who].agent), "id": dose_id, "t": ts(days_ago) + int(extra_hours * H)})

    # week -10: the discharge letter, photographed and typed in by Ravi, then seen by Meena
    ids = []
    for drug, dose, freq, quote in [
        ("metformin", "500 mg", "twice daily with meals", "Metformin 500 mg tablets - one tablet twice daily with meals"),
        ("amlodipine", "5 mg", "once daily", "Amlodipine 5 mg tablets - one tablet once daily"),
        ("atorvastatin", "20 mg", "at bedtime", "Atorvastatin 20 mg tablets - one tablet at bedtime"),
        ("lisinopril", "10 mg", "once daily in the morning", "Lisinopril 10 mg tablets - one tablet once daily in the morning"),
        ("levothyroxine", "50 mcg", "each morning, empty stomach", "Levothyroxine 50 mcg tablets - one tablet each morning on an empty stomach"),
        ("omeprazole", "20 mg", "once daily before breakfast", "Omeprazole 20 mg capsules - one capsule once daily before breakfast"),
    ]:
        ids.append(await rec("ravi", 70, drug, dose, freq, "document", quote, DISCHARGE))
    for i in ids:
        await ack("meena", i, 69.6)
    vit = await rec("meena", 68, "vitamin d", "1000 iu", "once daily")                                       # from the bottle on the shelf
    await ack("ravi", vit, 67.5)
    para = await rec("ravi", 66, "acetaminophen", "500 mg", "up to 4 times a day if needed")
    await ack("meena", para, 65.8)

    # week -7: atrial fibrillation: a blood thinner from the pharmacy label; the dose is changed after a clinic call
    w = await rec("ravi", 49, "warfarin", "3 mg", "once daily, evening", "photo", "WARFARIN 3 MG TABLETS", WARFARIN_LABEL)
    await ack("meena", w, 48.9)
    w2 = await rec("meena", 42, "warfarin", "4 mg", "every evening", "voice", "warfarin goes up to four milligrams every evening", INR_CALL)
    await ack("ravi", w2, 41.2)

    # week -5 and -4: the blood-pressure and cholesterol doses are raised
    a2 = await rec("ravi", 35, "amlodipine", "10 mg", "once daily", "voice", "increase amlodipine from five to ten milligrams once a day", BP_CALL)
    await ack("meena", a2, 34.9)
    s2 = await rec("ravi", 28, "atorvastatin", "40 mg", "at bedtime", "document", "Atorvastatin 40 mg tablets - one tablet at bedtime", CLINIC_LETTER)
    await ack("meena", s2, 27.6)

    # week -3: a painkiller bought over the counter for the knee (a major flag against warfarin), noticed late, then recorded as stopped
    ib = await rec("meena", 21, "ibuprofen", "400 mg", "up to twice a day with food", "photo", "Ibuprofen 400 mg tablets", IBUPROFEN_BOTTLE)
    await ack("ravi", ib, 19.0)
    ibs = await rec("ravi", 16, "ibuprofen", "400 mg", "up to twice a day with food", action="stop")
    await ack("meena", ibs, 15.9)

    # week -2: a short antibiotic course from urgent care (major flags against warfarin and atorvastatin), finished
    cl = await rec("ravi", 11, "clarithromycin", "500 mg", "twice daily for 7 days", "photo", "CLARITHROMYCIN 500 MG TABLETS", CLARI_LABEL)
    await ack("meena", cl, 10.9)
    cls = await rec("ravi", 4, "clarithromycin", "500 mg", "twice daily for 7 days", action="stop")
    await ack("meena", cls, 3.7)

    # this week: a thyroid dose change that Meena has not yet seen, and an antihistamine from Meena that Ravi has not yet seen
    await rec("ravi", 3, "levothyroxine", "75 mcg", "each morning, empty stomach", "document", "Levothyroxine 75 mcg tablets - one tablet each morning on an empty stomach", THYROID_LETTER)
    await rec("meena", 0.8, "cetirizine", "10 mg", "at night when needed", "photo", "CETIRIZINE 10 MG TABLETS", CETIRIZINE_LABEL)

    # readings the carers took or were told (typed as given; the app never judges them). They line up with the warfarin and amlodipine changes above.
    for days, who, v in ((66, "ravi", 154), (58, "ravi", 152), (50, "meena", 156), (44, "ravi", 151), (37, "meena", 150), (31, "ravi", 141), (24, "meena", 138),
                         (17, "ravi", 136), (10, "meena", 137), (3, "ravi", 135)):
        await handle[who].care_measure(person, "bp_systolic", v, "mmHg", at=ts(days))
        await handle[who].care_measure(person, "bp_diastolic", round(v * 0.57), "mmHg", at=ts(days))
    for days, v in ((46, 1.7), (40, 1.8), (35, 1.9), (28, 2.1), (21, 2.4), (14, 2.6), (7, 2.5), (1.5, 2.4)):
        await handle["meena"].care_measure(person, "inr", v, at=ts(days))
    for days, v in ((64, 8.9), (50, 8.4), (36, 8.1), (22, 7.8), (8, 7.6)):
        await handle["ravi"].care_measure(person, "glucose", v, "mmol/L", at=ts(days))
    for days, v in ((62, 61.2), (40, 60.8), (18, 60.1), (4, 59.9)):
        await handle["meena"].care_measure(person, "weight", v, "kg", at=ts(days))

    # the family's own notes about who she is and what is coming up
    for c in ("Type 2 diabetes", "High blood pressure", "Atrial fibrillation", "Underactive thyroid", "Reflux"):
        await handle["ravi"].care_condition_add(person, c)
    await handle["ravi"].care_allergy_add(person, "Penicillin")
    for days, who, name, place, bring in ((-3, "meena", "Anticoagulant clinic: INR check", "Riverside Medical Practice", "INR diary, warfarin box, list of every medicine"),
                                           (12, "ravi", "GP review: blood pressure and thyroid", "Riverside Medical Practice", "BP diary, recent blood test results"),
                                           (-21, "ravi", "Eye check", "City Eye Clinic", "Glasses, medicine list")):
        await handle[who].care_appoint(person, name, now - int(days * D), place, who, bring)
    await handle["meena"].care_appoint(person, "Diabetes review (done)", ts(30), "City General", "meena", "")

    # the last seven days of doses actually given (each slot can be claimed once; who gave it is kept)
    sched = [("levothyroxine", "07:00", "ravi"), ("omeprazole", "07:30", "ravi"), ("metformin", "08:00", "ravi"), ("amlodipine", "08:00", "ravi"),
             ("lisinopril", "08:00", "ravi"), ("vitamin d", "08:00", "meena"), ("warfarin", "18:00", "meena"), ("metformin", "19:30", "meena"),
             ("atorvastatin", "21:30", "meena")]
    skip = {(5, "vitamin d"), (3, "metformin|19:30"), (2, "amlodipine")}                                      # a few honest gaps
    today = datetime.fromtimestamp(now / 1000)
    for back in range(7, -1, -1):
        day = today - timedelta(days=back)
        for drug, hhmm, who in sched:
            if (back, drug) in skip or (back, f"{drug}|{hhmm}") in skip:
                continue
            h, m = (int(x) for x in hhmm.split(":"))
            when = day.replace(hour=h, minute=m, second=0, microsecond=0)
            at = int(when.timestamp() * 1000) + 6 * 60_000
            if at > now:
                continue
            # an early-morning warfarin dose belongs to Ravi on weekends: the circle shares the work
            giver = "ravi" if (back % 2 == 0 and drug in ("warfarin", "atorvastatin")) else who
            slot = _slot(day, hhmm)
            r = await handle[giver].care_give(person, drug, slot)
            if r.get("given"):
                await handle[giver]._q("MATCH (g:Give {key:$k}) SET g.at=$t", {"k": f"{norm(person)}|{norm(drug)}|{norm(slot)}", "t": at})
