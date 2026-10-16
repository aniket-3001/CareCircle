"""The memory graph as LlamaIndex tools: one FunctionTool per operation, built from the server's own catalogue (GET /v1/ops).

    from integrations.llamaindex_tools import graphmem_tools
    tools = graphmem_tools("https://3-228-70-117.sslip.io", api_key, tenant)
    tools = graphmem_tools(url, api_key, tenant, include=["graph_path", "graph_influence", "recall", "add_episode"])

Use them anywhere LlamaIndex takes tools (an agent, a workflow, `llm.chat_with_tools`). Needs `llama-index-core` (requirements-integrations.txt); the server
needs nothing extra. As with the LangChain adapter, the server judges every call and its refusals come back as text, so a model can correct itself."""
from __future__ import annotations

from typing import Iterable, Optional

import httpx
from llama_index.core.tools import FunctionTool

from ._graphmem import args_model, caller, choose, describe, fetch_catalogue


def graphmem_tools(base_url: str, api_key: str, tenant: str, include: Optional[Iterable[str]] = None, transport: Optional[httpx.BaseTransport] = None,
                   async_transport: Optional[httpx.AsyncBaseTransport] = None) -> list[FunctionTool]:
    """One FunctionTool per operation the key may see. `include` names the operations to expose (default: every one that is not a care_ operation)."""
    base, headers, catalogue = fetch_catalogue(base_url, api_key, transport)
    tools = []
    for name in choose(catalogue, include):
        run, arun = caller(base, headers, tenant, name, transport, async_transport)
        tools.append(FunctionTool.from_defaults(fn=run, async_fn=arun, name=name, description=describe(name, catalogue[name]),
                                                fn_schema=args_model(name, catalogue[name])))
    return tools
