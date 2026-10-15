from carecircle import dose
from conftest import tid


def test_parse_is_integer_exact():
    assert dose.parse("500 mg") == {"micro": 500_000, "unit": "mg", "family": "mass"}
    assert dose.parse("0.5 mg")["micro"] == 500 and dose.parse("500 mcg")["micro"] == 500 and dose.parse("0,25 mg")["micro"] == 250
    assert dose.parse("1000 IU")["family"] == "activity" and dose.parse("take it daily") is None
    assert dose.parse("0.1 mg")["micro"] == 100                                   # no float error: 0.1 is not 0.1000000000000000055


def test_slips_are_flagged_never_decided():
    assert "unit changed" in dose.slip("5 mg", "5 mcg")
    assert "1000 times more" in dose.slip("0.5 mg", "500 mg") or "1000 times more" in dose.slip("0.5 mg", "500 mg")
    assert "10 times less" in dose.slip("50 mg", "5 mg")
    assert dose.slip("5 mg", "10 mg") is None and dose.slip("500 mg", "500 mg") is None and dose.slip("", "5 mg") is None


async def test_record_returns_the_prompt_and_still_records(gm):
    t = tid(gm, "ds")
    await gm.grant("ravi", t, ("read", "write", "admin"))
    m = gm.open("ravi", t)
    await m.care_record("asha", "levothyroxine", dose_text="75 mcg")
    r = await m.care_record("asha", "levothyroxine", dose_text="75 mg")
    assert r["status"] == "confirmed" and "unit changed" in r["warning"]            # recorded as typed; a person is told to look again
    assert (await m.care_regimen("asha"))[0]["dose_text"] == "75 mg"
    assert "warning" not in await m.care_record("asha", "metformin", dose_text="500 mg")
