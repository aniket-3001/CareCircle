"""The LlamaIndex adapter (integrations/llamaindex_tools.py), against a real server over a real socket. Skipped when llama-index-core is not installed."""
import asyncio
import json

import pytest

pytest.importorskip("llama_index.core")

from conftest import tid  # noqa: E402
from integrations.llamaindex_tools import graphmem_tools  # noqa: E402
from test_langchain_tools import key_for, serving  # noqa: E402


async def test_every_general_operation_becomes_a_tool_that_really_calls_the_server(gm):
    t = tid(gm, "li")
    async with serving() as url:
        key = await key_for(url, "tt-li-a", t)
        tools = {x.metadata.name: x for x in await asyncio.to_thread(graphmem_tools, url, key, t)}
        assert {"add_episode", "history", "recall", "graph_path", "graph_influence", "graph_communities"} <= set(tools)
        assert not any(n.startswith("care_") for n in tools)

        def use():
            tools["assert_fact"].call(subject="ann", predicate="likes", obj="tea")
            tools["assert_fact"].call(subject="tea", predicate="grown_in", obj="assam")
            tools["add_episode"].call(session="s", role="user", content="the ferry leaves at nine")
            return (json.loads(tools["history"].call(session="s").content), json.loads(tools["recall"].call(query="tea").content),
                    json.loads(tools["graph_path"].call(source="ann", target="assam").content),
                    json.loads(tools["graph_influence"].call(metric="betweenness", label="Entity", top=2).content))

        hist, facts, path, infl = await asyncio.to_thread(use)
        assert "ferry leaves at nine" in json.dumps(hist) and facts
        assert path["found"] and path["length"] == 4 and path["path"][0]["ref"] == "ann" and path["path"][-1]["ref"] == "assam"
        assert infl["metric"] == "betweenness" and len(infl["rows"]) == 2
        schema = json.loads((await tools["graph_schema"].acall()).content)                  # the async path
        assert any(n["label"] == "Fact" for n in schema["nodes"])


async def test_refusals_come_back_as_text_and_the_schema_a_model_sees_is_right(gm):
    t = tid(gm, "li-err")
    async with serving() as url:
        w = await key_for(url, "tt-li-w", t)
        r = await key_for(url, "tt-li-r", t, ("read",))
        writer = {x.metadata.name: x for x in await asyncio.to_thread(graphmem_tools, url, w, t)}
        reader = {x.metadata.name: x for x in await asyncio.to_thread(graphmem_tools, url, r, t)}
        bad = await asyncio.to_thread(lambda: writer["graph_influence"].call(metric="degree").content)
        denied = await asyncio.to_thread(lambda: reader["add_episode"].call(session="s", role="user", content="x").content)
        assert bad.startswith("error 422") and "betweenness" in bad
        assert denied.startswith("error 403") and "write" in denied
        spec = writer["graph_path"].metadata.to_openai_tool()["function"]
        assert spec["name"] == "graph_path" and set(spec["parameters"]["required"]) == {"source", "target"}
        assert "max_hops" in spec["parameters"]["properties"] and "read access" in spec["description"]


async def test_choosing_operations_and_a_bad_key(gm):
    t = tid(gm, "li-pick")
    async with serving() as url:
        key = await key_for(url, "tt-li-p", t)
        only = await asyncio.to_thread(graphmem_tools, url, key, t, ["graph_path", "recall"])
        assert [x.metadata.name for x in only] == ["graph_path", "recall"]
        with pytest.raises(KeyError, match="no_such_op"):
            await asyncio.to_thread(graphmem_tools, url, key, t, ["no_such_op"])
        with pytest.raises(PermissionError):
            await asyncio.to_thread(graphmem_tools, url, "gm_wrong", t)
        care = await asyncio.to_thread(graphmem_tools, url, key, t, ["care_people"])
        assert care[0].metadata.name == "care_people"
