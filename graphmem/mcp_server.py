"""MCP server (stdio) exposing the same operations as the HTTP API.

The calling agent's identity comes from GRAPHMEM_API_KEY, checked once at startup against the `ctl` graph. Every tool
takes the tenant explicitly and goes through the same authorization as the HTTP API.

  GRAPHMEM_API_KEY=gm_... python -m graphmem.mcp_server
"""
from __future__ import annotations

import json
import os
import sys
from typing import Callable, Union

from mcp.server.mcpserver import MCPServer

from . import branch, ops, spaces
from .db import Db
from .policy import GraphMem


def build(gm: GraphMem, agent: Union[str, Callable[[], str]]) -> MCPServer:
    """`agent` is the caller's id, or (for the HTTP endpoint, where each request has its own caller) a function that returns it."""
    def me() -> str:
        return agent() if callable(agent) else agent

    server = MCPServer(
        "graphmem",
        instructions=("Graph-backed memory shared by agents. Every call names a tenant; you only see tenants you were "
                      "granted. Use call(tenant, op, args_json) for any operation, ops() to list them."),
    )

    @server.tool()
    async def whoami() -> str:
        """Which tenants and scopes this agent has."""
        return json.dumps({"agent": me(), "tenants": await gm.tenants_of(me())})

    @server.tool()
    async def list_ops() -> str:
        """Catalogue of memory operations with their arguments."""
        return json.dumps(ops.describe())

    @server.tool()
    async def call(tenant: str, op: str, args_json: str = "{}") -> str:
        """Run a memory operation on a tenant. args_json is a JSON object of the operation's arguments."""
        try:
            args = json.loads(args_json or "{}")
            return json.dumps(await ops.invoke(gm, me(), tenant, op, args), default=str)
        except Exception as e:  # tool errors are returned to the model, not raised through the transport
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    @server.tool()
    async def space_recall(space: str, query: str) -> str:
        """Recall facts from a shared space (only facts explicitly published into it)."""
        try:
            return json.dumps(await ops.invoke_space(gm, me(), space, "recall", {"query": query}), default=str)
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    @server.tool()
    async def publish_facts(tenant: str, space: str, fact_ids_json: str) -> str:
        """Publish chosen facts from your tenant into a shared space. fact_ids_json is a JSON list of fact ids."""
        try:
            return json.dumps(await spaces.publish(gm, me(), tenant, space, json.loads(fact_ids_json)))
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    @server.tool()
    async def fork_memory(tenant: str, label: str = "") -> str:
        """Branch a tenant's memory (GRAPH.COPY). Work on the fork with fork_call; nothing touches the tenant until merge."""
        try:
            return json.dumps(await branch.fork(gm, me(), tenant, label))
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    @server.tool()
    async def fork_call(fork_id: str, op: str, args_json: str = "{}") -> str:
        """Run a memory operation on a fork (same operations as call)."""
        try:
            if op not in ops.OPS:
                raise KeyError(f"unknown operation {op!r}")
            fm = await branch.open_fork(gm, me(), fork_id)
            return json.dumps(await getattr(fm, op)(**json.loads(args_json or "{}")), default=str)
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    @server.tool()
    async def merge_fork(fork_id: str, apply: bool = False, on_conflict: str = "skip") -> str:
        """Dry-run (default) or apply a fork's new work to its tenant. Reports conflicts and plans that would be stale."""
        try:
            return json.dumps(await branch.merge(gm, me(), fork_id, apply=apply, on_conflict=on_conflict), default=str)
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    @server.tool()
    async def discard_fork(fork_id: str) -> str:
        """Delete a fork without merging."""
        try:
            await branch.discard(gm, me(), fork_id)
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    # Convenience tools for the most common calls (thin wrappers over the same operations).
    @server.tool()
    async def remember(tenant: str, session: str, role: str, content: str) -> str:
        """Append a message to a session's persistent history."""
        return json.dumps(await ops.invoke(gm, me(), tenant, "add_episode",
                                           {"session": session, "role": role, "content": content}))

    @server.tool()
    async def recall(tenant: str, query: str, hops: int = 2) -> str:
        """Graph recall: matching facts, each with its source episodes and the path that reached it."""
        return json.dumps(await ops.invoke(gm, me(), tenant, "recall", {"query": query, "hops": hops}), default=str)

    return server


async def _amain() -> None:
    key = os.environ.get("GRAPHMEM_API_KEY", "")
    gm = GraphMem(Db(host=os.getenv("FALKORDB_HOST", "localhost"), port=int(os.getenv("FALKORDB_PORT", "6379"))))
    agent = await gm.authenticate(key)
    if not agent:
        sys.exit("GRAPHMEM_API_KEY missing or invalid")
    await build(gm, agent).run_stdio_async()


def main() -> None:  # pragma: no cover
    import asyncio
    asyncio.run(_amain())


if __name__ == "__main__":  # pragma: no cover
    main()
