"""The helper remembers the conversation. Round 3 found that it stored every exchange and read none of it: 'And what about Ravi?' got a different question's
answer, 'the second one' could not be resolved, and when the rules missed, a model answered off-topic with an 'AI' badge. These tests hold the reviewer's
conditions: a reference that cannot be resolved gets a question back and never a guess, and a follow-up is refused exactly like a first question if it asks for advice."""
import pytest

from carecircle import assistant, demo


async def circle(gm, flagged=True):
    out = await demo.start(gm)
    gm._created.append(out["circle"])
    ravi, meena = gm.open(out["agents"]["ravi"], out["circle"]), gm.open(out["agents"]["meena"], out["circle"])
    if flagged:
        await ravi.care_record("asha", "clarithromycin", dose_text="500 mg", freq_text="twice daily", source_type="typed")
    return ravi, meena


async def ask(m, q, now=None):
    return await m.care_chat_ask("asha", q, now=now)


async def test_the_reviews_live_sequence_now_follows_the_thread(gm):
    ravi, meena = await circle(gm)
    a1 = await ask(ravi, "Who has not seen the latest changes?")
    assert a1["source"] == "rules" and "not yet seen" in a1["text"]
    a2 = await ask(ravi, "And what about Ravi?")                                              # same topic, a different carer
    assert a2["source"] == "rules" and a2["text"].startswith("Ravi ") and ("not yet seen" in a2["text"] or "seen every change" in a2["text"])
    assert "has recorded" not in a2["text"]                                                   # not the generic "what did Ravi add" answer it gave before


async def test_the_first_and_the_second_one_are_the_things_it_listed_and_the_list_survives_a_drill_down(gm):
    """'The first one' and 'the second one' are the items the helper itself listed, in its order (which is fixed: severity, then name), whatever the data ranks second."""
    ravi, meena = await circle(gm)
    flags = await ask(ravi, "What does the record flag?")
    shown = assistant._flags_shown(await assistant.gather(ravi, "asha", 0), "What does the record flag?")
    pair = lambda x: f"{x['drugs'][0].capitalize()} + {x['drugs'][1].capitalize()}: {x['level'].lower()}"        # noqa: E731
    direct = [x for x in shown if x["kind"] == "direct"]
    assert len(direct) >= 2 and flags["source"] == "rules" and pair(direct[0]) in flags["text"] and pair(direct[1]) in flags["text"]
    assert direct[0]["level"].lower() == "major"                                                                     # the most severe is listed first
    first = await ask(ravi, "Why is the first one flagged?")
    assert first["source"] == "rules" and pair(direct[0]) in first["text"] and pair(direct[1]) not in first["text"]   # that pair, not a generic sentence
    second = await ask(ravi, "Why is the second one flagged?")                                                     # still the list it showed, not the answer about the first
    assert second["source"] == "rules" and pair(direct[1]) in second["text"] and pair(direct[0]) not in second["text"]
    again = await ask(ravi, "What does the record flag?")
    assert again["text"] == flags["text"]                                                                             # the same list in the same order every time
    far = await ask(ravi, "And the last one?")
    assert far["source"] == "rules"


async def test_a_reference_with_nothing_to_refer_to_is_a_question_back_not_a_guess_and_not_the_model(gm, monkeypatch):
    ravi, meena = await circle(gm)
    called = []
    monkeypatch.setattr(assistant, "ask_model", lambda *a, **k: called.append(1) or "a confident but unrelated answer")
    for q in ("Why is the second one flagged?", "What about the last one?", "Did anyone give it today?", "And what about Meena?", "What about that one?"):
        out = await ask(ravi, q)
        assert out["source"] == "rules" and out["text"] and "unrelated" not in out["text"], (q, out)
        assert any(w in out["text"].lower() for w in ("which", "not sure", "only listed", "do you want to know")), (q, out["text"])
    assert called == []                                                                        # the model was never asked to guess a reference


@pytest.mark.parametrize("q", ["Should she take the second one?", "Can I give it together with the first one?", "Is it safe to take the second one with metformin?",
                               "Should I stop the last one?", "How much of the first one should she take?", "Can mum skip that one tonight?"])
async def test_advice_wording_is_refused_on_a_follow_up_whether_or_not_the_reference_resolves(gm, q):
    ravi, meena = await circle(gm)
    out = await ask(ravi, q)                                                                   # with nothing listed yet
    assert out["source"] == "refusal" and "prescriber or pharmacist" in out["text"], out
    await ask(ravi, "What does the record flag?")
    out2 = await ask(ravi, q)                                                                  # and after it listed things to refer to
    assert out2["source"] == "refusal" and "prescriber or pharmacist" in out2["text"], out2


async def test_the_conversation_is_remembered_after_a_restart_and_is_per_carer(gm):
    ravi, meena = await circle(gm)
    await ask(ravi, "Who has not seen the latest changes?")
    again = gm.open(ravi.agent, ravi.tenant)                                                 # a new handle: nothing is held in the process
    assert (await ask(again, "And what about Ravi?"))["text"].startswith("Ravi ")
    other = await ask(meena, "And what about Ravi?")                                         # Meena has asked nothing: Ravi's thread is not hers
    assert "not sure" in other["text"] or "do you want to know" in other["text"].lower()


async def test_an_old_thread_is_not_read_into_a_new_question(gm):
    ravi, meena = await circle(gm)
    t = 2_000_000_000_000
    await ask(ravi, "Who has not seen the latest changes?", now=t)
    soon = await ask(ravi, "And what about Ravi?", now=t + 3_600_000)
    late = await ask(ravi, "And what about Ravi?", now=t + 30 * 3_600_000)                  # a day and a half later
    assert soon["text"].startswith("Ravi ") and "not yet seen" in soon["text"] + "seen every"
    assert "not sure" in late["text"] or "do you want to know" in late["text"].lower()


async def test_a_question_that_stands_alone_is_answered_as_before(gm):
    ravi, meena = await circle(gm)
    for q, src in (("What medicines are on record?", "rules"), ("how does it work", "rules"), ("What can you do?", "rules")):
        out = await ask(ravi, q)
        assert out["source"] == src and "Which medicine do you mean" not in out["text"], (q, out)
