import json, math, pytest, time
from carecircle import risk, reference
from carecircle.checks import Checker


def test_noisy_or_and_decay():
    assert risk.regimen_risk([]) == 0.0
    assert risk.regimen_risk([0.7, 0.3]) == pytest.approx(1 - 0.3 * 0.7, abs=1e-4)
    assert risk.decay(0) == 1.0 and risk.decay(72) == pytest.approx(0.5)
    assert risk.severity_weight("Unknown") is None and risk.severity_weight("Major") == 0.7
    assert 0 < risk.divergence([0.7], [10]) < risk.divergence([0.7], [200]) <= 1


def test_fda_parse():
    f = reference.parse_fda_cyp(open(reference.DATA / "fda_cyp.html", encoding="utf-8", errors="ignore").read())
    assert ("clarithromycin", "CYP3A", "strong") in f["inhibits"]
    assert ("warfarin", "CYP2C9") in f["substrates"]            # S-warfarin footnote stripped


@pytest.fixture(scope="module")
def chk():
    return Checker()


def test_direct_flag_and_unknown_not_safe(chk):
    r = chk.check(["Simvastatin", "Clarithromycin", "metformin"])
    assert any(x["level"] == "major" and set(x["drugs"]) == {"clarithromycin", "simvastatin"} for x in r["direct"])
    assert r["regimen_risk"] >= 0.7 and "not a statement of safety" in r["notice"]


def test_enzyme_path_via_graph(chk):
    r = chk.check(["fluconazole", "warfarin"])                    # CYP2C9 moderate inhibitor + substrate
    assert any("CYP2C9" in p["path"] for p in r["enzyme_paths"])


def test_control_unrelated_and_unknown_drug(chk):
    r = chk.check(["amlodipine", "notarealdrug"])
    assert r["not_in_reference"] == ["notarealdrug"] and r["regimen_risk"] == 0.0


# ---- circle graph (tenant-scoped, real FalkorDB) ----
import asyncio
from conftest import day, tid

H = 3_600_000


async def circle(gm, *carers):
    t = tid(gm, "cc")
    for c in ("amma", *carers):
        await gm.grant(c, t, ("read", "write", "admin"))
    return t, {c: gm.open(c, t) for c in carers}


async def test_supersession_quote_verify_and_regimen(gm):
    t, c = await circle(gm, "ravi", "meena")
    m = c["ravi"]
    a = await m.care_record("mum", "warfarin", dose_text="5 mg", freq_text="at bedtime", source_type="photo",
                            quote="Warfarin Sodium 5mg", source_ref=await m.care_store_source("image", "CITYPHARMACYRx48213 WarfarinSodium5mgtablets Qty30"))
    assert a["status"] == "confirmed" and a["verified"]
    b = await m.care_record("mum", "warfarin", dose_text="3 mg", source_type="photo", quote="Warfarin 3 mg",
                            source_ref=await m.care_store_source("image", "something else entirely"))
    assert b["status"] == "pending" and not b["verified"]             # quote not in source: never counts until confirmed
    assert [r["dose_text"] for r in await m.care_regimen("mum")] == ["5 mg"]
    await m.care_confirm(b["id"])
    assert [r["dose_text"] for r in await m.care_regimen("mum")] == ["3 mg"]
    old = await m.care_regimen("mum", as_of=0)
    assert old == []                                                    # as-of before anything existed
    await m.care_record("mum", "warfarin", action="stop")
    assert await m.care_regimen("mum") == []


async def test_check_staleness_and_nudges_once(gm):
    t, c = await circle(gm, "ravi", "meena")
    r, mn = c["ravi"], c["meena"]
    await mn.care_ack((await mn.care_record("mum", "metformin"))["id"])          # meena exists as carer
    d1 = await r.care_record("mum", "simvastatin")
    await r.care_record("mum", "clarithromycin")                                  # major interaction with simvastatin
    chk = await r.care_check("mum")
    assert any(f["level"] == "major" for f in chk["direct"])
    div = await r.care_divergence("mum")
    assert div["carers"]["meena"]["divergence"] > 0 and div["most_out_of_date"] == "meena"
    await mn.care_ack(d1["id"])
    later = int(__import__("time").time() * 1000) + 20 * H
    n1 = await r.care_nudges("mum", now=later)
    n2 = await r.care_nudges("mum", now=later)
    assert n1 and n2 == []                                                        # a reminder is produced once


async def test_double_dose_race_has_one_winner(gm):
    t, c = await circle(gm, "ravi", "meena")
    await c["ravi"].care_record("mum", "metformin", dose_text="500 mg", at=int(time.time() * 1000) - 3 * 24 * 3_600_000)      # a dose can only be given of a medicine that is on the record
    res = await asyncio.gather(*[c["ravi" if i % 2 else "meena"].care_give("mum", "metformin", f"{day(-1)} 08:00") for i in range(10)])
    assert sum(x["given"] for x in res) == 1
    assert all(x["given"] or x["already_given_by"] in ("ravi", "meena") for x in res)


async def test_resolve_noisy_ocr(gm):
    t, c = await circle(gm, "ravi")
    top = await c["ravi"].care_resolve("WarfarinSodium5mgtablets")
    assert top and top[0]["name"].startswith("warfarin")


# ---- intake ----
from carecircle import intake


def test_rule_proposals_noisy_ocr_and_verify():
    ch = Checker()
    text = "CITY PHARMACY\nWarfarinSodium5mgtablets\nTake ONE tablet daily at bedtime"
    p = intake.rule_proposals(text, ch)
    assert p and p[0]["drug_candidates"][0]["name"].startswith("warfarin") and p[0]["dose_text"].lower() == "5mg"
    assert intake.quote_in_source(p[0]["quote"], text)
    assert not intake.quote_in_source("Warfarin 3 mg", text)


def test_speech_misspelling_is_matched_and_plain_words_are_not():
    ch = Checker()
    p = intake.rule_proposals("The doctor started chlorythromycin 500 mg twice daily for seven days.", ch)   # a real Whisper transcript
    assert p and p[0]["drug_candidates"][0]["name"] == "clarithromycin" and p[0]["dose_text"] == "500 mg"
    assert not intake.rule_proposals("Take one tablet every morning with water and food. Bring the prescription tomorrow evening.", ch)


def test_real_photo_ocr_texts_strength_on_next_line_and_brands():
    ch = Checker()     # OCR output from real bottle photos (Wikimedia Commons), copied verbatim
    label = "NDC 62856-243-05\nRx only\nAcipHex\nrabeprazolesodium\n20mg\n5Delayed-ReleaseTablets"
    p = intake.rule_proposals(label, ch)
    assert p[0]["drug_candidates"][0]["name"] == "rabeprazole" and p[0]["dose_text"] == "20mg"
    assert intake.quote_in_source(p[0]["quote"], label)
    assert intake.rule_proposals("Advil\nLIQUI-GELS\nLiquidFilled\nCapsules", ch)[0]["drug_candidates"][0]["name"] == "ibuprofen"
    assert intake.rule_proposals("GENUINE ASPIRIN\nORIGINAL", ch)[0]["drug_candidates"][0]["name"] == "acetylsalicylic acid"


def test_unsupported_and_corrupt_files_do_not_crash():
    assert intake.read_source(b"junk", "x.bin")["status"] == "unsupported"
    assert intake.read_source(b"%PDF-broken", "x.pdf")["status"] == "unsupported"
    assert intake.read_source(b"   ", "n.txt")["status"] == "empty"


def test_image_roundtrip_ocr_and_llm_off(monkeypatch):
    monkeypatch.setenv("CC_LLM", "0")
    from carecircle import demo
    src = intake.read_source(demo.label_png("Warfarin Sodium 5 mg tablets", "Take ONE tablet daily at bedtime"), "label.png", "image/png")
    assert src["status"] == "ok"
    props = intake.propose(src["text"], Checker())
    assert props and props[0]["drug_candidates"][0]["name"].startswith("warfarin") and props[0]["verified"]


# ---- safety layer ----
from carecircle import safety


def test_advice_scanner_and_reword_guard():
    assert safety.scan_advice({"a": "You should stop taking the tablet"}) and safety.scan_advice("it is safe to take")
    assert not safety.scan_advice({"statement": "Possible interactions found: discuss with a prescriber.", "quote": "take ONE tablet daily"})
    facts = {"drug": "warfarin", "hours": 14.0}
    assert safety.numbers_match_facts("change to warfarin 14 hours ago", facts)
    assert not safety.numbers_match_facts("change to warfarin 15 hours ago", facts)
    assert safety.reword("tpl 14", facts, lambda t, f: "made up 99")["source"] == "template"
    assert safety.reword("tpl 14", facts, lambda t, f: "warfarin changed 14 hours ago")["source"] == "model"


async def test_no_output_gives_advice_and_judgement_states(gm):
    t, c = await circle(gm, "ravi", "meena")
    r, mn = c["ravi"], c["meena"]
    assert (await r.care_check("mum"))["judgement"]["state"] == "no_data"
    await mn.care_ack((await mn.care_record("mum", "amlodipine"))["id"])
    assert (await r.care_check("mum"))["judgement"]["state"] == "no_known_conflict"
    await r.care_record("mum", "notarealdrug")
    assert (await r.care_check("mum"))["judgement"]["state"] == "partial"
    await r.care_record("mum", "simvastatin"); await r.care_record("mum", "clarithromycin")
    outputs = [await r.care_check("mum"), await r.care_divergence("mum"), await r.care_regimen("mum"),
               await r.care_nudges("mum", now=int(__import__("time").time() * 1000) + 30 * H)]
    assert (await r.care_check("mum"))["judgement"]["state"] == "flags"
    for o in outputs:
        assert safety.scan_advice(o) == [], safety.scan_advice(o)


# ---- telegram shell (fake API, no network) ----
from carecircle.telegram import Bot


class FakeApi:
    def __init__(self): self.out = []
    def send(self, chat, text, buttons=None): self.out.append((chat, text, buttons))
    def download(self, fid):
        from carecircle import demo
        return demo.label_png("Warfarin Sodium 5 mg tablets", "Take ONE tablet daily at bedtime"), "p.png"


async def test_a_slow_telegram_reply_does_not_stall_everything_else(gm):
    """The bot runs in the same process as the web server: a Telegram call that takes seconds must not freeze the event loop for that long."""
    import asyncio
    import time

    class SlowApi(FakeApi):
        def send(self, chat, text, buttons=None):
            time.sleep(0.6)                                         # a blocking HTTP call, as urllib is
            super().send(chat, text, buttons)

    api, ticks, stop = SlowApi(), [], asyncio.Event()

    async def ticker():
        while not stop.is_set():
            ticks.append(time.perf_counter())
            await asyncio.sleep(0.02)

    bot = Bot(gm, api, Checker())
    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.1)
    await bot.handle({"message": {"chat": {"id": 7}, "text": "/start"}})
    await asyncio.sleep(0.1)                                        # let the ticker tick once more, so a freeze shows up as a gap
    stop.set()
    await task
    assert api.out and "records and cross-checks" in api.out[-1][1]
    assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.3, "the event loop was blocked while the message was sent"


async def test_bot_link_photo_confirm_check_and_nudge(gm, monkeypatch):
    monkeypatch.setenv("CC_LLM", "0")
    t, c = await circle(gm, "ravi", "meena")
    key = await gm.issue_key("ravi"); key2 = await gm.issue_key("meena")
    api = FakeApi(); bot = Bot(gm, api, Checker())
    await bot.handle({"message": {"chat": {"id": 1}, "text": "/regimen mum"}})
    assert "link this chat first" in api.out[-1][1]
    await bot.handle({"message": {"chat": {"id": 1}, "text": f"/link {key} {t}"}})
    await bot.handle({"message": {"chat": {"id": 2}, "text": f"/link {key2} {t}"}})
    assert "Linked as ravi" in api.out[-2][1]
    await bot.handle({"message": {"chat": {"id": 1}, "photo": [{"file_id": "x"}]}})
    chat, msg, btn = api.out[-1]
    assert "warfarin" in msg and btn and "quote verified" in msg
    await bot.handle({"callback_query": {"message": {"chat": {"id": 1}}, "data": btn[0][0]["callback_data"]}})
    await bot.handle({"message": {"chat": {"id": 1}, "text": "/regimen mum"}})
    assert "warfarin" in api.out[-1][1].lower()
    await bot.handle({"message": {"chat": {"id": 1}, "text": "/check mum"}})
    assert "not a statement of safety" in api.out[-1][1] or "Possible interactions" in api.out[-1][1]
    later = int(__import__("time").time() * 1000) + 6 * H
    await bot.handle({"message": {"chat": {"id": 2}, "text": "/who"}})        # meena appears as a carer only after acting; ack makes her one
    await c["meena"].care_ack((await c["meena"].care_record("mum", "vitamin d"))["id"])
    await c["ravi"].care_record("mum", "metformin")
    assert await bot.deliver_nudges(now=later) >= 1 and await bot.deliver_nudges(now=later) == 0
    await bot.handle({"message": {"chat": {"id": 2}, "text": "/ack"}})
    assert "Acknowledged" in api.out[-1][1]


async def test_demo_circle_and_label(gm):
    from carecircle import demo
    out = await demo.start(gm)
    gm._created.append(out["circle"])
    m = gm.open(out["agents"]["ravi"], out["circle"])
    assert {r["drug"] for r in await m.care_regimen("asha")} == {"metformin", "amlodipine", "atorvastatin", "vitamin d"}
    src = intake.read_source(demo.label_png(), "l.png", "image/png")
    props = intake.propose(src["text"], Checker())
    assert props and props[0]["drug_candidates"][0]["name"] == "clarithromycin"


async def test_bot_uses_the_circles_own_patient_by_default(gm, monkeypatch):
    monkeypatch.setenv("CC_LLM", "0")
    t, c = await circle(gm, "ravi")
    await c["ravi"].care_record("asha", "metformin", dose_text="500 mg")
    key = await gm.issue_key("ravi")
    api = FakeApi(); bot = Bot(gm, api, Checker())
    await bot.handle({"message": {"chat": {"id": 7}, "text": f"/link {key} {t}"}})
    await bot.handle({"message": {"chat": {"id": 7}, "text": "/regimen"}})
    assert "metformin" in api.out[-1][1]
    await bot.handle({"message": {"chat": {"id": 7}, "text": "Please start warfarin 5 mg once daily"}})
    btn = api.out[-1][2]
    assert "asha" in btn[0][0]["text"] and btn[0][0]["callback_data"].endswith("|asha")
    await bot.handle({"callback_query": {"message": {"chat": {"id": 7}}, "data": btn[0][0]["callback_data"]}})
    assert {r["drug"] for r in await c["ravi"].care_regimen("asha")} == {"metformin", "warfarin"}


async def test_a_carer_who_only_records_still_gets_reminders(gm):
    t, c = await circle(gm, "ravi", "meena")
    await c["ravi"].care_record("asha", "metformin")                       # ravi never acknowledges anything
    old = int(__import__("time").time() * 1000) - 5 * H
    await c["meena"].care_record("asha", "fluconazole", at=old)
    due = await c["ravi"].care_nudges("asha")
    assert [(n["kind"], n["notify"]) for n in due if n["drug"] == "fluconazole"] == [("remind", "ravi")]


def test_speech_decodes_a_telegram_style_opus_voice_note():
    """Regression: a voice note (Ogg/Opus, as Telegram sends it) must decode and transcribe without raising."""
    import io, math, struct, wave
    import av
    buf = io.BytesIO()
    w = wave.open(buf, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(i / 15))) for i in range(24000))); w.close()
    buf.seek(0)
    out = io.BytesIO()
    src, dst = av.open(buf), av.open(out, "w", format="ogg")
    st = dst.add_stream("libopus", rate=48000); st.layout = "mono"
    rs = av.AudioResampler(format="s16", layout="mono", rate=48000)
    for fr in src.decode(audio=0):
        for f in rs.resample(fr):
            for p in st.encode(f): dst.mux(p)
    for p in st.encode(None): dst.mux(p)
    dst.close()
    src = intake.read_source(out.getvalue(), "voice/file_3.oga", "audio/ogg")
    assert src["status"] in ("ok", "empty") and src["kind"] != "unknown"      # a tone has no words: 'empty' is fine, a crash is not


# ---- graph view, timeline, forgetting, FHIR ----
async def _regimen_with_conflict(gm):
    t, c = await circle(gm, "ravi", "meena")
    for d in ("atorvastatin", "amlodipine", "metformin"):
        await c["ravi"].care_record("asha", d, dose_text="10 mg", freq_text="once daily", at=int(time.time() * 1000) - 3 * 24 * 3_600_000)
    r = await c["meena"].care_record("asha", "clarithromycin", dose_text="500 mg", freq_text="twice daily", source_type="photo",
                                     quote="Clarithromycin 500 mg tablets", source_ref=await c["meena"].care_store_source("image", "DEMO\nClarithromycin 500 mg tablets\nTake one"))
    return t, c, r


async def test_care_graph_has_nodes_edges_and_readable_metadata(gm):
    t, c, r = await _regimen_with_conflict(gm)
    g = await c["ravi"].care_graph("asha")
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"patient", "carer", "dose", "drug", "enzyme"} <= kinds
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])             # no dangling edges
    cla = next(n for n in g["nodes"] if n["id"] == "drug:clarithromycin")
    meta = dict(map(tuple, cla["meta"]))
    assert "Interaction pairs in the reference data" in meta and meta["On record now"] == "yes"
    dose = next(n for n in g["nodes"] if n["id"] == f"dose:{r['id']}")
    dm = dict(map(tuple, dose["meta"]))
    assert dm["Source"] == "read from a photo" and "Clarithromycin 500 mg tablets" in dm["Line it was read from"]
    assert dm["Acknowledged by"] == "nobody yet" and dm["Recorded by"].startswith("Meena")
    assert any(e["kind"] == "interacts" and e["level"] == "major" for e in g["edges"])
    assert any(e["kind"] == "inhibits" for e in g["edges"]) and any(e["kind"] == "substrate" for e in g["edges"])
    meena = next(n for n in g["nodes"] if n["id"].startswith("person:meena"))
    assert dict(map(tuple, meena["meta"]))["Changes recorded"] == "1"
    ravi = next(n for n in g["nodes"] if n["id"].startswith("person:ravi"))
    assert "clarithromycin" in dict(map(tuple, ravi["meta"]))["Changes not yet seen"].lower()


async def test_care_graph_text_never_advises_and_history_is_optional(gm):
    from carecircle.safety import scan_advice
    t, c, r = await _regimen_with_conflict(gm)
    await c["ravi"].care_record("asha", "metformin", dose_text="850 mg")                    # supersedes
    g = await c["ravi"].care_graph("asha")
    for n in g["nodes"]:
        assert not scan_advice(n["summary"]) and not any(scan_advice(str(v)) for _, v in n["meta"])
    for e in g["edges"]:
        assert not scan_advice(e["summary"])
    assert any(n["kind"] == "dose_old" for n in g["nodes"]) and any(e["kind"] == "supersedes" for e in g["edges"])
    g2 = await c["ravi"].care_graph("asha", include_history=False)
    assert not any(n["kind"] == "dose_old" for n in g2["nodes"])


async def test_timeline_reads_as_sentences(gm):
    t, c, r = await _regimen_with_conflict(gm)
    await c["ravi"].care_ack(r["id"])
    await c["ravi"].care_give("asha", "metformin", f"{day(-1)} 08:00")
    tl = await c["ravi"].care_timeline("asha")
    texts = [e["text"] for e in tl]
    assert any("Meena recorded Clarithromycin 500 mg twice daily, read from a photo" in x for x in texts)
    assert any("Ravi acknowledged the entry for Clarithromycin" in x for x in texts)
    assert any("recorded Metformin as given" in x for x in texts)
    assert [e["at"] for e in tl] == sorted((e["at"] for e in tl), reverse=True)


async def test_forget_entry_leaves_a_receipt_and_no_content(gm):
    t, c, r = await _regimen_with_conflict(gm)
    await c["ravi"].care_ack(r["id"])
    out = await c["ravi"].care_forget(r["id"], reason="entered by mistake")
    assert out["forgotten"] and len(out["sha256"]) == 64
    assert "clarithromycin" not in {x["drug"] for x in await c["ravi"].care_regimen("asha")}
    g = await c["ravi"].care_graph("asha")
    assert "clarithromycin" not in json.dumps(g).lower()                                    # nothing left to show anywhere
    rc = await c["ravi"].care_receipts()
    assert rc[0]["receipt"] == out["receipt"] and rc[0]["reason"] == "entered by mistake"
    assert "clarithromycin" not in json.dumps(rc).lower()
    with pytest.raises(KeyError):
        await c["ravi"].care_forget(r["id"])


async def test_forget_person_needs_the_name_and_removes_everything(gm):
    t, c, r = await _regimen_with_conflict(gm)
    await c["ravi"].care_give("asha", "metformin", f"{day(-1)} 08:00")
    with pytest.raises(ValueError):
        await c["ravi"].care_forget_person("asha", confirm="nope")
    out = await c["ravi"].care_forget_person("asha", confirm="Asha")
    assert out["forgotten"] and out["removed_entries"] == 4 and out["removed_dose_records"] == 1
    assert await c["ravi"].care_regimen("asha") == [] and await c["ravi"].care_gives("asha") == []
    assert "asha" not in (await c["ravi"].care_people())["patients"]


async def test_fhir_bundle_shape_and_free_text_only(gm):
    t, c, r = await _regimen_with_conflict(gm)
    b = await c["ravi"].care_export_fhir("asha")
    assert b["resourceType"] == "Bundle" and b["entry"][0]["resource"]["resourceType"] == "Patient"
    ms = [e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "MedicationStatement"]
    assert len(ms) == 4 and all(m["status"] == "active" and m["subject"]["reference"] == "Patient/asha" for m in ms)
    cla = next(m for m in ms if m["medicationCodeableConcept"]["text"] == "Clarithromycin")
    assert "coding" not in cla["medicationCodeableConcept"] and cla["dosage"][0]["text"] == "500 mg twice daily"
    assert "Quote verified" in cla["note"][0]["text"] and "photo" in cla["note"][0]["text"]
    json.dumps(b)


async def test_pending_proposal_survives_a_restart(gm, monkeypatch):
    monkeypatch.setenv("CC_LLM", "0")
    t, c = await circle(gm, "ravi")
    key = await gm.issue_key("ravi")
    api = FakeApi()
    await Bot(gm, api, Checker()).handle({"message": {"chat": {"id": 5}, "text": f"/link {key} {t}"}})
    await Bot(gm, api, Checker()).handle({"message": {"chat": {"id": 5}, "text": "Please start warfarin 5 mg once daily"}})
    btn = api.out[-1][2][0][0]["callback_data"]
    fresh = Bot(gm, api, Checker())                       # a new process: nothing in memory
    await fresh.handle({"callback_query": {"message": {"chat": {"id": 5}}, "data": btn}})
    assert "Saved warfarin" in api.out[-1][1]
    await fresh.handle({"callback_query": {"message": {"chat": {"id": 5}}, "data": btn}})          # a second tap does nothing
    assert "expired" in api.out[-1][1]
    await fresh.handle({"message": {"chat": {"id": 5}, "text": "/history"}})
    assert "recorded Warfarin 5 mg once daily" in api.out[-1][1]


def test_label_frequency_two_lines_below_the_drug_is_read():
    ch = Checker()
    text = "DEMO PHARMACY\nPatient: Asha\nClarithromycin 500 mg tablets\nTake ONE tablet twice daily for 7 days\nQty 14"
    p = intake.rule_proposals(text, ch)[0]
    assert p["dose_text"] == "500 mg" and p["freq_text"] == "twice daily"
    assert intake.quote_in_source(p["quote"], text)
    assert intake.rule_proposals("Warfarin 5 mg\nQty 30\nTake once daily", ch)[0]["freq_text"] == "once daily"


def test_ocr_letter_o_inside_numbers_is_read_as_zero_only_there():
    assert intake.fix_digits("Clarithromycin 5o0 mg") == "Clarithromycin 500 mg"
    assert intake.fix_digits("take 1OO mg; 2O mg") == "take 100 mg; 20 mg"
    assert intake.fix_digits("Oral dose; Omeprazole; TOP 10; Rx 00481") == "Oral dose; Omeprazole; TOP 10; Rx 00481"


async def test_graph_of_a_larger_regimen_with_heavy_drugs_is_fast_enough(gm):
    import time
    t, c = await circle(gm, "ravi")
    for d in ("warfarin", "fluconazole", "metformin", "atorvastatin", "clarithromycin", "amlodipine", "simvastatin", "omeprazole", "sertraline"):
        await c["ravi"].care_record("asha", d, dose_text="10 mg")
    t0 = time.time()
    g = await c["ravi"].care_graph("asha")
    assert time.time() - t0 < 3.0                                   # FalkorDB's own query timeout is 1 s per query
    assert sum(n["kind"] == "drug" for n in g["nodes"]) == 9


async def test_reminder_preview_never_uses_up_a_reminder(gm):
    t, c = await circle(gm, "ravi", "meena")
    await c["ravi"].care_record("asha", "metformin")
    await c["meena"].care_record("asha", "vitamin d")
    later = int(__import__("time").time() * 1000) + 6 * H
    for _ in range(3):                                                               # looking any number of times claims nothing
        due = await c["ravi"].care_reminders("asha", now=later)
        assert {(d["kind"], d["notify"], d["drug"], d["delivered"]) for d in due} == {("remind", "ravi", "vitamin d", False), ("remind", "meena", "metformin", False)}
    claimed = await c["ravi"].care_nudges("asha", now=later)                         # the bot's delivery still gets every one of them
    assert len(claimed) == 2
    assert all(d["delivered"] for d in await c["ravi"].care_reminders("asha", now=later))
    assert await c["ravi"].care_nudges("asha", now=later) == []


def test_quiet_hours_window_including_one_through_midnight():
    from carecircle.accounts import in_quiet
    h = lambda utc_hour: utc_hour * 3_600_000                                    # an instant at that UTC hour (day 0)
    assert in_quiet(22, 7, 0, h(23)) and in_quiet(22, 7, 0, h(3)) and not in_quiet(22, 7, 0, h(12))      # runs through midnight
    assert in_quiet(13, 15, 0, h(14)) and not in_quiet(13, 15, 0, h(15))                                   # end hour is outside
    assert in_quiet(22, 7, 330, h(17)) and not in_quiet(22, 7, 330, h(5))                                  # India: 17:00 UTC is 22:30 there
    assert not in_quiet(None, None, 0, h(3)) and not in_quiet(8, 8, 0, h(8))                                # off, or an empty window


async def test_a_reminder_held_for_quiet_hours_is_still_sent_afterwards(gm):
    t, c = await circle(gm, "ravi", "meena")
    r, mn = c["ravi"], c["meena"]
    await mn.care_ack((await mn.care_record("mum", "metformin"))["id"])
    await r.care_record("mum", "simvastatin")                                   # meena has not seen this
    later = int(__import__("time").time() * 1000) + 20 * H
    assert await r.care_nudges("mum", now=later, hold={"meena", "ravi"}) == []   # everyone quiet: nothing claimed
    sent = await r.care_nudges("mum", now=later)                                 # quiet hours over: it goes out, once
    assert sent and await r.care_nudges("mum", now=later) == []


def test_strength_read_through_ocr_punctuation_but_not_from_prose():
    ch = Checker()
    for text, want in (("Metocurine\n40:mg tablets", "40:mg"), ("selumetinib 50.mg.tablets", "50.mg"), ("Warfarin 5 mg", "5 mg"), ("Metformin 500mg", "500mg")):
        p = intake.rule_proposals(text, ch)
        assert p and p[0]["dose_text"] == want, (text, p)
    p = intake.rule_proposals("Warfarin dose 5: great care is needed", ch)                  # a bare "g" after punctuation is prose, not grams
    assert p and p[0]["dose_text"] == ""


async def test_divergence_weighs_an_enzyme_flag_by_its_medicines_not_by_parsing_its_text(gm, monkeypatch):
    """The flag names its two medicines as fields; the readable path text is for people and must not be taken apart."""
    t, c = await circle(gm, "ravi", "meena")
    await c["ravi"].care_record("mum", "warfarin", dose_text="5 mg", freq_text="at bedtime", source_type="typed", at=1)
    seen = await c["ravi"].care_record("mum", "aspirin", dose_text="75 mg", freq_text="daily", source_type="typed", at=2)
    await c["meena"].care_ack(seen["id"])                  # meena is now a carer in the circle, and has seen aspirin but not warfarin
    await c["ravi"].care_ack(seen["id"])

    async def fake_check(self, person):
        return {"direct": [], "enzyme_paths": [{"path": "free text with SUBSTRATE_OF- and -dashes- in it", "x": "clarithromycin", "y": "warfarin", "weight": 0.7}]}
    monkeypatch.setattr(type(c["ravi"]), "care_check", fake_check)
    d = await c["meena"].care_divergence("mum", now=1 + 20 * 3_600_000)
    assert [u["drug"] for u in d["carers"]["meena"]["unacknowledged"]] == ["warfarin"]
    plain = (await c["meena"].care_divergence("mum", now=1 + 20 * 3_600_000))["carers"]["meena"]["divergence"]
    async def none_check(self, person): return {"direct": [], "enzyme_paths": []}
    monkeypatch.setattr(type(c["ravi"]), "care_check", none_check)
    base = (await c["meena"].care_divergence("mum", now=1 + 20 * 3_600_000))["carers"]["meena"]["divergence"]
    assert plain > base                         # warfarin's 0.7 flag weight counted, instead of the default 0.3


def test_a_model_cannot_attach_a_dose_the_quoted_line_does_not_say(monkeypatch):
    """The quote was checked against the label, but the dose and frequency beside it were not checked against the quote: a model answer of
    '1000 mg, three times daily' on the line 'METFORMIN 500 MG TABLETS' was shown as verified."""
    text = "CITY PHARMACY\nMETFORMIN 500 MG TABLETS\nTake ONE tablet twice daily"
    monkeypatch.setattr(intake, "llm_proposals", lambda t: [
        {"llm_drug": "metformin", "dose_text": "1000 mg", "freq_text": "three times daily", "quote": "METFORMIN 500 MG TABLETS", "method": "bedrock"}])
    p = intake.propose(text, Checker())
    met = [x for x in p if x["drug_candidates"][0]["name"] == "metformin"]
    assert len(met) == 1
    assert met[0]["dose_text"].replace(" ", "").lower() == "500mg" and "1000" not in met[0]["dose_text"]     # the rule reading of the label won
    assert "three" not in met[0]["freq_text"] and met[0]["verified"]
    assert intake.quote_in_source(met[0]["quote"], text) and all(intake.field_in_quote(met[0][k], met[0]["quote"]) for k in ("dose_text",) if met[0][k])


def test_field_in_quote_is_exact_about_numbers_and_short_units():
    from carecircle.verify import field_in_quote
    assert field_in_quote("500 mg", "METFORMIN 500 MG TABLETS") and field_in_quote("5g", "Take 5 g daily") and field_in_quote("OD", "Metformin 500 mg OD")
    assert not field_in_quote("500 mg", "METFORMIN 1500 MG") and not field_in_quote("0.5 mg", "Risperidone 10.5 mg") and not field_in_quote("", "x")
    assert not field_in_quote("twice daily", "Warfarin 5 mg at bedtime")
