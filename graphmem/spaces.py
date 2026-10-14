"""Shared spaces: the only sanctioned way for memory to cross a tenant boundary.

  (Agent)-[:MEMBER {scopes}]->(Space)        in `ctl`   (read | write | admin)
  (Tenant)-[:PUBLISHED_TO]->(Space)          in `ctl`   (so a forget can find every copy)
  graph `shared__<space>`: Fact copies carrying src_tenant / src_fact / published_by, linked to Entities.

Rules enforced here
- Publishing is explicit and per fact. Needs 'read' on the source tenant AND 'write' on the space.
- Only the fact triple and validity are copied. Source episodes (raw conversation) are never copied.
- Space members can read the space but have no access to any contributing tenant.
- Forgetting a fact in its tenant (`GraphMem.forget_fact`) deletes every published copy.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .db import CTL_GRAPH, new_id, now_ms, validate_tenant
from .memory import TenantMemory
from .policy import GraphMem, PermissionDenied, SCOPES


class SpaceView:
    """Read-only view of a space: graph recall and fact history, nothing else."""

    def __init__(self, mem: TenantMemory):
        self._m = mem

    async def recall(self, query: str, **kw):
        return await self._m.recall(query, **kw)

    async def fact_history(self, subject: str, predicate: str):
        return await self._m.fact_history(subject, predicate)

    async def stats(self):
        return await self._m.stats()


async def create_space(gm: GraphMem, space: str) -> None:
    validate_tenant(space)
    g = await gm._ctl()
    await g.query("MERGE (s:Space {id:$s}) ON CREATE SET s.created_at=$ts", {"s": space, "ts": now_ms()})
    await gm.db.graph(gm.db.space_graph_name(space))


async def add_member(gm: GraphMem, agent: str, space: str, scopes: tuple[str, ...] = ("read",)) -> None:
    bad = set(scopes) - set(SCOPES)
    if bad:
        raise ValueError(f"unknown scopes {bad}")
    await create_space(gm, space)
    g = await gm._ctl()
    await g.query("MERGE (a:Agent {id:$a}) WITH a MATCH (s:Space {id:$s}) MERGE (a)-[m:MEMBER]->(s) "
                  "SET m.scopes=$sc, m.at=$ts", {"a": agent, "s": space, "sc": list(scopes), "ts": now_ms()})


async def remove_member(gm: GraphMem, agent: str, space: str) -> None:
    g = await gm._ctl()
    await g.query("MATCH (:Agent {id:$a})-[m:MEMBER]->(:Space {id:$s}) DELETE m", {"a": agent, "s": space})


async def _space_scopes(gm: GraphMem, agent: str, space: str) -> set[str]:
    g = await gm._ctl()
    rows = (await g.query("MATCH (:Agent {id:$a})-[m:MEMBER]->(:Space {id:$s}) RETURN m.scopes",
                          {"a": agent, "s": space})).result_set
    return set(rows[0][0]) if rows else set()


async def _need(gm: GraphMem, agent: str, space: str, scope: str) -> None:
    have = await _space_scopes(gm, agent, space)
    if scope not in have and "admin" not in have:
        raise PermissionDenied(f"agent {agent!r} lacks {scope!r} on space {space!r}")


def open_space(gm: GraphMem, agent: str, space: str) -> SpaceView:
    validate_tenant(space)

    async def guard(scope: str) -> None:
        await _need(gm, agent, space, "read")

    return SpaceView(TenantMemory(gm.db, space, agent, guard, graph=gm.db.space_graph_name(space)))


async def publish(gm: GraphMem, agent: str, tenant: str, space: str, fact_ids: Iterable[str]) -> dict:
    """Copy the chosen facts (and their current validity) into the space. Re-publishing refreshes validity, so a fact
    superseded in its tenant is closed in the space too."""
    ids = list(fact_ids)
    await _need(gm, agent, space, "write")
    src = gm.open(agent, tenant)                                   # also enforces 'read' on the tenant
    rows = await src._q(
        """MATCH (f:Fact) WHERE f.id IN $ids AND coalesce(f.forgotten, false) = false
           RETURN f.id, f.skey, f.sname, f.pred, f.okey, f.otext, f.cur, f.valid_from, f.valid_to, f.support, f.conf""",
        {"ids": ids}, scope="read")
    sg = await gm.db.graph(gm.db.space_graph_name(space))
    ts, published = now_ms(), []
    for r in rows:
        await sg.query(
            """
            MERGE (s:Entity {key:$skey}) ON CREATE SET s.name=$sname
            MERGE (o:Entity {key:$okey}) ON CREATE SET o.name=$otext
            MERGE (f:Fact {src_tenant:$tenant, src_fact:$sid})
              ON CREATE SET f.id=$nid, f.published_at=$ts
            SET f.skey=$skey, f.sname=$sname, f.pred=$pred, f.okey=$okey, f.otext=$otext, f.cur=$cur,
                f.valid_from=$vf, f.valid_to=$vt, f.support=$sup, f.conf=$conf, f.published_by=$agent
            MERGE (f)-[:SUBJECT]->(s)
            MERGE (f)-[:OBJECT]->(o)
            """,
            {"skey": r[1], "sname": r[2], "pred": r[3], "okey": r[4], "otext": r[5], "cur": bool(r[6]), "vf": r[7],
             "vt": r[8], "sup": r[9], "conf": r[10], "tenant": tenant, "sid": r[0], "nid": new_id("fct"), "ts": ts,
             "agent": agent})
        published.append(r[0])
    cg = await gm._ctl()
    await cg.query("MATCH (t:Tenant {id:$t}), (s:Space {id:$s}) MERGE (t)-[:PUBLISHED_TO]->(s)",
                   {"t": tenant, "s": space})
    return {"published": published, "skipped": sorted(set(ids) - set(published))}


async def forget_fact(gm: GraphMem, agent: str, tenant: str, fact_id: str, reason: str,
                      redact_sources: bool = False) -> dict:
    """Forget in the tenant, then delete every published copy from every space the tenant published to."""
    out = await gm.open(agent, tenant).forget_fact(fact_id, reason, redact_sources=redact_sources)
    cg = await gm._ctl()
    spaces = [r[0] for r in (await cg.query("MATCH (:Tenant {id:$t})-[:PUBLISHED_TO]->(s:Space) RETURN s.id",
                                            {"t": tenant})).result_set]
    removed = 0
    for sp in spaces:
        sg = await gm.db.graph(gm.db.space_graph_name(sp))
        r = (await sg.query("MATCH (f:Fact {src_tenant:$t, src_fact:$f}) WITH f, f.skey AS a, f.okey AS b "
                            "DETACH DELETE f RETURN count(*), collect(a)+collect(b)",
                            {"t": tenant, "f": fact_id})).result_set
        n, keys = r[0][0], r[0][1]
        removed += n
        if keys:
            await sg.query("MATCH (e:Entity) WHERE e.key IN $k AND NOT (e)<-[:SUBJECT|OBJECT]-(:Fact) DELETE e",
                           {"k": keys})
    out["space_copies_removed"] = removed
    return out
