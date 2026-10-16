"""A read-only look at the database for the admin plane: what it is running, which caps are in force, how many graphs of each
kind it holds, how much memory it uses, and the slowest queries it has seen. Nothing here writes, and no user text leaves it:
FalkorDB's slow log keeps the query together with its parameters, so every string value is removed before an entry is shown."""
from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Any

from .db import Db

CONFIG_KEYS = ["TIMEOUT_DEFAULT", "TIMEOUT_MAX", "QUERY_MEM_CAPACITY", "MAX_QUEUED_QUERIES", "THREAD_COUNT", "CACHE_SIZE"]
KINDS = [("mem__", "circles_and_tenants"), ("fork__", "forks"), ("shared__", "shared_spaces")]
MAX_GRAPHS_SCANNED = 400            # the slow log is kept per graph; a very large server is sampled rather than scanned for ever
STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
PARAM = re.compile(r"\s*`?\w+`?=")


def _end_of_value(t: str, i: int) -> int:
    """Where a parameter value that starts at t[i] ends (strings are already gone, so brackets are plain)."""
    while i < len(t) and t[i] == " ":
        i += 1
    if i < len(t) and t[i] in "[{":
        depth = 0
        while i < len(t):
            depth += t[i] in "[{"
            depth -= t[i] in "]}"
            i += 1
            if depth == 0:
                break
        return i
    while i < len(t) and t[i] != " ":
        i += 1
    return i


def redact(text: str, limit: int = 240) -> str:
    """The shape of a logged query: string values replaced, the parameter header dropped, whitespace tidied, cut to `limit`."""
    t = STRING.sub('"…"', str(text))
    if t.startswith("CYPHER "):
        i = 7
        while True:
            m = PARAM.match(t, i)
            if not m:
                break
            i = _end_of_value(t, m.end())
        t = t[i:]
    t = " ".join(t.split())
    return t if len(t) <= limit else t[:limit - 1] + "…"


def _info(raw: Any) -> dict:
    if isinstance(raw, dict):                      # redis-py already parses INFO into a dict
        return {str(k): str(v) for k, v in raw.items()}
    text = raw.decode() if isinstance(raw, bytes) else str(raw)
    return {k: v for k, _, v in (line.partition(":") for line in text.splitlines() if ":" in line and not line.startswith("#"))}


async def db_stats(db: Db, slowest: int = 10) -> dict:
    cmd = db.client.execute_command
    server = _info(await cmd("INFO", "server"))
    mem = _info(await cmd("INFO", "memory"))
    persist = _info(await cmd("INFO", "persistence"))
    limits = {}
    for key in CONFIG_KEYS:
        try:
            limits[key] = int((await cmd("GRAPH.CONFIG", "GET", key))[1])
        except Exception:  # noqa: BLE001
            limits[key] = None
    names = sorted(await db.client.list_graphs())
    kinds = {label: sum(n.startswith(prefix) for n in names) for prefix, label in KINDS}
    kinds["other"] = len(names) - sum(kinds.values())
    used = int(mem.get("used_memory", 0))
    scanned = names[:MAX_GRAPHS_SCANNED]
    gate = asyncio.Semaphore(16)

    async def slow(name: str):
        async with gate:
            try:
                return [(name, e) for e in await cmd("GRAPH.SLOWLOG", name)]
            except Exception:  # noqa: BLE001
                return []

    rows = [r for part in await asyncio.gather(*(slow(n) for n in scanned)) for r in part]
    rows.sort(key=lambda r: -float(r[1][3]))
    return {
        "server": {"version": server.get("redis_version"), "uptime_seconds": int(server.get("uptime_in_seconds", 0)),
                   "memory_bytes": used, "memory_human": mem.get("used_memory_human"),
                   "append_only_file": persist.get("aof_enabled") == "1", "last_snapshot_ok": persist.get("rdb_last_bgsave_status") == "ok"},
        "caps": limits,                                   # 0 means no cap
        "graphs": {"total": len(names), **kinds, "average_bytes_each": used // len(names) if names else 0,
                   "note": "average of everything in the server, including the shared reference graph; a rough guide only"},
        "slowest": [{"graph": g, "at": dt.datetime.fromtimestamp(int(e[0]), dt.timezone.utc).isoformat(timespec="seconds"),
                     "command": str(e[1]), "ms": round(float(e[3]), 2), "query": redact(e[2])} for g, e in rows[:max(1, min(slowest, 50))]],
        "slowest_scanned": f"{len(scanned)} of {len(names)} graphs",
    }
