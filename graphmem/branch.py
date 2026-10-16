"""Branch / dry-run / merge for tenant memory, built on FalkorDB GRAPH.COPY.

  fork(agent, tenant)        snapshot the tenant graph into `fork__<tenant>__<id>` (isolated; source stays writable)
  open_fork(agent, fork_id)  a TenantMemory bound to the fork: same API, writes never touch the tenant graph
  merge(..., apply=False)    DRY RUN: what would be applied, what conflicts, which plans would be stale
  merge(..., apply=True)     replay the fork's new items into the tenant graph
  discard(...)               delete the fork

What counts as "new in the fork": episodes, facts, skills, runs, tasks and plans stamped at/after the fork time. Changes a fork
makes to items that already existed (re-weighting a skill, changing a task's status, reinforcing an old fact) are NOT merged;
fork work is additive by design. Conflict rules at merge time:
  - exclusive fact (one value at a time): conflict if the tenant graph changed that (subject, predicate) to a different value
    after the snapshot. on_conflict='skip' (default) leaves the tenant's value; 'overwrite' applies the fork's value as newest.
  - plan: 'needs_rebase' if any input fact (or anything it was inferred from) is outdated in the tenant graph.
Merge is not one atomic transaction (FalkorDB has no multi-query transactions): a failure midway marks the fork 'merge_failed'
and reports what was applied. Re-merging a failed fork is refused; inspect, then discard.

Cost: GRAPH.COPY is linear in graph size (measured ~10 ms @1k nodes, ~0.4 s @100k, ~1 s @300k nodes), so forks are meant per
task/handoff, not per tiny action; forking is refused above MAX_FORK_NODES and per-tenant open forks are capped.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import uuid
from typing import Optional

from .db import Overloaded, new_id, norm, now_ms, validate_tenant
from .memory import TenantMemory
from .policy import GraphMem, PermissionDenied

MAX_OPEN_FORKS = int(os.getenv("GRAPHMEM_MAX_FORKS", "5"))
MAX_FORK_NODES = int(os.getenv("GRAPHMEM_MAX_FORK_NODES", "500000"))


class ForkError(Exception):
    pass


async def copy_graph(client, src: str, dst: str, attempts: int = 6) -> None:
    """GRAPH.COPY forks the database process, and the operating system can refuse a fork for a moment (memory pressure, another save
    running). Nothing has been copied when it does, so asking again is safe; after a few tries the caller is told to come back shortly."""
    delay = 0.1
    for attempt in range(attempts):
        try:
            await client.execute_command("GRAPH.COPY", src, dst)
            return
        except Exception as e:  # noqa: BLE001
            if "could not fork" not in str(e).lower():
                raise
            if attempt == attempts - 1:
                raise Overloaded("the database could not take a copy just now; try again shortly") from e
            await asyncio.sleep(delay * (0.5 + random.random()))
            delay *= 2


async def _need(gm: GraphMem, agent: str, tenant: str, scope: str) -> None:
    have = await gm.scopes(agent, tenant)
    if scope not in have and "admin" not in have:
        raise PermissionDenied(f"agent {agent!r} lacks {scope!r} on tenant {tenant!r}")


async def _fork_row(gm: GraphMem, fork_id: str) -> dict:
    g = await gm._ctl()
    rows = (await g.query("MATCH (f:Fork {id:$id}) RETURN f.tenant, f.graph, f.snap_ts, f.fork_ts, f.status, f.owner, f.label",
                          {"id": fork_id})).result_set
    if not rows:
        raise KeyError(fork_id)
    r = rows[0]
    return dict(id=fork_id, tenant=r[0], graph=r[1], snap_ts=r[2], fork_ts=r[3], status=r[4], owner=r[5], label=r[6])


async def fork(gm: GraphMem, agent: str, tenant: str, label: str = "") -> dict:
    validate_tenant(tenant)
    await _need(gm, agent, tenant, "read")
    ctl = await gm._ctl()
    open_n = (await ctl.query("MATCH (f:Fork {tenant:$t, status:'open'}) RETURN count(f)", {"t": tenant})).result_set[0][0]
    if open_n >= MAX_OPEN_FORKS:
        raise ForkError(f"tenant {tenant!r} already has {open_n} open forks (limit {MAX_OPEN_FORKS}); discard or merge one")
    src = await gm.db.tenant_graph(tenant)
    nodes = (await src.query("MATCH (n) RETURN count(n)")).result_set[0][0]
    if nodes > MAX_FORK_NODES:
        raise ForkError(f"graph has {nodes} nodes, above the fork limit {MAX_FORK_NODES}")
    fid = uuid.uuid4().hex[:12]
    name = gm.db.fork_graph_name(tenant, fid)
    snap_ts = now_ms()                                    # taken before the copy: writes at/after this are "since the fork"
    await copy_graph(gm.db.client, gm.db.graph_name(tenant), name)
    fork_ts = now_ms()                                    # taken after the copy: items stamped >= this were made in the fork
    await ctl.query("CREATE (:Fork {id:$id, tenant:$t, graph:$g, snap_ts:$s, fork_ts:$f, status:'open', owner:$o, label:$l, at:$f})",
                    {"id": fid, "t": tenant, "g": name, "s": snap_ts, "f": fork_ts, "o": agent, "l": label[:120]})
    return dict(id=fid, tenant=tenant, graph=name, nodes=nodes, snapshot_ms=snap_ts, copy_ms=fork_ts - snap_ts)


async def open_fork(gm: GraphMem, agent: str, fork_id: str) -> TenantMemory:
    row = await _fork_row(gm, fork_id)
    if row["status"] != "open":
        raise ForkError(f"fork {fork_id} is {row['status']}")
    tenant = row["tenant"]

    async def guard(scope: str) -> None:
        await _need(gm, agent, tenant, scope)

    return TenantMemory(gm.db, tenant, agent, guard, graph=row["graph"], extractor=gm.extractor)


async def list_forks(gm: GraphMem, agent: str, tenant: str) -> list[dict]:
    await _need(gm, agent, tenant, "read")
    g = await gm._ctl()
    rows = (await g.query("MATCH (f:Fork {tenant:$t}) RETURN f.id, f.status, f.owner, f.label, f.at ORDER BY f.at DESC",
                          {"t": tenant})).result_set
    return [dict(id=r[0], status=r[1], owner=r[2], label=r[3], at=r[4]) for r in rows]


async def discard(gm: GraphMem, agent: str, fork_id: str) -> None:
    row = await _fork_row(gm, fork_id)
    await _need(gm, agent, row["tenant"], "write")
    try:
        await gm.db.client.select_graph(row["graph"]).delete()
    except Exception:
        pass
    gm.db._ready.pop(row["graph"], None)
    await (await gm._ctl()).query("MATCH (f:Fork {id:$id}) SET f.status='discarded'", {"id": fork_id})


async def _collect(fm: TenantMemory, t: int) -> dict:
    q = lambda c, p=None: fm._q(c, {"t": t, **(p or {})}, scope="read", checked=True)
    return dict(
        episodes=await q("MATCH (e:Episode) WHERE e.ts >= $t RETURN e.id, e.session, e.role, e.content, e.agent, e.ts, e.redacted "
                         "ORDER BY e.ts, e.seq"),
        facts=await q("MATCH (f:Fact) WHERE f.recorded_at >= $t AND coalesce(f.forgotten,false)=false "
                      "RETURN f.id, f.sname, f.pred, f.otext, f.exclusive, f.valid_from, f.conf, f.agent, f.recorded_at "
                      "ORDER BY f.recorded_at"),
        fact_src=await q("MATCH (f:Fact)-[:EXTRACTED_FROM]->(e:Episode) WHERE f.recorded_at >= $t RETURN f.id, e.id"),
        fact_inf=await q("MATCH (f:Fact)-[:INFERRED_FROM]->(u:Fact) WHERE f.recorded_at >= $t RETURN f.id, u.id"),
        skills=await q("MATCH (s:Skill) WHERE s.created_at >= $t RETURN s.name, s.description, s.steps, s.tags"),
        runs=await q("MATCH (r:Run)-[:OF]->(s:Skill) WHERE r.ts >= $t RETURN r.id, s.name, r.success, r.notes, r.agent, r.ts "
                     "ORDER BY r.ts"),
        tasks=await q("MATCH (t:Task) WHERE t.created_at >= $t RETURN t.id, t.title, t.payload"),
        plans=await q("MATCH (p:Plan)-[:FOR]->(t:Task) WHERE p.created_at >= $t RETURN p.id, t.id, p.steps, p.agent"),
        plan_in=await q("MATCH (p:Plan)-[:DERIVED_FROM]->(f:Fact) WHERE p.created_at >= $t RETURN p.id, f.id"),
    )


async def merge(gm: GraphMem, agent: str, fork_id: str, *, apply: bool = False, on_conflict: str = "skip",
                keep_fork: bool = False) -> dict:
    if on_conflict not in ("skip", "overwrite"):
        raise ValueError("on_conflict must be 'skip' or 'overwrite'")
    row = await _fork_row(gm, fork_id)
    if row["status"] != "open":
        raise ForkError(f"fork {fork_id} is {row['status']}")
    tenant = row["tenant"]
    await _need(gm, agent, tenant, "write" if apply else "read")
    fm = await open_fork(gm, agent, fork_id)
    base = gm.open(agent, tenant)
    d = await _collect(fm, row["fork_ts"])
    new_fact_ids = {f[0] for f in d["facts"]}

    # ---- conflicts: exclusive facts whose (subject, predicate) the tenant changed to another value since the snapshot
    conflicts, conflicted_fact_ids = [], set()
    for f in d["facts"]:
        fid, sname, pred, otext, excl = f[0], f[1], f[2], f[3], f[4]
        if not excl:
            continue
        r = await base._q("MATCH (b:Fact {skey:$s, pred:$p, cur:true}) WHERE b.recorded_at >= $snap AND b.okey <> $o "
                          "RETURN b.id, b.otext", {"s": norm(sname), "p": pred, "o": norm(otext), "snap": row["snap_ts"]},
                          scope="read", checked=True)
        if r:
            conflicts.append(dict(kind="fact", subject=sname, predicate=pred, fork_value=otext, tenant_value=r[0][1],
                                  fork_fact=fid, tenant_fact=r[0][0]))
            conflicted_fact_ids.add(fid)

    # ---- plans whose inputs are already outdated in the tenant graph
    plan_inputs: dict[str, list[str]] = {}
    for pid, fid in d["plan_in"]:
        plan_inputs.setdefault(pid, []).append(fid)
    needs_rebase = []
    for pid, inputs in plan_inputs.items():
        old_inputs = [i for i in inputs if i not in new_fact_ids]
        if not old_inputs:
            continue
        r = await base._q(
            """MATCH (f:Fact) WHERE f.id IN $ids
               OPTIONAL MATCH (f)-[:INFERRED_FROM*1..8]->(u:Fact {cur:false})
               WITH f, collect(u.id) AS ups
               WHERE f.cur = false OR coalesce(f.forgotten,false) = true OR size(ups) > 0
               RETURN f.id, f.sname, f.pred, f.otext, ups""", {"ids": old_inputs}, scope="read", checked=True)
        if r:
            needs_rebase.append(dict(plan=pid, outdated_inputs=[dict(fact=x[0], text=f"{x[1]} {x[2]} {x[3]}",
                                                                      upstream=x[4]) for x in r]))

    report = dict(fork=fork_id, tenant=tenant, applied=False, on_conflict=on_conflict,
                  would_apply=dict(episodes=len(d["episodes"]), facts=len(d["facts"]) - (len(conflicted_fact_ids) if on_conflict == "skip" else 0),
                                   skills=len(d["skills"]), runs=len(d["runs"]), tasks=len(d["tasks"]), plans=len(d["plans"])),
                  conflicts=conflicts, needs_rebase=needs_rebase)
    if not apply:
        return report

    ctl = await gm._ctl()
    await ctl.query("MATCH (f:Fork {id:$id}) SET f.status='merging'", {"id": fork_id})
    ep_map, fact_map, task_map = {}, {}, {}
    applied = dict(episodes=0, facts=0, skills=0, runs=0, tasks=0, plans=0)
    try:
        for e in d["episodes"]:
            r = await base.add_episode(e[1], e[2], e[3] or "", agent=e[4], at=e[5])
            ep_map[e[0]] = r["id"]
            applied["episodes"] += 1
        for s in d["skills"]:
            await base.add_skill(s[0], s[1] or "", json.loads(s[2] or "[]"), tags=s[3] or [])
            applied["skills"] += 1
        srcs, infs = {}, {}
        for fid, eid in d["fact_src"]:
            srcs.setdefault(fid, []).append(ep_map.get(eid, eid))
        for fid, uid in d["fact_inf"]:
            infs.setdefault(fid, []).append(fact_map.get(uid, uid))
        for f in d["facts"]:
            fid = f[0]
            if fid in conflicted_fact_ids and on_conflict == "skip":
                continue
            at = now_ms() if fid in conflicted_fact_ids else f[8]
            r = await base.assert_fact(f[1], f[2], f[3], sources=srcs.get(fid, []), conf=f[6] or 1.0, exclusive=bool(f[4]),
                                       valid_from=(at if fid in conflicted_fact_ids else f[5]), agent=f[7], at=at,
                                       inferred_from=[fact_map.get(u, u) for u in infs.get(fid, [])])
            fact_map[fid] = r["id"]
            applied["facts"] += 1
        for t in d["tasks"]:
            task_map[t[0]] = await base.create_task(t[1], json.loads(t[2] or "{}"))
            applied["tasks"] += 1
        new_plans = []
        for p in d["plans"]:
            if p[1] not in task_map and not await base.get_task(p[1]):
                continue
            pid = await base.create_plan(task_map.get(p[1], p[1]), json.loads(p[2] or "[]"),
                                         derived_from=[fact_map.get(i, i) for i in plan_inputs.get(p[0], [])])
            new_plans.append(pid)
            applied["plans"] += 1
        for r in d["runs"]:
            try:
                await base.record_run(r[1], bool(r[2]), notes=r[3] or "", agent=r[4])
                applied["runs"] += 1
            except KeyError:
                pass
        stale_after = [dict(plan=pid, changes=c["changes"]) for pid in new_plans
                       if (c := await base.check_plan(pid))["stale"]]
    except Exception as e:
        await ctl.query("MATCH (f:Fork {id:$id}) SET f.status='merge_failed'", {"id": fork_id})
        raise ForkError(f"merge failed after applying {applied}: {type(e).__name__}: {e}") from e
    await ctl.query("MATCH (f:Fork {id:$id}) SET f.status='merged', f.merged_at=$ts", {"id": fork_id, "ts": now_ms()})
    if not keep_fork:
        try:
            await gm.db.client.select_graph(row["graph"]).delete()
        except Exception:
            pass
        gm.db._ready.pop(row["graph"], None)
    report.update(applied=applied, plans_stale_after_merge=stale_after, status="merged")
    return report
