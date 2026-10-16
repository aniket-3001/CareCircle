"""The memory graph as LangChain tools: one tool per operation, built from the server's own catalogue (GET /v1/ops), so a new operation appears here
without a change to this file.

    from integrations.langchain_tools import graphmem_tools
    tools = graphmem_tools("https://3-228-70-117.sslip.io", api_key, tenant)             # every general operation
    tools = graphmem_tools(url, api_key, tenant, include=["graph_path", "graph_influence", "recall", "add_episode"])

Works with anything that takes LangChain tools (an agent executor, LangGraph's ToolNode, `model.bind_tools(tools)`). Needs `langchain-core`
(requirements-integrations.txt); the server needs nothing extra. The server remains the judge of every call: grants, scopes, argument checks and rate
limits are its own, and its refusals come back to the model as text (not exceptions), so the model can correct itself.

The catalogue lists argument names and whether each is required, not their types, so each tool's schema accepts any JSON value per argument and the
server validates it."""
from __future__ import annotations

from typing import Iterable, Optional

import httpx
from langchain_core.tools import StructuredTool

from ._graphmem import args_model, caller, choose, describe, fetch_catalogue


def graphmem_tools(base_url: str, api_key: str, tenant: str, include: Optional[Iterable[str]] = None, transport: Optional[httpx.BaseTransport] = None,
                   async_transport: Optional[httpx.AsyncBaseTransport] = None) -> list[StructuredTool]:
    """One StructuredTool per operation the key may see. `include` names the operations to expose (default: every one that is not a care_ operation)."""
    base, headers, catalogue = fetch_catalogue(base_url, api_key, transport)
    tools = []
    for name in choose(catalogue, include):
        run, arun = caller(base, headers, tenant, name, transport, async_transport)
        tools.append(StructuredTool.from_function(func=run, coroutine=arun, name=name, args_schema=args_model(name, catalogue[name]),
                                                  description=describe(name, catalogue[name])))
    return tools
