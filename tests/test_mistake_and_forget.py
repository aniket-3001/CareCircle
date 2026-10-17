"""Erasing an entry for good is the owner's call; any carer can mark an entry as entered by mistake, which keeps it in the history and can be undone."""
import pytest

from conftest import tid
from graphmem.policy import PermissionDenied


async def circle(gm):
    t = tid(gm, "mk")
    await gm.grant("owner-mk", t, ("read", "write", "admin"))
    for c in ("carer-a", "carer-b"):
        await gm.grant(c, t, ("read", "write"))
    return t, gm.open("owner-mk", t), gm.open("carer-a", t), gm.open("carer-b", t)


async def regimen(m):
    return {r["drug"]: r["dose_text"] for r in await m.care_regimen("asha")}


async def test_only_the_owner_can_erase_an_entry_for_good(gm):
    t, owner, a, b = await circle(gm)
    e = await a.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed")
    with pytest.raises(PermissionDenied):
        await b.care_forget(e["id"], reason="not mine")
    with pytest.raises(PermissionDenied):
        await b.care_forget_person("asha", confirm="asha")
    assert (await regimen(b)) == {"warfarin": "5 mg"}                       # nothing was erased
    out = await owner.care_forget(e["id"], reason="entered twice")
    assert out["forgotten"] and await regimen(owner) == {}


async def test_a_carer_marks_an_entry_as_a_mistake_and_the_history_keeps_it(gm):
    t, owner, a, b = await circle(gm)
    first = await a.care_record("asha", "warfarin", dose_text="4 mg", freq_text="bedtime", source_type="typed", at=1_000_000)
    typo = await a.care_record("asha", "warfarin", dose_text="40 mg", freq_text="bedtime", source_type="typed", at=2_000_000)
    assert await regimen(b) == {"warfarin": "40 mg"}
    out = await b.care_mark_mistake(typo["id"], reason="should have been 4")             # a carer who did not write it
    assert out["status"] == "mistake"
    assert await regimen(b) == {"warfarin": "4 mg"}                                    # the earlier entry stands again
    tl = " | ".join(e["text"] for e in await b.care_timeline("asha"))
    assert "40 mg" in tl and "marked as entered by mistake" in tl and "should have been 4" in tl      # nothing is hidden or rewritten
    assert first["id"] != typo["id"]
    with pytest.raises(KeyError):
        await b.care_mark_mistake(typo["id"])                                              # already marked
    with pytest.raises(KeyError):
        await b.care_mark_mistake("dose_nope")


async def test_a_mark_can_be_undone_by_whoever_made_it_or_the_owner_but_not_by_another_carer(gm):
    t, owner, a, b = await circle(gm)
    e = await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily", source_type="typed")
    await a.care_mark_mistake(e["id"])
    assert await regimen(a) == {}
    with pytest.raises(PermissionDenied):
        await b.care_restore_entry(e["id"])                                                # a third carer cannot override
    await a.care_restore_entry(e["id"])                                                   # the one who marked it can
    assert await regimen(a) == {"metformin": "500 mg"}
    await b.care_mark_mistake(e["id"])
    await owner.care_restore_entry(e["id"])                                               # the owner can undo anyone's mark
    assert await regimen(a) == {"metformin": "500 mg"}
    assert "mistake" not in " ".join(x["text"] for x in await a.care_timeline("asha"))     # restored: the history no longer calls it one


async def test_a_receipt_is_keyed_so_a_guessed_line_cannot_be_checked_by_hashing_alone(gm):
    import hashlib
    import json
    t, owner, a, b = await circle(gm)
    e = await a.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed", at=1_000_000)
    out = await owner.care_forget(e["id"], reason="entered twice")
    guess = hashlib.sha256(json.dumps(["warfarin", "5 mg", "bedtime", "", "carer-a", 1_000_000], sort_keys=True).encode()).hexdigest()
    assert out["sha256"] != guess                                                        # the old unkeyed form no longer matches a guess
    same = await owner.care_receipt_check(out["receipt"], drug="warfarin", dose_text="5 mg", freq_text="bedtime", quote="", by="carer-a", at=1_000_000)
    other = await owner.care_receipt_check(out["receipt"], drug="warfarin", dose_text="50 mg", freq_text="bedtime", quote="", by="carer-a", at=1_000_000)
    assert same["matches"] is True and other["matches"] is False
    with pytest.raises(PermissionDenied):
        await b.care_receipt_check(out["receipt"], drug="warfarin")                      # only the owner may test guesses


SECRET = "s" * 40


async def test_with_a_server_secret_the_receipt_key_is_not_in_the_graph_at_all(gm, monkeypatch):
    """The per-circle key lived in the same graph as the receipts, so a backup of the graph held both and a guessed line could be tried offline. With a server
    secret the key is derived from it and the circle's id, and nothing key-like is written to the graph."""
    monkeypatch.setenv("CC_RECEIPT_SECRET", SECRET)
    t, owner, a, b = await circle(gm)
    e = await a.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed", at=1_000_000)
    out = await owner.care_forget(e["id"], reason="entered twice")
    assert (await owner._q("MATCH (s:Setting {key:'receipt_key'}) RETURN count(s)", scope="read"))[0][0] == 0
    assert (await owner.care_receipts())[0]["keyed_by"] == "server"
    args = dict(drug="warfarin", dose_text="5 mg", freq_text="bedtime", quote="", by="carer-a", at=1_000_000)
    assert (await owner.care_receipt_check(out["receipt"], **args))["matches"] is True
    monkeypatch.setenv("CC_RECEIPT_SECRET", "t" * 40)                                  # a holder of the graph who guesses another secret gets nothing
    assert (await owner.care_receipt_check(out["receipt"], **args))["matches"] is False
    monkeypatch.delenv("CC_RECEIPT_SECRET")
    with pytest.raises(ValueError):                                                    # without the secret the server cannot even answer
        await owner.care_receipt_check(out["receipt"], **args)


async def test_a_receipt_made_before_the_secret_existed_still_checks_and_the_same_line_differs_per_circle(gm, monkeypatch):
    t, owner, a, b = await circle(gm)
    e = await a.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed", at=1_000_000)
    old = await owner.care_forget(e["id"])
    monkeypatch.setenv("CC_RECEIPT_SECRET", SECRET)
    args = dict(drug="warfarin", dose_text="5 mg", freq_text="bedtime", quote="", by="carer-a", at=1_000_000)
    assert (await owner.care_receipt_check(old["receipt"], **args))["matches"] is True and (await owner.care_receipts())[0]["keyed_by"] == "graph"
    t2, owner2, a2, _ = await circle(gm)
    e2 = await a2.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed", at=1_000_000)
    new2 = await owner2.care_forget(e2["id"])
    e3 = await a.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed", at=1_000_000)
    new1 = await owner.care_forget(e3["id"])
    assert new1["sha256"] != new2["sha256"]                                            # same line, two circles: two different keys


async def test_a_short_receipt_secret_is_refused(gm, monkeypatch):
    monkeypatch.setenv("CC_RECEIPT_SECRET", "short")
    t, owner, a, b = await circle(gm)
    with pytest.raises(ValueError):                                                    # the log needs the key on the first write, so a bad secret is never used quietly
        await a.care_record("asha", "warfarin", dose_text="5 mg", source_type="typed", at=1_000)
    from graphmem.api import create_app
    with pytest.raises(ValueError):                                                    # and the server will not start with it
        async with create_app(gm, admin_key="x").router.lifespan_context(None):
            pass
