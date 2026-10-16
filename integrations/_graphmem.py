"""What the framework adapters share: reading the operation catalogue, choosing operations, turning a catalogue entry into an argument schema, calling an
operation and turning the reply into text. Nothing here imports a framework."""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

import httpx
from pydantic import Field, create_model

DEFAULT_SKIP_PREFIX = ("care_",)      # the Care Circle product's own operations; ask for them with include=[...] if you want them
TIMEOUT = 60.0


def result_text(r: httpx.Response) -> str:
    """The reply as text for a model: the result as JSON, or the server's refusal as 'error <status>: <why>' (never an exception)."""
    try:
        body = r.json()
    except ValueError:
        return f"error {r.status_code}: {r.text[:300]}"
    if r.status_code == 200:
        return json.dumps(body.get("result", body), default=str)
    why = body.get("error") or body.get("detail") or r.reason_phrase
    return f"error {r.status_code}: {why if isinstance(why, str) else json.dumps(why)}"


def fetch_catalogue(base_url: str, api_key: str, transport: Optional[httpx.BaseTransport] = None) -> tuple[str, dict, dict]:
    """(base url, auth headers, the server's catalogue of operations). A key the server refuses raises PermissionError."""
    base = base_url.rstrip("/")
    headers = {"Authorization": "Bearer " + api_key}
    with httpx.Client(base_url=base, headers=headers, timeout=TIMEOUT, transport=transport) as c:
        r = c.get("/v1/ops")
    if r.status_code != 200:
        raise PermissionError(f"could not read the operation catalogue: {result_text(r)}")
    return base, headers, r.json()


def choose(catalogue: dict, include: Optional[Iterable[str]]) -> list[str]:
    wanted = list(include) if include is not None else [n for n in catalogue if not n.startswith(DEFAULT_SKIP_PREFIX)]
    unknown = [n for n in wanted if n not in catalogue]
    if unknown:
        raise KeyError(f"no such operation: {', '.join(unknown)}")
    return wanted


def args_model(name: str, info: dict):
    """A pydantic model with one field per argument. The catalogue says which are required, not their types, so each takes any JSON value and the server validates."""
    return create_model(f"{name}_args", **{a["name"]: (Any, Field(...) if a["required"] else Field(None)) for a in info["args"]})


def describe(name: str, info: dict) -> str:
    return f"{info.get('help') or info['doc'] or name} (memory operation, {info['scope']} access)"


def caller(base: str, headers: dict, tenant: str, name: str, transport=None, async_transport=None):
    """(sync function, async function) that run one operation with keyword arguments and return text. None-valued arguments are left out."""
    url = f"/v1/tenants/{tenant}/{name}"

    def run(**kwargs: Any) -> str:
        with httpx.Client(base_url=base, headers=headers, timeout=TIMEOUT, transport=transport) as cl:
            return result_text(cl.post(url, json={k: v for k, v in kwargs.items() if v is not None}))

    async def arun(**kwargs: Any) -> str:
        async with httpx.AsyncClient(base_url=base, headers=headers, timeout=TIMEOUT, transport=async_transport) as cl:
            return result_text(await cl.post(url, json={k: v for k, v in kwargs.items() if v is not None}))

    return run, arun
