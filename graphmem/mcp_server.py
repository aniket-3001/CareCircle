"""MCP server (stdio) exposing the same operations as the HTTP API.

The calling agent's identity comes from GRAPHMEM_API_KEY, checked once at startup against the `ctl` graph. Every tool
takes the tenant explicitly and goes through the same authorization as the HTTP API.

  GRAPHMEM_API_KEY=gm_... python -m graphmem.mcp_server
"""
from __future__ import annotations

import json
import os
import sys
from typing import Callable, Optional, Union

from mcp.server.mcpserver import MCPServer

from . import branch, ops, spaces
from .db import Db
from .policy import GraphMem


def _loads(value, default):
    """Arguments arrive as a JSON string, but some clients (the MCP Inspector's command line, for one) parse it first and send the object. Take both."""
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value) if value else default


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
    async def call(tenant: str, op: str, args_json: Union[str, dict] = "{}") -> str:
        """Run a memory operation on a tenant. args_json is a JSON object of the operation's arguments."""
        try:
            args = _loads(args_json, {})
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
    async def publish_facts(tenant: str, space: str, fact_ids_json: Union[str, list]) -> str:
        """Publish chosen facts from your tenant into a shared space. fact_ids_json is a JSON list of fact ids."""
        try:
            return json.dumps(await spaces.publish(gm, me(), tenant, space, _loads(fact_ids_json, [])))
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
    async def fork_call(fork_id: str, op: str, args_json: Union[str, dict] = "{}") -> str:
        """Run a memory operation on a fork (same operations as call)."""
        try:
            if op not in ops.OPS:
                raise KeyError(f"unknown operation {op!r}")
            fm = await branch.open_fork(gm, me(), fork_id)
            return json.dumps(await getattr(fm, op)(**_loads(args_json, {})), default=str)
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

    # Graph algorithms as first-class tools, so a model sees each one with its own typed arguments instead of finding them behind `call`.
    async def graph(tenant: str, op: str, **args) -> str:
        try:
            clean = {k: v for k, v in args.items() if v not in (None, "")}
            return json.dumps(await ops.invoke(gm, me(), tenant, op, clean), default=str)
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    @server.tool()
    async def graph_schema(tenant: str) -> str:
        """What a tenant's graph holds: node labels and relationship types with counts. Start here to learn the data model."""
        return await graph(tenant, "graph_schema")

    @server.tool()
    async def graph_path(tenant: str, source: str, target: str, max_hops: int = 8, source_label: Optional[str] = None,
                         target_label: Optional[str] = None) -> str:
        """Shortest path between two records (named by id, key or name), ignoring link direction: the records on it and the relationship between each pair."""
        return await graph(tenant, "graph_path", source=source, target=target, max_hops=max_hops, source_label=source_label, target_label=target_label)

    @server.tool()
    async def graph_influence(tenant: str, metric: str = "pagerank", label: Optional[str] = None, top: int = 10) -> str:
        """The most influential records. metric: 'pagerank' (many records point here), 'harmonic' (reaches the rest of the graph fastest) or 'betweenness' (many shortest paths pass through)."""
        return await graph(tenant, "graph_influence", metric=metric, label=label, top=top)

    @server.tool()
    async def graph_communities(tenant: str, method: str = "wcc", label: Optional[str] = None, top: int = 10) -> str:
        """Groups of records that belong together. method: 'wcc' (separate connected parts) or 'labelpropagation' (communities within them)."""
        return await graph(tenant, "graph_communities", method=method, label=label, top=top)

    @server.tool()
    async def graph_neighbourhood(tenant: str, ref: str, depth: int = 2, label: Optional[str] = None, limit: int = 50) -> str:
        """Everything within `depth` hops of one record (named by id, key or name), nearest first."""
        return await graph(tenant, "graph_neighbourhood", ref=ref, depth=depth, label=label, limit=limit)

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
