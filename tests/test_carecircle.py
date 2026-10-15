import math, pytest
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
from conftest import tid

H = 3_600_000


async def circle(gm, *carers):
    t = tid(gm, "cc")
    for c in ("amma", *carers):
        await gm.grant(c, t, ("read", "write"))
    return t, {c: gm.open(c, t) for c in carers}


async def test_supersession_quote_verify_and_regimen(gm):
    t, c = await circle(gm, "ravi", "meena")
    m = c["ravi"]
    a = await m.care_record("mum", "warfarin", dose_text="5 mg", freq_text="at bedtime", source_type="photo",
                            quote="Warfarin Sodium 5mg", source_text="CITYPHARMACYRx48213 WarfarinSodium5mgtablets Qty30")
    assert a["status"] == "confirmed" and a["verified"]
    b = await m.care_record("mum", "warfarin", dose_text="3 mg", source_type="photo", quote="Warfarin 3 mg",
                            source_text="something else entirely")
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
    res = await asyncio.gather(*[c["ravi" if i % 2 else "meena"].care_give("mum", "metformin", "2026-10-16 08:00") for i in range(10)])
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
    data = open(reference.DATA.parent.parent.parent / "data" / "checks" / "label.png", "rb").read()
    src = intake.read_source(data, "label.png", "image/png")
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
    def download(self, fid): return open(reference.DATA.parent.parent.parent / "data" / "checks" / "label.png", "rb").read(), "p.png"


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
