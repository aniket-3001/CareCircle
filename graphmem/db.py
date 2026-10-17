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
import logging
import os
import random
import re
import time
import uuid

from typing import Optional

from falkordb.asyncio import FalkorDB
from redis.asyncio import BlockingConnectionPool

log = logging.getLogger("graphmem.db")

TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
CTL_GRAPH = "ctl"
RO_USER = "gm_reader"

# (label, property) pairs indexed in a tenant graph. A care circle's graph gets the CARE ones when it is made; the ENGINE ones belong to the generic memory engine
# (episodes, facts, tasks, plans ...), which the care product never touches, so they are created the first time a query on that graph names one of those labels
# (`Db.ensure_engine`, called from `TenantMemory._q`). Space and fork graphs hold engine data from the start and get everything at once.
CARE_INDEXES = [("Person", "id"), ("Dose", "id"), ("Give", "key"), ("Nudge", "key"), ("Drug", "name"), ("ChatMsg", "by"), ("Receipt", "id")]
ENGINE_INDEXES = [
    ("Session", "id"), ("Episode", "id"), ("Entity", "key"), ("Fact", "id"), ("Fact", "skey"),
    ("Skill", "key"), ("Run", "id"), ("Task", "id"), ("Plan", "id"), ("Decision", "id"), ("Agent", "id"),
    ("Code", "id"), ("Commit", "sha"),
]
TENANT_INDEXES = ENGINE_INDEXES + CARE_INDEXES                 # all of them, for callers that want the full list
ENGINE_LABELS = re.compile(r":(Session|Episode|Entity|Fact|Skill|Run|Task|Plan|Decision|Agent|Code|Commit)\b|db\.idx\.(fulltext|vector)")
EAGER_ENGINE = os.getenv("GRAPHMEM_EAGER_ENGINE", "") in ("1", "true", "yes")     # create every index when a graph is made (the old behaviour)
CTL_INDEXES = [("Tenant", "id"), ("Agent", "id"), ("ApiKey", "hash"), ("Fork", "id"), ("Account", "email"), ("Account", "agent"), ("Account", "sub"),
               ("Session", "hash"), ("Invite", "hash"), ("Throttle", "key"), ("TgChat", "chat")]
# UNIQUE constraints enforced by FalkorDB itself (need the matching exact-match index above): even a buggy writer cannot
# create two Entities with one key, two Tasks with one id, two keys with one hash.
TENANT_UNIQUE = [("Entity", "key"), ("Task", "id"), ("Session", "id"), ("Episode", "id"), ("Plan", "id")]
CTL_UNIQUE = [("Tenant", "id"), ("Agent", "id"), ("ApiKey", "hash"), ("Fork", "id"), ("Account", "email"), ("Account", "agent"), ("Throttle", "key")]


# Caps FalkorDB enforces on every query (its own defaults are "no limit"): a runaway traversal or a huge result must not hold the
# single writer of a graph for ever or exhaust memory. A cap is set only when the server has none, so an operator's own setting wins.
# Each can be changed (or switched off with 0) through the environment variable named here.
QUERY_LIMITS = [
    ("TIMEOUT_MAX", "GRAPHMEM_QUERY_TIMEOUT_MAX_MS", 60_000),      # no request may ask for more than a minute
    ("TIMEOUT_DEFAULT", "GRAPHMEM_QUERY_TIMEOUT_MS", 15_000),      # a query that names no time may run for 15 seconds
    ("QUERY_MEM_CAPACITY", "GRAPHMEM_QUERY_MEM_BYTES", 1 << 30),   # one query may use 1 GiB
]


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


class QueryLimit(Exception):
    """One query ran past the time or memory cap the database enforces (see Db.apply_limits). Map to HTTP 503; never retried."""


# What FalkorDB answers when a cap stops a query (the query is abandoned and, for a write, rolled back).
_LIMIT_MESSAGES = ("timed out", "mem consumption")


class RetryingGraph:
    """Wraps a FalkorDB graph handle. FalkorDB answers 'Max pending queries exceeded' *before* executing a query, so
    retrying exactly that error is safe even for writes. Retries use exponential backoff with jitter; after the
    attempts are used up Overloaded is raised. Every other error passes through untouched."""

    ATTEMPTS = 6

    def __init__(self, graph):
        self._g = graph

    async def query(self, q, params=None, **kw):
        return await self._retry(self._g.query, q, params, **kw)

    async def ro_query(self, q, params=None, **kw):
        return await self._retry(self._g.ro_query, q, params, **kw)

    async def _retry(self, call, q, params, **kw):
        delay = 0.02
        for attempt in range(self.ATTEMPTS):
            try:
                return await call(q, params, **kw)
            except Exception as e:
                msg = str(e).lower()
                if any(m in msg for m in _LIMIT_MESSAGES):
                    raise QueryLimit("that was too heavy for the database to answer in time; ask for less") from e
                if "max pending queries" not in msg:
                    raise
                if attempt == self.ATTEMPTS - 1:
                    raise Overloaded("database queue full; retry shortly") from e
                await asyncio.sleep(delay * (0.5 + random.random()))
                delay *= 2

    def __getattr__(self, name):
        return getattr(self._g, name)


class Db:
    def __init__(self, host: str = "localhost", port: int = 6379, max_connections: int = 64,
                 ro_password: Optional[str] = None):
        # GRAPHMEM_DB_PASSWORD: the database itself requires a password (Redis requirepass), so another container or a stray port cannot read it.
        pool = BlockingConnectionPool(host=host, port=port, max_connections=max_connections,
                                      timeout=30, decode_responses=True, password=os.getenv("GRAPHMEM_DB_PASSWORD") or None)
        self.client = FalkorDB(connection_pool=pool)
        # Optional database-level ACL: read-scope operations run as a Redis user that may only call GRAPH.RO_QUERY, so even a
        # bug in a read path cannot write. Enabled by GRAPHMEM_RO_PASSWORD; the user is created on first use (needs the default user).
        ro_password = ro_password if ro_password is not None else os.getenv("GRAPHMEM_RO_PASSWORD")
        self.ro_client = None            # built lazily: the client authenticates on construction, so the user must exist first
        self._ro_password, self._conn = ro_password, dict(host=host, port=port, max_connections=max_connections)
        self._ro_ready = False
        self._ready: dict[str, asyncio.Future] = {}
        self._engine: dict[str, asyncio.Future] = {}
        self._engine_done: set[str] = set()
        self._lock = asyncio.Lock()
        self._limits_set = False

    async def apply_limits(self) -> dict:
        """Give the database its query time and memory caps (once per process). Returns what is in force. A server that refuses
        the setting (a managed service) is left as it is, with a warning: the app still works, only the cap is missing."""
        if self._limits_set:
            return {}
        async with self._lock:
            if self._limits_set:
                return {}
            out = {}
            for key, env, default in QUERY_LIMITS:
                try:
                    want = int(os.getenv(env, default))
                    now = int((await self.client.execute_command("GRAPH.CONFIG", "GET", key))[1])
                    if want > 0 and now == 0:
                        await self.client.execute_command("GRAPH.CONFIG", "SET", key, want)
                        now = want
                    out[key] = now
                except Exception as e:  # noqa: BLE001
                    log.warning("could not set %s: %s", key, e)
            self._limits_set = True
            return out

    @staticmethod
    def graph_name(tenant: str) -> str:
        return f"mem__{validate_tenant(tenant)}"

    async def ensure_ro_user(self) -> None:
        if not self._ro_password or self._ro_ready:
            return
        async with self._lock:
            if self._ro_ready:
                return
            await self.client.execute_command("ACL", "SETUSER", RO_USER, "reset", "on", f">{self._ro_password}", "~*", "&*",
                                              "+ping", "+auth", "+hello", "+info", "+client", "+graph.ro_query", "+graph.list")
            pool = BlockingConnectionPool(timeout=30, decode_responses=True, username=RO_USER, password=self._ro_password,
                                          **self._conn)
            self.ro_client = await asyncio.get_running_loop().run_in_executor(None, lambda: FalkorDB(connection_pool=pool))
            self._ro_ready = True

    async def ro_graph(self, name: str):
        """Graph handle bound to the read-only database user (falls back to the normal handle when ACL is not enabled)."""
        g = await self.graph(name)
        if not self._ro_password:
            return g
        await self.ensure_ro_user()
        return RetryingGraph(self.ro_client.select_graph(name))

    async def graph(self, name: str):
        """Return a graph handle, creating indexes exactly once per process."""
        if not self._limits_set:
            await self.apply_limits()
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
        full = name != CTL_GRAPH and (EAGER_ENGINE or name.startswith(("shared__", "fork__")))
        idx = CTL_INDEXES if name == CTL_GRAPH else (TENANT_INDEXES if full else CARE_INDEXES)
        for label, prop in idx:
            try:
                await g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
            except Exception as e:  # idempotent: index may already exist from an earlier process
                if "already indexed" not in str(e).lower() and "already exists" not in str(e).lower():
                    raise
        if name == CTL_GRAPH or full:
            await self._engine_extras(name, g)
        if name != CTL_GRAPH:
            from . import schema

            async def mk(label: str, prop: str) -> None:
                try:
                    await g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
                except Exception as e:
                    if "already" not in str(e).lower():
                        raise
            await schema.migrate(g, mk)           # versioned: each circle graph is brought up to the current shape when first opened

    async def _engine_extras(self, name: str, g) -> None:
        """The unique constraints (and, for a tenant graph, the vector and full-text indexes) that go with the indexes above."""
        for label, prop in (CTL_UNIQUE if name == CTL_GRAPH else TENANT_UNIQUE):
            try:
                await self.client.execute_command("GRAPH.CONSTRAINT", "CREATE", name, "UNIQUE", "NODE", label, "PROPERTIES", "1", prop)
            except Exception as e:  # idempotent
                if "already" not in str(e).lower():
                    raise
        if name == CTL_GRAPH:
            return
        if os.getenv("GRAPHMEM_EMBEDDINGS", "") in ("1", "true", "yes"):
            try:
                await g.query("CREATE VECTOR INDEX FOR (f:Fact) ON (f.embedding) OPTIONS {dimension:384, similarityFunction:'cosine'}")
            except Exception as e:
                if "already" not in str(e).lower():
                    raise
        try:   # full-text index for search_text (DDL form; the procedure form is rejected by FalkorDB 6.x)
            await g.query("CREATE FULLTEXT INDEX FOR (e:Episode) ON (e.content)")
        except Exception as e:
            if "already" not in str(e).lower():
                raise

    async def ensure_engine(self, name: str) -> None:
        """Create the generic memory engine's indexes and constraints on this graph, once per process (idempotent across processes)."""
        if name == CTL_GRAPH or name in self._engine_done:
            return
        async with self._lock:
            fut = self._engine.get(name)
            if fut is None:
                async def work() -> None:
                    g = RetryingGraph(self.client.select_graph(name))
                    for label, prop in ENGINE_INDEXES:
                        try:
                            await g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
                        except Exception as e:
                            if "already indexed" not in str(e).lower() and "already exists" not in str(e).lower():
                                raise
                    await self._engine_extras(name, g)
                fut = self._engine[name] = asyncio.ensure_future(work())
        await fut
        self._engine_done.add(name)

    async def drop_tenant(self, tenant: str) -> None:
        name = self.graph_name(tenant)
        try:
            await self.client.select_graph(name).delete()
        except Exception:
            pass
        self._ready.pop(name, None)
        self._engine.pop(name, None)
        self._engine_done.discard(name)

    async def list_tenant_graphs(self) -> list[str]:
        return sorted(g[len("mem__"):] for g in await self.client.list_graphs() if g.startswith("mem__"))

    async def close(self) -> None:
        await self.client.aclose() if hasattr(self.client, "aclose") else None
