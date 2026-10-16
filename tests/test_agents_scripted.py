"""Real agent frameworks driving our tools, with a scripted stand-in for the language model, so it is deterministic and free and can run in CI.

What this proves: the LangGraph and LlamaIndex agent loops can take our tool schemas, call a tool the way a model does (a tool-call message with arguments),
get the real server's answer back as a tool result, and continue to an answer. What it does not prove: that a real model chooses well. `scripts/agent_demo.py`
(run by hand, Bedrock Nova Pro) covers that, and the README says so.

The script is a list of steps; each step sees the messages so far and returns the model's next move, so a later call can use what an earlier tool returned."""
import asyncio
import json
import uuid

import pytest

from conftest import tid
from test_langchain_tools import key_for, serving

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph.prebuilt")
from integrations.langchain_tools import graphmem_tools as lc_tools  # noqa: E402

ASK = "How is ann connected to assam, and what does the schema hold?"


async def seed(url, key, tenant):
    import httpx
    async with httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {key}"}) as c:
        for s, p, o in (("ann", "likes", "tea"), ("tea", "grown_in", "assam")):
            r = await c.post(f"/v1/tenants/{tenant}/assert_fact", json={"subject": s, "predicate": p, "obj": o})
            assert r.status_code == 200, r.text


# ----------------------------------------------------------------------------------------------------------------------------- LangGraph
def _scripted_chat_model(steps):
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class Scripted(BaseChatModel):
        calls: int = 0
        seen: list = []

        @property
        def _llm_type(self):
            return "scripted"

        def bind_tools(self, tools, **kw):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kw):
            self.seen.append(list(messages))
            move = steps[min(self.calls, len(steps) - 1)](messages)
            self.calls += 1
            msg = AIMessage(content=move.get("text", ""), tool_calls=[{"name": n, "args": a, "id": f"c{self.calls}-{i}", "type": "tool_call"} for i, (n, a) in enumerate(move.get("calls", []))])
            return ChatResult(generations=[ChatGeneration(message=msg)])

    return Scripted()


def _last_tool_text(messages, name):
    for m in reversed(messages):
        if getattr(m, "type", "") == "tool" and getattr(m, "name", "") == name:
            return m.content
    return None


async def test_langgraph_agent_loop_uses_the_tools_and_answers_from_what_they_return(gm):
    from langgraph.prebuilt import create_react_agent
    t = tid(gm, "ag-lg")
    async with serving() as url:
        key = await key_for(url, f"tt-aglg-{uuid.uuid4().hex[:5]}", t)
        await seed(url, key, t)
        tools = await asyncio.to_thread(lc_tools, url, key, t, ["graph_schema", "graph_path"])
        steps = [
            lambda m: {"calls": [("graph_schema", {})]},
            lambda m: {"calls": [("graph_path", {"source": "ann", "target": "assam"})]},
            lambda m: {"text": f"ann reaches assam in {json.loads(_last_tool_text(m, 'graph_path'))['length']} steps; labels: "
                              + ", ".join(sorted({n['label'] for n in json.loads(_last_tool_text(m, 'graph_schema'))['nodes']}))},
        ]
        model = _scripted_chat_model(steps)
        agent = create_react_agent(model, tools)
        out = await asyncio.wait_for(agent.ainvoke({"messages": [("user", ASK)]}), 60)
        answer = out["messages"][-1].content
        assert model.calls == 3
        assert "in 4 steps" in answer and "Entity" in answer and "Fact" in answer, answer                  # numbers and labels that only the real server could have supplied
        tool_msgs = [m for m in out["messages"] if m.type == "tool"]
        assert [m.name for m in tool_msgs] == ["graph_schema", "graph_path"] and all(m.status != "error" for m in tool_msgs)


async def test_langgraph_agent_gets_a_refusal_as_text_and_can_correct_itself(gm):
    from langgraph.prebuilt import create_react_agent
    t = tid(gm, "ag-lg-fix")
    async with serving() as url:
        key = await key_for(url, f"tt-aglgf-{uuid.uuid4().hex[:5]}", t)
        await seed(url, key, t)
        tools = await asyncio.to_thread(lc_tools, url, key, t, ["graph_influence"])
        steps = [
            lambda m: {"calls": [("graph_influence", {"metric": "degree"})]},                               # not a metric: the server refuses and names the valid ones
            lambda m: {"calls": [("graph_influence", {"metric": "pagerank", "top": 2})]} if "pagerank" in _last_tool_text(m, "graph_influence") else {"text": "gave up"},
            lambda m: {"text": f"top: {len(json.loads(_last_tool_text(m, 'graph_influence'))['rows'])} rows"},
        ]
        model = _scripted_chat_model(steps)
        out = await asyncio.wait_for(create_react_agent(model, tools).ainvoke({"messages": [("user", "who matters most?")]}), 60)
        texts = [m.content for m in out["messages"] if m.type == "tool"]
        assert texts[0].startswith("error 422") and "pagerank" in texts[0]
        assert out["messages"][-1].content == "top: 2 rows"


# ----------------------------------------------------------------------------------------------------------------------------- LlamaIndex
def _scripted_llamaindex_llm(steps):
    from llama_index.core.base.llms.types import ChatMessage, ChatResponse, LLMMetadata, MessageRole
    from llama_index.core.llms.function_calling import FunctionCallingLLM
    from llama_index.core.llms import CompletionResponse
    from llama_index.core.llms.llm import ToolSelection

    class Scripted(FunctionCallingLLM):
        calls: int = 0

        @property
        def metadata(self):
            return LLMMetadata(is_function_calling_model=True, is_chat_model=True)

        def _next(self, messages):
            move = steps[min(self.calls, len(steps) - 1)](messages)
            self.calls += 1
            tcs = [{"id": f"c{self.calls}-{i}", "name": n, "args": a} for i, (n, a) in enumerate(move.get("calls", []))]
            return ChatResponse(message=ChatMessage(role=MessageRole.ASSISTANT, content=move.get("text", ""), additional_kwargs={"scripted_calls": tcs}))

        def _prepare_chat_with_tools(self, tools, user_msg=None, chat_history=None, verbose=False, allow_parallel_tool_calls=False, tool_required=False, **kw):
            msgs = list(chat_history or [])
            if user_msg is not None:
                msgs.append(user_msg if isinstance(user_msg, ChatMessage) else ChatMessage(role=MessageRole.USER, content=user_msg))
            return {"messages": msgs, "tools": [t.metadata.name for t in tools]}

        def get_tool_calls_from_response(self, response, error_on_no_tool_call=True, **kw):
            tcs = response.message.additional_kwargs.get("scripted_calls", [])
            if not tcs and error_on_no_tool_call:
                raise ValueError("no tool call")
            return [ToolSelection(tool_id=c["id"], tool_name=c["name"], tool_kwargs=c["args"]) for c in tcs]

        def chat(self, messages, **kw):
            return self._next(messages)

        async def achat(self, messages, **kw):
            return self._next(messages)

        def stream_chat(self, messages, **kw):
            yield self._next(messages)

        async def astream_chat(self, messages, **kw):
            async def gen():
                yield self._next(messages)
            return gen()

        def complete(self, prompt, formatted=False, **kw):
            return CompletionResponse(text="")

        async def acomplete(self, prompt, formatted=False, **kw):
            return CompletionResponse(text="")

        def stream_complete(self, prompt, formatted=False, **kw):
            yield CompletionResponse(text="")

        async def astream_complete(self, prompt, formatted=False, **kw):
            async def gen():
                yield CompletionResponse(text="")
            return gen()

    return Scripted()


async def test_llamaindex_agent_loop_uses_the_tools_and_answers_from_what_they_return(gm):
    pytest.importorskip("llama_index.core")
    from llama_index.core.agent.workflow import FunctionAgent, ToolCallResult
    from integrations.llamaindex_tools import graphmem_tools as li_tools
    t = tid(gm, "ag-li")
    async with serving() as url:
        key = await key_for(url, f"tt-agli-{uuid.uuid4().hex[:5]}", t)
        await seed(url, key, t)
        tools = await asyncio.to_thread(li_tools, url, key, t, ["graph_schema", "graph_path"])

        steps = [
            lambda m: {"calls": [("graph_schema", {})]},
            lambda m: {"calls": [("graph_path", {"source": "ann", "target": "assam"})]},
            lambda m: {"text": "done: " + json.dumps([x.content for x in m if x.role == "tool"])},
        ]
        llm = _scripted_llamaindex_llm(steps)
        agent = FunctionAgent(tools=tools, llm=llm, streaming=False)
        handler = agent.run(user_msg=ASK)
        results = []
        async for ev in handler.stream_events():
            if isinstance(ev, ToolCallResult):
                results.append((ev.tool_name, str(ev.tool_output.content), ev.tool_output.is_error))
        answer = str(await asyncio.wait_for(handler, 60))
        assert llm.calls == 3
        assert [r[0] for r in results] == ["graph_schema", "graph_path"] and not any(r[2] for r in results)
        path = json.loads(results[1][1])
        assert path["found"] and path["length"] == 4 and path["path"][0]["ref"] == "ann" and path["path"][-1]["ref"] == "assam"
        assert any(n["label"] == "Fact" for n in json.loads(results[0][1])["nodes"])
        assert answer.startswith("done:") and "assam" in answer, answer
