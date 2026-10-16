"""The LangChain adapter (integrations/langchain_tools.py), against a real server over a real socket. Skipped when langchain-core is not installed."""
import asyncio
import contextlib
import json
import socket
import threading

import httpx
import pytest

pytest.importorskip("langchain_core")

from langchain_core.utils.function_calling import convert_to_openai_tool  # noqa: E402

from conftest import tid  # noqa: E402
from graphmem.api import create_app  # noqa: E402
from integrations.langchain_tools import graphmem_tools  # noqa: E402

ADMIN = {"Authorization": "Bearer admin-secret"}


@contextlib.asynccontextmanager
async def serving():
    import uvicorn
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(None, admin_key="admin-secret", rate_per_minute=100000)          # its own database client, in the server's own loop
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.1)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


async def key_for(url, name, tenant, scopes=("read", "write")):
    async with httpx.AsyncClient(base_url=url) as c:
        k = (await c.post("/admin/agents", json={"agent": name}, headers=ADMIN)).json()["api_key"]
        await c.post("/admin/grants", json={"agent": name, "tenant": tenant, "scopes": list(scopes)}, headers=ADMIN)
    return k


async def test_every_general_operation_becomes_a_tool_that_really_calls_the_server(gm):
    t = tid(gm, "lc")
    async with serving() as url:
        key = await key_for(url, "tt-lc-a", t)
        tools = {x.name: x for x in await asyncio.to_thread(graphmem_tools, url, key, t)}
        assert {"add_episode", "history", "recall", "graph_path", "graph_influence", "graph_communities"} <= set(tools)
        assert not any(n.startswith("care_") for n in tools)

        def use():
            tools["assert_fact"].invoke({"subject": "ann", "predicate": "likes", "obj": "tea"})
            tools["assert_fact"].invoke({"subject": "tea", "predicate": "grown_in", "obj": "assam"})
            tools["add_episode"].invoke({"session": "s", "role": "user", "content": "the ferry leaves at nine"})
            hist = json.loads(tools["history"].invoke({"session": "s"}))
            facts = json.loads(tools["recall"].invoke({"query": "tea"}))
            path = json.loads(tools["graph_path"].invoke({"source": "ann", "target": "assam"}))
            infl = json.loads(tools["graph_influence"].invoke({"metric": "pagerank", "top": 2}))
            return hist, facts, path, infl

        hist, facts, path, infl = await asyncio.to_thread(use)
        assert "ferry leaves at nine" in json.dumps(hist) and facts and facts[0]["object"] in ("tea", "assam")
        assert path["found"] and path["length"] == 4                                      # ann, a fact, tea, a fact, assam: a fact is a node between its two entities
        assert [n["label"] for n in path["path"]] == ["Entity", "Fact", "Entity", "Fact", "Entity"]
        assert path["path"][0]["ref"] == "ann" and path["path"][-1]["ref"] == "assam"
        assert len(infl["rows"]) == 2
        # the way an agent framework calls a tool: with a tool-call message, getting a ToolMessage back
        msg = await asyncio.to_thread(tools["graph_path"].invoke, {"name": "graph_path", "args": {"source": "ann", "target": "tea"}, "id": "call-1", "type": "tool_call"})
        assert msg.tool_call_id == "call-1" and json.loads(msg.content)["length"] == 2 and msg.status != "error"
        # the async path too
        schema = json.loads(await tools["graph_schema"].ainvoke({}))
        assert any(n["label"] == "Fact" for n in schema["nodes"])


async def test_refusals_come_back_as_text_for_the_model_not_as_exceptions(gm):
    t = tid(gm, "lc-err")
    async with serving() as url:
        w = await key_for(url, "tt-lc-w", t)
        r = await key_for(url, "tt-lc-r", t, ("read",))
        writer = {x.name: x for x in await asyncio.to_thread(graphmem_tools, url, w, t)}
        reader = {x.name: x for x in await asyncio.to_thread(graphmem_tools, url, r, t)}

        def use():
            return (writer["graph_influence"].invoke({"metric": "degree"}),
                    reader["add_episode"].invoke({"session": "s", "role": "user", "content": "x"}),
                    writer["history"].invoke({"session": "never-written"}))

        bad, denied, empty = await asyncio.to_thread(use)
        assert bad.startswith("error 422") and "pagerank" in bad
        assert denied.startswith("error 403") and "write" in denied
        assert json.loads(empty) is not None
        with pytest.raises(Exception):                                                   # a missing required argument is the framework's own validation
            writer["graph_path"].invoke({"source": "a"})


async def test_choosing_operations_a_bad_key_and_the_schema_a_model_sees(gm):
    t = tid(gm, "lc-pick")
    async with serving() as url:
        key = await key_for(url, "tt-lc-p", t)
        only = await asyncio.to_thread(graphmem_tools, url, key, t, ["graph_path", "recall"])
        assert [x.name for x in only] == ["graph_path", "recall"]
        spec = convert_to_openai_tool(only[0])["function"]
        assert spec["name"] == "graph_path" and set(spec["parameters"]["required"]) == {"source", "target"}
        assert "max_hops" in spec["parameters"]["properties"] and "read access" in spec["description"]
        with pytest.raises(KeyError, match="no_such_op"):
            await asyncio.to_thread(graphmem_tools, url, key, t, ["no_such_op"])
        with pytest.raises(PermissionError):
            await asyncio.to_thread(graphmem_tools, url, "gm_wrong", t)
        care = await asyncio.to_thread(graphmem_tools, url, key, t, ["care_people"])
        assert care[0].name == "care_people"                                              # the product's own operations are there when asked for
