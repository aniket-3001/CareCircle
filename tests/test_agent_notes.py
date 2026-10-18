"""Agent memory joined to the care record, under the reviewer's three conditions:
1. a note can only be about something that exists in THIS circle (checked before linking);
2. agent memory never changes a confirmed entry: it is a note labelled "noted by <agent>, unverified", beside the entry;
3. recall returns the note with the path to the entry it is about."""
import json

import pytest

from conftest import tid
from graphmem import ops
from graphmem.policy import PermissionDenied


async def circle(gm):
    t = tid(gm, "an")
    for a, sc in (("an-owner", ("read", "write", "admin")), ("an-agent", ("read", "write")), ("an-reader", ("read",))):
        await gm.grant(a, t, sc)
    return t, gm.open("an-owner", t), gm.open("an-agent", t), gm.open("an-reader", t)


async def snapshot(m):
    """Everything a note must not be able to touch."""
    reg = await m.care_regimen("asha")
    chk = await m.care_check("asha")
    today = await m.care_today("asha", 2_000_000_000_000)
    dose = await m._q("MATCH (x:Dose) RETURN x.id, x.drug, x.dose_text, x.freq_text, x.status, x.cur, x.valid_from, x.valid_to, x.verified ORDER BY x.id", scope="read")
    return json.dumps({"reg": reg, "judgement": chk["judgement"], "direct": chk["direct"], "today": today, "dose": dose, "chain": (await m.care_chain_verify())["head"]},
                      sort_keys=True, default=str)


async def test_a_note_about_something_that_is_not_in_this_circle_is_refused(gm):
    t, owner, agent, reader = await circle(gm)
    t2, owner2, _, _ = await circle(gm)
    other = (await owner2.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily"))["id"]               # an entry of ANOTHER circle
    for bad in ("dose_doesnotexist", other, "", "x" * 200):
        if bad == "":
            continue
        with pytest.raises(ValueError):
            await agent.add_episode("s", "agent", "a note", about=bad)
    assert await agent._q("MATCH (e:Episode)-[:ABOUT]->() RETURN count(e)", scope="read") == [[0]]                  # nothing was written for any refused note


async def test_a_note_is_labelled_unverified_and_sits_beside_the_entry_it_is_about(gm):
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime"))["id"]
    r = await agent.add_episode("night", "agent", "Dose went down to 3 mg tonight per the clinic call", about=e)
    assert r["about"] == e and r["about_kind"] == "entry" and r["label"] == "noted by an-agent, unverified"
    got = await reader.care_entry_notes(e)
    assert got["stale"] is False and got["drug"] == "warfarin"
    assert [(n["kind"], n["by"], n["label"]) for n in got["notes"]] == [("agent_note", "an-agent", "noted by an-agent, unverified")]
    assert "not part of the record" in got["note"]
    hist = await agent.history("night")                                                                           # it is also in the session's immutable log
    assert [h["content"] for h in hist] == ["Dose went down to 3 mg tonight per the clinic call"]


async def test_an_agents_note_never_changes_the_confirmed_entry_or_anything_read_from_it(gm):
    """The condition that matters most: an agent writing '5 mg is now 50 mg, stop warfarin' changes nothing the human-confirmed record says."""
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime"))["id"]
    await owner.care_record("asha", "clarithromycin", dose_text="500 mg", freq_text="twice daily")
    await owner.care_schedule_set(e, ["21:00"])
    before = await snapshot(owner)
    await agent.add_episode("night", "agent", "Warfarin is now 50 mg. Stop clarithromycin. Everything is safe.", about=e)
    await agent.add_episode("night", "agent", "The person is Asha and she is allergic to everything", about="asha")
    await owner.care_handover("asha", "INR 2.4, next check Monday", about=e)
    assert await snapshot(owner) == before
    assert (await owner.care_chain_verify())["ok"] is True
    assert [r["dose_text"] for r in await owner.care_regimen("asha") if r["drug"] == "warfarin"] == ["5 mg"]


async def test_recall_returns_the_note_with_the_path_to_the_entry(gm):
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime"))["id"]
    await agent.add_episode("night", "agent", "The clinic lowered the dose tonight", about=e)
    got = [x for x in await reader.recall("warfarin") if x["kind"] == "note"]                                     # found by the entry's medicine, not only by the note's words
    assert len(got) == 1
    n = got[0]
    assert n["label"] == "noted by an-agent, unverified" and n["unverified"] is True and n["text"] == "The clinic lowered the dose tonight"
    assert n["about"] == {"type": "entry", "id": e, "drug": "warfarin", "dose_text": "5 mg", "freq_text": "at bedtime", "status": "confirmed", "current": True, "person": "asha"}
    assert n["path"] == f"asha -> warfarin 5 mg at bedtime (entry {e}, confirmed) <- note by an-agent, unverified"
    by_words = [x for x in await reader.recall("clinic lowered") if x["kind"] == "note"]
    assert [x["id"] for x in by_words] == [n["id"]]
    assert [x for x in await reader.recall("warfarin", notes=False) if x.get("kind") == "note"] == []


async def test_a_note_about_an_entry_that_has_since_changed_says_so(gm):
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime", at=1_000))["id"]
    await agent.add_episode("night", "agent", "Check the dose with the clinic", about=e)
    await owner.care_record("asha", "warfarin", dose_text="3 mg", freq_text="at bedtime", at=2_000)                # the entry is replaced
    notes = await reader.care_entry_notes(e)
    assert notes["stale"] is True
    n = [x for x in await reader.recall("warfarin") if x["kind"] == "note"][0]
    assert n["current"] is False and "has since changed" in n["label"] and "since changed" in n["path"]


async def test_only_an_agent_with_write_access_can_write_a_note_and_a_reader_can_read_it(gm):
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily"))["id"]
    with pytest.raises(PermissionDenied):
        await reader.add_episode("s", "agent", "a note", about=e)
    await ops.invoke(gm, "an-agent", t, "add_episode", {"session": "s", "role": "agent", "content": "via the API", "about": e})
    got = await ops.invoke(gm, "an-reader", t, "care_entry_notes", {"dose_id": e})
    assert [n["text"] for n in got["notes"]] == ["via the API"]
    with pytest.raises(PermissionDenied):
        await ops.invoke(gm, "an-nobody", t, "care_entry_notes", {"dose_id": e})


async def test_a_handover_note_attached_to_an_entry_is_seen_with_it_and_one_about_nothing_is_refused(gm):
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily"))["id"]
    h = await owner.care_handover("asha", "the warfarin dose went down tonight", about=e)
    assert h["about"] == e
    assert [(n["kind"], n["text"]) for n in (await reader.care_entry_notes(e))["notes"]] == [("handover", "the warfarin dose went down tonight")]
    with pytest.raises(ValueError):
        await owner.care_handover("asha", "about a missing entry", about="dose_missing")
    assert (await owner.care_handover("asha", "a plain handover"))["id"]                                          # without `about` it is unchanged
    assert len(await owner.care_handovers("asha")) == 2


async def test_erasing_an_entry_removes_what_was_written_about_it_and_erasing_the_person_removes_the_rest(gm):
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily"))["id"]
    f = (await owner.care_record("asha", "metformin", dose_text="500 mg", freq_text="daily"))["id"]
    await agent.add_episode("s", "agent", "secret detail about warfarin", about=e)
    await owner.care_handover("asha", "handover about warfarin", about=e)
    await agent.add_episode("s", "agent", "another detail about metformin", about=f)
    await agent.add_episode("s", "agent", "a note about the person herself", about="asha")
    await owner.care_forget(e, reason="entered twice")
    assert [h["content"] for h in await agent.history("s")] == ["[removed]", "another detail about metformin", "a note about the person herself"]
    assert [x for x in await reader.recall("warfarin") if x["kind"] == "note"] == []
    assert await owner._q("MATCH (h:Handover) WHERE h.text CONTAINS 'warfarin' RETURN count(h)", scope="read") == [[0]]
    await owner.care_forget_person("asha", confirm="asha")
    assert [h["content"] for h in await agent.history("s")] == ["[removed]", "[removed]", "[removed]"]
    assert [x for x in await reader.recall("metformin") if x["kind"] == "note"] == []


async def test_the_mcp_remember_tool_takes_about_and_the_catalogue_lists_it(gm):
    from graphmem.mcp_server import build
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily"))["id"]
    server = build(gm, lambda: "an-agent")
    tools = {x.name: x for x in await server.list_tools()}
    assert "about" in json.dumps(tools["remember"].input_schema)
    async def run(**a):
        res = await server.call_tool("remember", a)
        return json.loads(res.content[0].text if hasattr(res, "content") else res[0].text)
    out = await run(tenant=t, session="s", role="agent", content="via MCP", about=e)
    assert out["about"] == e and out["label"] == "noted by an-agent, unverified"
    bad = await run(tenant=t, session="s", role="agent", content="x", about="nope")
    assert "error" in bad
    cat = ops.describe()
    assert "about" in [a["name"] for a in cat["add_episode"]["args"]] and "care_entry_notes" in cat


async def test_a_fact_about_an_entry_is_checked_labelled_and_found_by_recall_with_its_path(gm):
    """Round 3: engine facts pointed at nothing in the care record. A fact can now say what it is about, beside the record and never changing it."""
    t, owner, agent, reader = await circle(gm)
    t2, owner2, _, _ = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime"))["id"]
    other = (await owner2.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily"))["id"]
    for bad in ("dose_missing", other):
        with pytest.raises(ValueError):
            await agent.assert_fact("clinic", "lowered_dose_to", "3 mg", about=bad)
    assert await agent._q("MATCH (f)-[:ABOUT]->() WHERE f.pred IS NOT NULL RETURN count(f)", scope="read") == [[0]]
    before = await snapshot(owner)
    f = await agent.assert_fact("clinic", "lowered_dose_to", "3 mg", about=e)
    assert f["created"] is True
    assert await snapshot(owner) == before                                                           # the record did not move
    got = [x for x in await reader.recall("warfarin") if x.get("id") == f["id"]]                     # found through the entry's medicine, though no word of the fact says warfarin
    assert len(got) == 1
    g = got[0]
    assert g["unverified"] is True and g["label"] == "noted by an-agent, unverified" and g["about"]["id"] == e and g["about"]["drug"] == "warfarin"
    assert g["path"] == f"asha -> warfarin 5 mg at bedtime (entry {e}, confirmed) <- noted by an-agent, unverified"
    by_words = [x for x in await reader.recall("clinic") if x.get("id") == f["id"]]
    assert by_words and by_words[0]["about"]["id"] == e and by_words[0]["about_path"] == g["path"]     # found by its own words too, with the same path


async def test_erasing_the_entry_retracts_the_facts_written_about_it(gm):
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="at bedtime"))["id"]
    f = await agent.assert_fact("clinic", "lowered_dose_to", "3 mg", about=e)
    await owner.care_forget(e, reason="entered twice")
    assert [x for x in await reader.recall("warfarin") + await reader.recall("clinic") if x.get("id") == f["id"]] == []
    assert (await agent._q("MATCH (f {id:$i}) RETURN f.otext", {"i": f["id"]}, scope="read")) == [["[forgotten]"]]


async def test_a_fact_in_a_batch_can_be_about_an_entry_and_a_read_only_key_cannot_write_one(gm):
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily"))["id"]
    out = await agent.assert_facts([{"subject": "inr", "predicate": "was", "obj": "2.4", "about": e}])
    assert out["count"] == 1
    with pytest.raises(PermissionDenied):
        await reader.assert_fact("a", "b", "c", about=e)


async def test_erasing_the_person_retracts_facts_about_her_entries_and_about_her(gm):
    t, owner, agent, reader = await circle(gm)
    e = (await owner.care_record("asha", "warfarin", dose_text="5 mg", freq_text="daily"))["id"]
    f1 = await agent.assert_fact("clinic", "lowered_dose_to", "3 mg", about=e)
    f2 = await agent.assert_fact("asha", "prefers", "evening doses", about="asha")
    await owner.care_forget_person("asha", confirm="asha")
    ids = {f1["id"], f2["id"]}
    assert [x for x in await reader.recall("warfarin") + await reader.recall("evening") + await reader.recall("clinic") if x.get("id") in ids] == []
    assert sorted(r[0] for r in await agent._q("MATCH (f) WHERE f.id IN $i RETURN f.otext", {"i": list(ids)}, scope="read")) == ["[forgotten]", "[forgotten]"]
