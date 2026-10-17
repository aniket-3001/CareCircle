"""A LangGraph agent whose conversation state is checkpointed in FalkorDB (langchain-falkordb's FalkorDBSaver) while its long-term memory is our graph,
reached through the LangChain tools: two different kinds of memory in one FalkorDB, side by side, and still there for the next session. No model is
needed: the graph's nodes are plain functions that call the tools. Skipped when langgraph or langchain-falkordb is not installed."""
import asyncio
import json
import operator
import os
import uuid
from typing import Annotated, TypedDict

import pytest

pytest.importorskip("langgraph")
pytest.importorskip("langchain_falkordb")

import falkordb  # noqa: E402
from langchain_falkordb.checkpoint import FalkorDBSaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from conftest import tid  # noqa: E402
from integrations.langchain_tools import graphmem_tools  # noqa: E402
from test_langchain_tools import key_for, serving  # noqa: E402


class State(TypedDict):
    steps: Annotated[list, operator.add]          # grows with every node, across runs of the same thread
    path_length: int


def build(tools):
    """learn two facts, then ask the graph how the first and last are connected."""
    def learn(state: State):
        tools["assert_fact"].invoke({"subject": "ann", "predicate": "likes", "obj": "tea"})
        tools["assert_fact"].invoke({"subject": "tea", "predicate": "grown_in", "obj": "assam"})
        return {"steps": ["learned two facts"]}

    def connect(state: State):
        path = json.loads(tools["graph_path"].invoke({"source": "ann", "target": "assam"}))
        return {"steps": [f"path found: {path['found']}"], "path_length": path["length"]}

    g = StateGraph(State)
    g.add_node("learn", learn)
    g.add_node("connect", connect)
    g.add_edge(START, "learn")
    g.add_edge("learn", "connect")
    g.add_edge("connect", END)
    return g


async def test_checkpoints_live_in_falkordb_and_the_next_session_finds_them(gm):
    t = tid(gm, "lg")
    ckpt = "tt_lg_" + uuid.uuid4().hex[:8]                                        # the checkpoint graph, named apart from every graph of ours
    port = int(os.getenv("FALKORDB_PORT", "6379"))                               # the database the suite is pointed at (the 6.0.2 compatibility run uses another port)
    raw = falkordb.FalkorDB(port=port)
    try:
        async with serving() as url:
            key = await key_for(url, "tt-lg-a", t)
            tools = {x.name: x for x in await asyncio.to_thread(graphmem_tools, url, key, t)}
            config = {"configurable": {"thread_id": "session-1"}}

            def first_session():
                app = build(tools).compile(checkpointer=FalkorDBSaver(database=ckpt, port=port))
                return app.invoke({"steps": [], "path_length": -1}, config)

            out = await asyncio.to_thread(first_session)
            assert out["path_length"] == 4 and out["steps"] == ["learned two facts", "path found: True"]

            def next_session():                                                      # a new saver and a new compiled graph: nothing shared with the first but the database
                app = build(tools).compile(checkpointer=FalkorDBSaver(database=ckpt, port=port))
                snap = app.get_state(config)
                history = list(app.get_state_history(config))
                again = app.invoke({"steps": ["asked again"], "path_length": -1}, config)
                other = app.get_state({"configurable": {"thread_id": "session-2"}})
                return snap, history, again, other

            snap, history, again, other = await asyncio.to_thread(next_session)
            assert snap.values["path_length"] == 4 and snap.values["steps"] == ["learned two facts", "path found: True"]       # found where the first session left it
            assert len(history) >= 3                                                  # a checkpoint per step, not only the last
            assert again["steps"][:2] == ["learned two facts", "path found: True"] and again["steps"][2] == "asked again"       # the same thread carries on
            assert other.values == {} and not other.next                              # another thread is untouched

        names = set(await asyncio.to_thread(raw.list_graphs))
        assert ckpt in names and f"mem__{t}" in names                                 # two kinds of memory, one FalkorDB
        mem_nodes = raw.select_graph(f"mem__{t}").ro_query("MATCH (n) WHERE NOT n:Schema RETURN count(n)").result_set[0][0]
        assert mem_nodes > 0
        ck_nodes = raw.select_graph(ckpt).ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
        assert ck_nodes >= 3
        labels = {r[0] for r in raw.select_graph(ckpt).ro_query("MATCH (n) RETURN DISTINCT labels(n)[0]").result_set}
        assert not labels & {"Episode", "Fact", "Entity", "Dose", "Person"}            # the saver's records never mix into a memory graph
        assert not any(l in ("Checkpoint",) for l in {r[0] for r in raw.select_graph(f"mem__{t}").ro_query("MATCH (n) RETURN DISTINCT labels(n)[0]").result_set})
    finally:
        try:
            raw.select_graph(ckpt).delete()
        except Exception:
            pass
