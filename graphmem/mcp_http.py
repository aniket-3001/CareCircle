"""The MCP server over HTTP (streamable HTTP, JSON responses), at POST /mcp on the same server as the REST API, so an agent framework or an MCP client
can connect to the live memory with a URL and a key instead of running our code.

  Authorization: Bearer gm_...      the same agent keys as the REST API, checked on every request; wrong or missing key -> 401
  stateless                         no MCP session is kept on the server; the caller's identity is held for the one request, in a context variable

The tools are those of graphmem/mcp_server.py, and every tool call goes through the same grants and scopes as the REST API. The rate limits are the
REST API's (per agent, and per client address for bad keys). Nothing here can see a tenant the key was not granted."""
from __future__ import annotations

import contextvars
import json
import os
from contextlib import AsyncExitStack
from typing import Optional
from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings

from .mcp_server import build
from .policy import GraphMem

PATH = "/mcp"
_current: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("mcp_agent", default=None)


def _who() -> str:
    agent = _current.get()
    if agent is None:                                 # a tool ran with no authenticated request around it: refuse rather than guess
        raise PermissionError("no authenticated caller")
    return agent


def _hosts() -> TransportSecuritySettings:
    """The MCP library refuses requests whose Host header it does not expect (protection against DNS rebinding). Allow this site's own host, from
    CC_PUBLIC_URL, and localhost; the key is still required for everything."""
    hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "testserver", "t"]
    site = urlparse(os.getenv("CC_PUBLIC_URL", "")).netloc
    if site:
        hosts += [site, site + ":*"]
    extra = [h.strip() for h in os.getenv("CC_MCP_HOSTS", "").split(",") if h.strip()]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts + extra, allowed_origins=[])


async def _reply(send, status: int, body: dict, headers: Optional[list] = None) -> None:
    raw = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode()), *(headers or [])]})
    await send({"type": "http.response.body", "body": raw})


class McpGate:
    """Holds the MCP app and decides, per request, whether /mcp may reach it."""

    def __init__(self, gm: GraphMem, limiter, bad_auth):
        self.gm, self.limiter, self.bad_auth = gm, limiter, bad_auth
        self.server = build(gm, _who)
        self.mcp = self.server.streamable_http_app(streamable_http_path=PATH, stateless_http=True, json_response=True, transport_security=_hosts())
        self._stack: Optional[AsyncExitStack] = None

    async def start(self) -> None:
        self._stack = AsyncExitStack()
        await self._stack.enter_async_context(self.mcp.router.lifespan_context(self.mcp))

    async def stop(self) -> None:
        if self._stack:
            await self._stack.aclose()
            self._stack = None

    async def handle(self, scope, receive, send) -> None:
        headers = {k.lower(): v for k, v in scope["headers"]}
        auth = headers.get(b"authorization", b"").decode("latin-1")
        key = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        ip = (scope.get("client") or ("?",))[0]
        agent = await self.gm.authenticate(key) if key else None
        if not agent:
            if not self.bad_auth.allow(ip):
                return await _reply(send, 429, {"error": "too many failed attempts"})
            return await _reply(send, 401, {"error": "invalid api key" if key else "missing bearer token"}, [(b"www-authenticate", b'Bearer realm="graphmem"')])
        if not self.limiter.allow(agent):
            return await _reply(send, 429, {"error": "rate limit exceeded"})
        token = _current.set(agent)
        try:
            await self.mcp(scope, receive, send)
        finally:
            _current.reset(token)


class _Front:
    """ASGI middleware: /mcp goes to the gate, everything else to the REST app untouched."""

    def __init__(self, app, gate: McpGate):
        self.app, self.gate = app, gate

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == PATH:
            return await self.gate.handle(scope, receive, send)
        return await self.app(scope, receive, send)


def install(app, gm: GraphMem, limiter, bad_auth) -> Optional[McpGate]:
    """Serve MCP at /mcp on `app`. Off when CC_MCP_HTTP=0."""
    if os.getenv("CC_MCP_HTTP", "1") == "0":
        return None
    gate = McpGate(gm, limiter, bad_auth)
    app.add_middleware(_Front, gate=gate)
    app.router.on_startup.append(gate.start)
    app.router.on_shutdown.append(gate.stop)
    app.state.mcp = gate
    return gate
