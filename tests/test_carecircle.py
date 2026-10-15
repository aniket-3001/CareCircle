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
