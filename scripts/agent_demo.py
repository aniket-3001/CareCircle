"""An agent driven by a real model (Amazon Bedrock, Nova Pro) that uses the memory graph through our LlamaIndex or LangChain tools, run by hand.

  python scripts/agent_demo.py llamaindex|langchain --url https://3-228-70-117.sslip.io --key gm_... --tenant demo-xxxxxxxx [--question "..."] [--mode graph|memory]

`--mode graph` (the default) gives the model graph-algorithm tools (path, influence, communities). `--mode memory` gives it the MEMORY tools instead: `recall` (notes other agents wrote
about an entry, returned with the path to the entry), the entry's notes, who has not yet seen a change, and `add_episode` with `about` to write its own note. Run
`scripts/agent_memory_demo.py` first to leave a night agent's note about warfarin in the circle, then ask this agent what it knows and whether it should act.

It needs AWS credentials for Bedrock (profile from AWS_PROFILE) and, for the framework you pick, `llama-index-llms-bedrock-converse` (LlamaIndex) or
`langchain-aws` and `langgraph` (LangChain), besides requirements-integrations.txt. It is not part of the test suite: it calls a paid model. Use a synthetic
circle (POST /demo/start gives one with keys); nothing here should be pointed at real people's records.

It prints every tool the model chose to call, with its arguments, then the model's answer, so what happened can be read."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TOOLS = ["graph_schema", "graph_path", "graph_influence", "graph_communities", "graph_neighbourhood"]
MEMORY_TOOLS = ["recall", "care_regimen", "care_entry_notes", "care_divergence", "add_episode"]
MEMORY_QUESTION = ("Another agent may have left a note about warfarin in this circle's memory. Use `recall` with query 'warfarin' and report the note and the path it gives. "
                   "Then call `care_divergence` for person 'asha' and say which carers have not yet seen the latest change. You may write a note with `add_episode` only if NO carer "
                   "is behind; otherwise say you are holding off and who must see it first. Answer in three short sentences.")
MODEL = os.getenv("CC_MODEL", "us.amazon.nova-pro-v1:0")
REGION = os.getenv("AWS_REGION", "us-east-1")
QUESTION = ("This graph holds one person's medicines, the doses on record and the carers. Use the tools. First look at the schema. Then find how the person "
            "'asha' is connected to the medicine 'atorvastatin', and which record sits between the most other records (betweenness). Answer in two short sentences.")
TOOLSET = [TOOLS]                                                    # set by --mode
SYSTEM = "You answer only from what the tools return. Never invent record names. Tenant for every tool call is given in the user message."


async def llamaindex(url, key, tenant, question):
    from llama_index.core.agent.workflow import FunctionAgent, ToolCall, ToolCallResult
    from llama_index.llms.bedrock_converse import BedrockConverse

    from integrations.llamaindex_tools import graphmem_tools
    tools = await asyncio.to_thread(graphmem_tools, url, key, tenant, TOOLSET[0])
    llm = BedrockConverse(model=MODEL, region_name=REGION, profile_name=os.getenv("AWS_PROFILE"), temperature=0.0, max_tokens=600)
    agent = FunctionAgent(tools=tools, llm=llm, system_prompt=SYSTEM)
    handler = agent.run(user_msg=f"tenant = {tenant}. {question}")
    calls = []
    async for ev in handler.stream_events():
        if isinstance(ev, ToolCall):
            calls.append(ev.tool_name)
            print(f"  tool call: {ev.tool_name}({json.dumps(ev.tool_kwargs)})")
        elif isinstance(ev, ToolCallResult):
            print(f"    -> {str(ev.tool_output.content)[:160]}")
    return calls, str(await handler)


async def langchain(url, key, tenant, question):
    from langchain_aws import ChatBedrockConverse

    from integrations.langchain_tools import graphmem_tools
    tools = await asyncio.to_thread(graphmem_tools, url, key, tenant, TOOLSET[0])
    model = ChatBedrockConverse(model=MODEL, region_name=REGION, credentials_profile_name=os.getenv("AWS_PROFILE"), temperature=0.0, max_tokens=600)
    try:                                                              # the current home of the agent builder; older installs only have langgraph's
        from langchain.agents import create_agent
        agent = create_agent(model, tools, system_prompt=SYSTEM)
    except ImportError:
        from langgraph.prebuilt import create_react_agent
        agent = create_react_agent(model, tools, prompt=SYSTEM)
    out = await agent.ainvoke({"messages": [("user", f"tenant = {tenant}. {question}")]})
    calls = []
    for m in out["messages"]:
        for c in getattr(m, "tool_calls", None) or []:
            calls.append(c["name"])
            print(f"  tool call: {c['name']}({json.dumps(c['args'])})")
        if m.type == "tool":
            print(f"    -> {str(m.content)[:160]}")
    return calls, out["messages"][-1].content if isinstance(out["messages"][-1].content, str) else json.dumps(out["messages"][-1].content)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("framework", choices=["llamaindex", "langchain"])
    ap.add_argument("--url", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--question", default="")
    ap.add_argument("--mode", choices=["graph", "memory"], default="graph")
    a = ap.parse_args()
    TOOLSET[0] = MEMORY_TOOLS if a.mode == "memory" else TOOLS
    a.question = a.question or (MEMORY_QUESTION if a.mode == "memory" else QUESTION)
    print(f"{a.framework} agent, model {MODEL}")
    calls, answer = asyncio.run((llamaindex if a.framework == "llamaindex" else langchain)(a.url, a.key, a.tenant, a.question))
    print("\nanswer:", answer.strip())
    print("tools used:", calls)
    return 0 if calls else 1


if __name__ == "__main__":
    sys.exit(main())
