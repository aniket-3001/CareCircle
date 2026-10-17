"""The stored history log: unbroken when nothing was touched, broken in a way it can name when something was, safe under concurrent writers, and emptied with the person."""
import asyncio

import pytest

from conftest import tid


async def make(gm, name="ch"):
    t = tid(gm, name)
    await gm.grant("o", t, ("read", "write", "admin"))
    await gm.grant("c", t, ("read", "write"))
    return gm.open("o", t), gm.open("c", t)


async def test_every_write_is_logged_and_an_untouched_log_verifies(gm):
    o, c = await make(gm)
    a = await o.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed")
    b = await c.care_record("asha", "metformin", dose_text="500 mg", freq_text="twice daily", source_type="typed")
    await c.care_mark_mistake(b["id"], "typo")
    await o.care_restore_entry(b["id"])
    v = await o.care_chain_verify()
    assert v["ok"] and v["events"] == 4 and v["entries_logged"] == 2 and v["entries_not_logged"] == 0 and len(v["head"]) == 64
    kinds = [e["kind"] for e in reversed(await o.care_chain_events())]
    assert kinds == ["entry", "entry", "mistake", "restore"]
    ev = await o.care_chain_events()
    assert not any("warfarin" in str(e) or "5 mg" in str(e) for e in ev)               # the log says that, not what


async def test_an_entry_rewritten_after_it_was_logged_is_found_and_named(gm):
    o, _ = await make(gm)
    a = await o.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed")
    await o.care_record("asha", "metformin", dose_text="500 mg", source_type="typed")
    await o._q("MATCH (x:Dose {id:$i}) SET x.dose_text = '50 mg'", {"i": a["id"]}, scope="admin")
    v = await o.care_chain_verify()
    assert v["ok"] is False and v["first_problem"] == {"seq": 1, "why": "the entry was changed after it was logged"}


async def test_an_edited_or_removed_or_reordered_event_breaks_the_chain(gm):
    o, _ = await make(gm)
    for d in ("warfarin", "metformin", "amlodipine"):
        await o.care_record("asha", d, dose_text="5 mg", source_type="typed")
    assert (await o.care_chain_verify())["ok"]
    await o._q("MATCH (e:Event {seq:2}) SET e.by = 'someone-else'", scope="admin")
    assert (await o.care_chain_verify())["first_problem"]["seq"] == 2                      # an event edited
    await o._q("MATCH (e:Event {seq:2}) SET e.by = $b", {"b": "o"}, scope="admin")
    assert (await o.care_chain_verify())["ok"]                                              # put back exactly: whole again
    await o._q("MATCH (e:Event {seq:2}) DELETE e", scope="admin")
    assert "missing" in (await o.care_chain_verify())["first_problem"]["why"]              # an event removed
    o2, _ = await make(gm, "ch2")
    for d in ("warfarin", "metformin"):
        await o2.care_record("asha", d, dose_text="5 mg", source_type="typed")
    await o2._q("MATCH (e:Event {seq:2}) DELETE e", scope="admin")                          # the LAST event removed: the head no longer matches
    assert "removed" in (await o2.care_chain_verify())["first_problem"]["why"]


async def test_many_writers_at_once_extend_one_chain_without_forking_it(gm):
    o, c = await make(gm, "ch3")
    await asyncio.gather(*[(o if i % 2 else c).care_record("asha", f"drug{i}", dose_text="5 mg", source_type="typed") for i in range(12)])
    v = await o.care_chain_verify()
    assert v["ok"] and v["events"] == 12 and v["entries_logged"] == 12, v


async def test_erasing_the_person_empties_the_log_and_everything_else_about_them(gm):
    o, c = await make(gm, "ch4")
    sid = await o.care_store_source("image", "Patient: Asha\nWarfarin 5 mg")
    await o.care_record("asha", "warfarin", dose_text="5 mg", source_type="photo", quote="Warfarin 5 mg", source_ref=sid)
    await o.care_consent_set("asha", "agreed")
    await o.care_add_review("asha", "Dr R", "ask the doctor", "share1")
    await o.care_chat_ask("asha", "what is she taking?", now=None) if hasattr(o, "care_chat_ask") else None
    out = await o.care_forget_person("asha", confirm="asha")
    assert out["forgotten"]
    for label in ("Dose", "Source", "Consent", "Review", "ChatMsg", "Prevented"):
        assert (await o._q(f"MATCH (n:{label}) RETURN count(n)", scope="read"))[0][0] == 0, label
    v = await o.care_chain_verify()
    assert v["ok"] and v["events"] == 1 and (await o.care_chain_events())[0]["kind"] == "erase_person"          # one event: that it was erased


async def test_entries_from_before_the_log_can_be_adopted_and_are_then_covered(gm):
    o, c = await make(gm, "ch-adopt")
    a = await o.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed")
    await o._q("MATCH (e:Event) DETACH DELETE e", scope="admin")                                # as if the entry predates the log
    await o._q("MATCH (h:Chain) DELETE h", scope="admin")
    v = await o.care_chain_verify()
    assert v["ok"] and v["entries_not_logged"] == 1 and v["entries_adopted"] == 0
    assert (await c.care_chain_adopt())["adopted"] == 1                                         # a plain carer can do it; the event says who
    assert (await c.care_chain_adopt())["adopted"] == 0                                         # once only
    v = await o.care_chain_verify()
    assert v["ok"] and v["entries_not_logged"] == 0 and v["entries_adopted"] == 1 and v["entries_logged"] == 1
    assert [e["kind"] for e in await o.care_chain_events()] == ["adopted"] and (await o.care_chain_events())[0]["by"] == "c"
    await o._q("MATCH (x:Dose {id:$i}) SET x.dose_text = '50 mg'", {"i": a["id"]}, scope="admin")   # a later quiet change to the adopted entry
    assert (await o.care_chain_verify())["first_problem"]["why"].startswith("the entry was changed")


async def test_with_a_server_secret_the_log_still_verifies_and_older_events_keep_their_old_key(gm, monkeypatch):
    """Erased entries leave a keyed hash in the log; with the key in the same graph a backup could test guesses against it. New events use the server key;
    events written before it existed are still checked with the circle's own key."""
    t = tid(gm, "chs")
    await gm.grant("ch-a", t, ("read", "write", "admin"))
    a = gm.open("ch-a", t)
    await a.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily", source_type="typed")
    monkeypatch.setenv("CC_RECEIPT_SECRET", "k" * 40)
    e = await a.care_record("asha", "warfarin", dose_text="5 mg", freq_text="bedtime", source_type="typed")
    await a.care_forget(e["id"])
    v = await a.care_chain_verify()
    assert v["ok"] is True and v["entries_logged"] == 2
    kinds = {r[0]: r[1] for r in await a._q("MATCH (e:Event) RETURN e.seq, coalesce(e.kdf, 'graph') ORDER BY e.seq", scope="read")}
    assert kinds[1] == "graph" and set(list(kinds.values())[1:]) == {"server"}
