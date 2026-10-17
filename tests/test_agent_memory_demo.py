"""The Track 2 demo, run against the engine in CI: an agent remembers across sessions and another agent, with its own key, finds the note with its path and holds
off until the carer it affects has seen the change. The same story runs over real MCP connections with `scripts/agent_memory_demo.py`."""
import importlib.util
import pathlib

from conftest import tid
from graphmem import ops

SPEC = importlib.util.spec_from_file_location("agent_memory_demo", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "agent_memory_demo.py")
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


async def setup(gm):
    t = tid(gm, "amd")
    for a, sc in (("ravi", ("read", "write", "admin")), ("meena", ("read", "write", "admin")), ("night-agent", ("read", "write")), ("morning-agent", ("read", "write"))):
        await gm.grant(a, t, sc)

    async def human(who, op, **args):
        return await ops.invoke(gm, who, t, op, args)
    return t, demo.LocalAgent(gm, "night-agent", t), demo.LocalAgent(gm, "morning-agent", t), human


async def test_an_agent_remembers_across_sessions_and_another_holds_off_until_the_carer_has_seen_it(gm):
    t, night, morning, human = await setup(gm)
    lines = []
    ev = await demo.story(night, morning, human, say=lines.append)
    assert ev["recalled"] and ev["recalled"][0]["label"] == "noted by night-agent, unverified"                      # remembered, with who wrote it
    assert ev["recalled"][0]["path"].startswith("asha -> warfarin 3 mg at bedtime (entry ") and ev["recalled"][0]["path"].endswith("<- note by night-agent, unverified")
    assert "INR 2.4" in ev["recalled"][0]["text"]
    assert ev["without"] == []                                                                                      # the same question without the memory finds nothing
    assert ev["held"] == ["Meena"] and ev["notes_while_held"] == ["agent_note"]                                      # held off: no handover written while Meena was behind
    assert ev["still_held"] == []
    assert [k for k, _ in ev["final_notes"]] == ["agent_note", "handover"]                                          # after she saw it, it proceeded and attached its note
    assert any("HOLDS OFF" in l for l in lines) and any("proceeds" in l for l in lines)


async def test_the_second_agent_has_its_own_key_and_cannot_do_what_its_scope_does_not_allow(gm):
    t, night, morning, human = await setup(gm)
    await demo.story(night, morning, human, say=lambda s: None)
    # an agent with read access only can recall the note and see who is behind, but cannot write one
    await gm.grant("reader-agent", t, ("read",))
    reader = demo.LocalAgent(gm, "reader-agent", t)
    assert [x for x in await reader.recall("warfarin") if x.get("kind") == "note"]
    import pytest
    from graphmem.policy import PermissionDenied
    with pytest.raises(PermissionDenied):
        await reader.remember("s", "agent", "I would like to add a note", about=(await human("ravi", "care_regimen", person="asha"))[0]["id"])


async def test_the_notes_changed_nothing_in_the_record(gm):
    t, night, morning, human = await setup(gm)
    await demo.story(night, morning, human, say=lambda s: None)
    reg = {r["drug"]: r["dose_text"] for r in await human("ravi", "care_regimen", person="asha")}
    assert reg == {"warfarin": "3 mg"}                                                                              # only the night agent's own recorded change; no note edited anything
    assert (await human("ravi", "care_chain_verify"))["ok"] is True
