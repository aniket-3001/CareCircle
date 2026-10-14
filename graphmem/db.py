"""FalkorDB access layer: connection pool, tenant -> graph naming, one-time index setup.

Design notes
- One FalkorDB graph per tenant (`mem__<tenant>`): hard isolation, and write serialization is per graph so
  tenants write in parallel (measured 2.36x in spikes/spike1b).
- Index setup runs once per graph per process, guarded by a lock. (Graphiti schedules an index build on every
  driver clone, which exhausted the connection pool in spikes/spike2.)
- A blocking pool makes bursts of concurrent agents queue instead of failing with MaxConnectionsError.
"""
from __future__ import annotations

import asyncio
import random
import re
import time
import uuid

from falkordb.asyncio import FalkorDB
from redis.asyncio import BlockingConnectionPool

TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
CTL_GRAPH = "ctl"

# (label, property) pairs indexed in every tenant graph.
TENANT_INDEXES = [
    ("Session", "id"), ("Episode", "id"), ("Entity", "key"), ("Fact", "id"), ("Fact", "skey"),
    ("Skill", "key"), ("Run", "id"), ("Task", "id"), ("Plan", "id"), ("Decision", "id"), ("Agent", "id"),
    ("Code", "id"), ("Commit", "sha"), ("Person", "id"),
]
CTL_INDEXES = [("Tenant", "id"), ("Agent", "id"), ("ApiKey", "hash"), ("Fork", "id")]


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:14]}"


def norm(s: str) -> str:
    return " ".join(str(s).lower().split())


def validate_tenant(tenant: str) -> str:
    if not isinstance(tenant, str) or not TENANT_RE.match(tenant):
        raise ValueError(f"invalid tenant id {tenant!r}: use [a-z0-9_-], 1-48 chars, starting alphanumeric")
    return tenant


class Overloaded(Exception):
    """FalkorDB kept rejecting queries because its queue was full (MAX_QUEUED_QUERIES). Map to HTTP 503."""


class RetryingGraph:
    """Wraps a FalkorDB graph handle. FalkorDB answers 'Max pending queries exceeded' *before* executing a query, so
    retrying exactly that error is safe even for writes. Retries use exponential backoff with jitter; after the
    attempts are used up Overloaded is raised. Every other error passes through untouched."""

    ATTEMPTS = 6

    def __init__(self, graph):
        self._g = graph

    async def query(self, q, params=None, **kw):
        delay = 0.02
        for attempt in range(self.ATTEMPTS):
            try:
                return await self._g.query(q, params, **kw)
            except Exception as e:
                if "max pending queries" not in str(e).lower():
                    raise
                if attempt == self.ATTEMPTS - 1:
                    raise Overloaded("database queue full; retry shortly") from e
                await asyncio.sleep(delay * (0.5 + random.random()))
                delay *= 2

    def __getattr__(self, name):
        return getattr(self._g, name)


class Db:
    def __init__(self, host: str = "localhost", port: int = 6379, max_connections: int = 64):
        pool = BlockingConnectionPool(host=host, port=port, max_connections=max_connections,
                                      timeout=30, decode_responses=True)
        self.client = FalkorDB(connection_pool=pool)
        self._ready: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def graph_name(tenant: str) -> str:
        return f"mem__{validate_tenant(tenant)}"

    async def graph(self, name: str):
        """Return a graph handle, creating indexes exactly once per process."""
        if name not in self._ready:
            async with self._lock:
                if name not in self._ready:
                    fut = asyncio.ensure_future(self._setup(name))
                    self._ready[name] = fut
        await self._ready[name]
        return RetryingGraph(self.client.select_graph(name))

    @staticmethod
    def fork_graph_name(tenant: str, fork_id: str) -> str:
        if not re.fullmatch(r"[a-z0-9]{6,24}", fork_id):
            raise ValueError("invalid fork id")
        return f"fork__{validate_tenant(tenant)}__{fork_id}"

    @staticmethod
    def space_graph_name(space: str) -> str:
        return f"shared__{validate_tenant(space)}"

    async def tenant_graph(self, tenant: str):
        return await self.graph(self.graph_name(tenant))

    async def _setup(self, name: str) -> None:
        g = RetryingGraph(self.client.select_graph(name))
        idx = CTL_INDEXES if name == CTL_GRAPH else TENANT_INDEXES
        for label, prop in idx:
            try:
                await g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
            except Exception as e:  # idempotent: index may already exist from an earlier process
                if "already indexed" not in str(e).lower() and "already exists" not in str(e).lower():
                    raise

    async def drop_tenant(self, tenant: str) -> None:
        name = self.graph_name(tenant)
        try:
            await self.client.select_graph(name).delete()
        except Exception:
            pass
        self._ready.pop(name, None)

    async def list_tenant_graphs(self) -> list[str]:
        return sorted(g[len("mem__"):] for g in await self.client.list_graphs() if g.startswith("mem__"))

    async def close(self) -> None:
        await self.client.aclose() if hasattr(self.client, "aclose") else None
