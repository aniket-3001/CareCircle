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

import json
from typing import Any, Iterable, Optional

import httpx
from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

DEFAULT_SKIP_PREFIX = ("care_",)      # the Care Circle product's own operations; ask for them with include=[...] if you want them
TIMEOUT = 60.0


def _text(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return f"error {r.status_code}: {r.text[:300]}"
    if r.status_code == 200:
        return json.dumps(body.get("result", body), default=str)
    why = body.get("error") or body.get("detail") or r.reason_phrase
    return f"error {r.status_code}: {why if isinstance(why, str) else json.dumps(why)}"


def graphmem_tools(base_url: str, api_key: str, tenant: str, include: Optional[Iterable[str]] = None, transport: Optional[httpx.BaseTransport] = None,
                   async_transport: Optional[httpx.AsyncBaseTransport] = None) -> list[StructuredTool]:
    """One StructuredTool per operation the key may see. `include` names the operations to expose (default: every one that is not a care_ operation)."""
    base = base_url.rstrip("/")
    headers = {"Authorization": "Bearer " + api_key}
    with httpx.Client(base_url=base, headers=headers, timeout=TIMEOUT, transport=transport) as c:
        r = c.get("/v1/ops")
    if r.status_code != 200:
        raise PermissionError(f"could not read the operation catalogue: {_text(r)}")
    catalogue: dict[str, dict] = r.json()
    wanted = list(include) if include is not None else [n for n in catalogue if not n.startswith(DEFAULT_SKIP_PREFIX)]
    unknown = [n for n in wanted if n not in catalogue]
    if unknown:
        raise KeyError(f"no such operation: {', '.join(unknown)}")

    def make(name: str, info: dict) -> StructuredTool:
        fields: dict[str, Any] = {}
        for a in info["args"]:
            fields[a["name"]] = (Any, Field(...)) if a["required"] else (Any, Field(None))
        schema = create_model(f"{name}_args", **fields)
        url = f"/v1/tenants/{tenant}/{name}"

        def run(**kwargs: Any) -> str:
            body = {k: v for k, v in kwargs.items() if v is not None}
            with httpx.Client(base_url=base, headers=headers, timeout=TIMEOUT, transport=transport) as cl:
                return _text(cl.post(url, json=body))

        async def arun(**kwargs: Any) -> str:
            body = {k: v for k, v in kwargs.items() if v is not None}
            async with httpx.AsyncClient(base_url=base, headers=headers, timeout=TIMEOUT, transport=async_transport) as cl:
                return _text(await cl.post(url, json=body))

        return StructuredTool.from_function(func=run, coroutine=arun, name=name, args_schema=schema,
                                            description=f"{info['doc'] or name} (memory operation, {info['scope']} access)")

    return [make(n, catalogue[n]) for n in wanted]
