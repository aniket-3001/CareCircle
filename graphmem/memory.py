"""Per-tenant memory engine. Every operation is one or a few Cypher queries on the tenant's own graph.

Graph model (see docs/DESIGN_SKETCH.md)
  (Episode)-[:IN_SESSION]->(Session)            (Episode)-[:NEXT]->(Episode)
  (Fact)-[:SUBJECT|OBJECT]->(Entity)            (Fact)-[:EXTRACTED_FROM]->(Episode)
  (Fact)-[:SUPERSEDES]->(Fact)                  (Tombstone)-[:TOMBSTONES]->(Fact)
  (Run)-[:OF]->(Skill)   (Run)-[:FOR]->(Task)   (Skill)-[:LEARNED_FROM]->(Episode)
  (Task)-[:CLAIMED_BY|HANDED_OFF]->(Agent)      (Plan)-[:FOR]->(Task)   (Plan)-[:REVISES]->(Plan)
  (Plan)-[:DERIVED_FROM]->(Fact)                (Decision)-[:USED]->(Fact|Episode|Plan|Skill|...)

Concurrency model: FalkorDB serializes write queries per graph and every query is atomic, so all state
transitions (claims, handoffs, fact create-or-reinforce) are single queries guarded by a WHERE on current state.
"""
from __future__ import annotations

import json
import math
import re
from typing import Awaitable, Callable, Iterable, Optional

from .db import Db, new_id, norm, now_ms
from .extract import RuleExtractor

STOP = set("a an and are as at be by did do does for from has have how i in is it of on or that the this to was "
           "were what when where which who whom why will with you your my me we our about tell".split())

# id prefix -> node label, so id lookups use the label's index instead of scanning every node
PREFIX_LABEL = {"ep": "Episode", "fct": "Fact", "pln": "Plan", "skl": "Skill", "run": "Run", "tsk": "Task",
                "dec": "Decision", "ses": "Session"}

Guard = Callable[[str], Awaitable[None]]


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) >= 3 and t not in STOP]


def _props(node) -> dict:
    return dict(node.properties) if hasattr(node, "properties") else node


class TenantMemory:
    def __init__(self, db: Db, tenant: str, agent: str, guard: Optional[Guard] = None, graph: Optional[str] = None,
                 extractor=None):
        self.db, self.tenant, self.agent, self._guard, self._graph = db, tenant, agent, guard, graph
        self.extractor = extractor or RuleExtractor()

    # ---------------------------------------------------------------- plumbing
    async def _q(self, cypher: str, params: Optional[dict] = None, scope: str = "write", *, checked: bool = False):
        """Run one Cypher query on the tenant graph. Multi-query operations authorize once up front and pass
        checked=True to the rest, so a policy lookup is not repeated per query."""
        if self._guard and not checked:
            await self._guard(scope)
        g = await (self.db.graph(self._graph) if self._graph else self.db.tenant_graph(self.tenant))
        return (await g.query(cypher, params or {})).result_set

    # ---------------------------------------------------------------- episodic
    async def add_episode(self, session: str, role: str, content: str, *, agent: Optional[str] = None,
                          at: Optional[int] = None) -> dict:
        """Append an immutable event to a session. Ordering (seq + NEXT edge) is assigned atomically in-graph."""
        ts, eid = at or now_ms(), new_id("ep")
        rows = await self._q(
            """
            MERGE (s:Session {id:$sid}) ON CREATE SET s.agent=$agent, s.started_at=$ts, s.n=0
            WITH s, s.last AS prev_id, s.n + 1 AS seq
            SET s.n = seq, s.last = $eid, s.last_at = $ts
            CREATE (e:Episode {id:$eid, seq:seq, session:$sid, role:$role, content:$content, agent:$agent,
                               ts:$ts, redacted:false})
            CREATE (e)-[:IN_SESSION]->(s)
            WITH e, prev_id
            OPTIONAL MATCH (prev:Episode {id:prev_id})
            FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | CREATE (prev)-[:NEXT]->(e))
            RETURN e.id, e.seq
            """,
            {"sid": session, "eid": eid, "role": role, "content": content, "agent": agent or self.agent, "ts": ts},
        )
        return {"id": rows[0][0], "seq": rows[0][1], "session": session}

    async def ingest(self, session: str, role: str, content: str) -> dict:
        """Store a message as an episode, extract facts from it, and link each fact to that episode.
        Extraction failures (e.g. an unreachable LLM) never lose the message: the episode is stored regardless."""
        ep = await self.add_episode(session, role, content)
        facts, error = [], None
        try:
            triples = await self.extractor.extract(content)
        except Exception as e:  # network/model failure: keep the episode, report the problem
            triples, error = [], f"{type(e).__name__}: {e}"
        for t in triples:
            r = await self.assert_fact(t.subject, t.predicate, t.obj, sources=[ep["id"]], exclusive=t.exclusive)
            facts.append(dict(id=r["id"], subject=t.subject, predicate=t.predicate, object=t.obj,
                              created=r["created"], superseded=r["superseded"]))
        return {"episode": ep, "facts": facts, "extraction_error": error}

    async def history(self, session: str, limit: int = 50, before_seq: Optional[int] = None) -> list[dict]:
        """Persistent conversation history, oldest first, newest `limit` turns (optionally before a seq)."""
        rows = await self._q(
            """
            MATCH (e:Episode)-[:IN_SESSION]->(:Session {id:$sid})
            WHERE $before IS NULL OR e.seq < $before
            RETURN e.id, e.seq, e.role, e.content, e.agent, e.ts, e.redacted
            ORDER BY e.seq DESC LIMIT $n
            """,
            {"sid": session, "before": before_seq, "n": limit}, scope="read")
        out = [dict(id=r[0], seq=r[1], role=r[2], content=r[3], agent=r[4], ts=r[5], redacted=r[6]) for r in rows]
        return out[::-1]

    async def sessions(self, limit: int = 50) -> list[dict]:
        rows = await self._q("MATCH (s:Session) RETURN s.id, s.agent, s.started_at, s.n, s.last_at "
                             "ORDER BY s.last_at DESC LIMIT $n", {"n": limit}, scope="read")
        return [dict(id=r[0], agent=r[1], started_at=r[2], turns=r[3], last_at=r[4]) for r in rows]

    async def search_episodes(self, query: str, limit: int = 10) -> list[dict]:
        toks = tokens(query)
        if not toks:
            return []
        rows = await self._q(
            """
            MATCH (e:Episode) WHERE e.redacted = false AND any(t IN $toks WHERE toLower(e.content) CONTAINS t)
            RETURN e.id, e.session, e.seq, e.role, e.content, e.ts
            ORDER BY e.ts DESC LIMIT $n
            """, {"toks": toks, "n": limit * 5}, scope="read")
        scored = []
        for r in rows:
            low = (r[4] or "").lower()
            scored.append((sum(t in low for t in toks) / len(toks), r))
        scored.sort(key=lambda x: (-x[0], -x[1][5]))
        return [dict(id=r[0], session=r[1], seq=r[2], role=r[3], content=r[4], ts=r[5], score=round(s, 3))
                for s, r in scored[:limit]]

    # ---------------------------------------------------------------- semantic
    async def assert_fact(self, subject: str, predicate: str, obj: str, *, sources: Iterable[str] = (),
                          conf: float = 1.0, exclusive: bool = False, valid_from: Optional[int] = None,
                          agent: Optional[str] = None, at: Optional[int] = None,
                          inferred_from: Iterable[str] = ()) -> dict:
        """Create-or-reinforce a fact. `exclusive` predicates (one value at a time, e.g. 'lives_in') supersede
        the previous current value instead of coexisting; the old fact is kept, closed, and linked via SUPERSEDES."""
        ts = at or now_ms()
        fid, skey, okey, pred = new_id("fct"), norm(subject), norm(obj), norm(predicate)
        rows = await self._q(
            """
            MERGE (s:Entity {key:$skey}) ON CREATE SET s.name=$sname, s.created_at=$ts
            MERGE (o:Entity {key:$okey}) ON CREATE SET o.name=$oname, o.created_at=$ts
            MERGE (f:Fact {skey:$skey, pred:$pred, okey:$okey, cur:true})
              ON CREATE SET f.id=$fid, f.sname=$sname, f.otext=$oname, f.valid_from=$vf, f.recorded_at=$ts,
                            f.support=0, f.conf=$conf, f.exclusive=$excl, f.agent=$agent
            SET f.support = f.support + 1, f.last_seen = $ts
            MERGE (f)-[:SUBJECT]->(s)
            MERGE (f)-[:OBJECT]->(o)
            RETURN f.id, f.support
            """,
            {"skey": skey, "okey": okey, "pred": pred, "sname": subject.strip(), "oname": obj.strip(), "ts": ts,
             "fid": fid, "vf": valid_from or ts, "conf": float(conf), "excl": exclusive, "agent": agent or self.agent})
        fid, support = rows[0][0], rows[0][1]
        src = list(sources)
        if src:
            await self._q("MATCH (f:Fact {id:$fid}) UNWIND $src AS eid MATCH (e:Episode {id:eid}) "
                          "MERGE (f)-[:EXTRACTED_FROM]->(e)", {"fid": fid, "src": src})
        inf = list(inferred_from)
        if inf:  # derived knowledge: this fact is only as valid as the facts it was inferred from
            await self._q("MATCH (f:Fact {id:$fid}) UNWIND $inf AS iid MATCH (u:Fact {id:iid}) "
                          "WHERE u.id <> f.id MERGE (f)-[:INFERRED_FROM]->(u)", {"fid": fid, "inf": inf})
        superseded: list[str] = []
        if exclusive:
            # Only strictly older facts are closed, so two racing writers converge on the newer one.
            r = await self._q(
                """
                MATCH (f:Fact {id:$fid})-[:SUBJECT]->(s:Entity)
                MATCH (s)<-[:SUBJECT]-(old:Fact {pred:$pred, cur:true})
                WHERE old.id <> f.id AND old.okey <> f.okey
                  AND (old.recorded_at < f.recorded_at OR (old.recorded_at = f.recorded_at AND old.id < f.id))
                SET old.cur = false, old.valid_to = f.valid_from, old.invalidated_by = f.id
                CREATE (f)-[:SUPERSEDES {at:$ts}]->(old)
                RETURN old.id
                """, {"fid": fid, "pred": pred, "ts": ts})
            superseded = [x[0] for x in r]
        return {"id": fid, "created": support == 1, "support": support, "superseded": superseded}

    async def recall(self, query: str, *, as_of: Optional[int] = None, hops: int = 2, limit: int = 10) -> list[dict]:
        """Entity-anchored graph recall. Every result carries its provenance (source episodes) and the graph path
        that reached it. `as_of` answers 'what did we believe at time T'."""
        toks = tokens(query)
        if not toks:
            return []
        if self._guard:
            await self._guard("read")
        asof = as_of or now_ms()
        valid = "{f}.valid_from <= $asof AND ({f}.valid_to IS NULL OR {f}.valid_to > $asof)"
        ret = "{f}.id, {f}.sname, {f}.pred, {f}.otext, {f}.support, {f}.conf, {f}.valid_from, {f}.valid_to, {f}.cur"
        found: dict[str, dict] = {}

        rows = await self._q(
            f"""MATCH (en:Entity) WHERE any(t IN $toks WHERE en.key CONTAINS t)
                WITH en  // FalkorDB: without this WITH the next MATCH silently returns no rows
                MATCH (en)<-[:SUBJECT|OBJECT]-(f:Fact) WHERE {valid.format(f='f')}
                RETURN {ret.format(f='f')}, en.name, en.key""", {"toks": toks, "asof": asof}, scope="read", checked=True)
        for r in rows:
            cov = sum(t in r[10] for t in toks) / len(toks)
            found[r[0]] = self._fact_row(r, hop=1, path=f"{r[9]} -> [{r[1]} {r[2]} {r[3]}]", base=1.0 + cov)

        if hops >= 2:
            rows = await self._q(
                f"""MATCH (en:Entity) WHERE any(t IN $toks WHERE en.key CONTAINS t)
                    WITH en
                    MATCH (en)<-[:SUBJECT|OBJECT]-(f1:Fact)-[:SUBJECT|OBJECT]->(mid:Entity)
                          <-[:SUBJECT|OBJECT]-(f2:Fact)
                    WHERE mid.key <> en.key AND f2.id <> f1.id AND {valid.format(f='f1')} AND {valid.format(f='f2')}
                    RETURN {ret.format(f='f2')}, en.name, mid.name, f1.sname, f1.pred, f1.otext""",
                {"toks": toks, "asof": asof}, scope="read", checked=True)
            for r in rows:
                if r[0] in found:
                    continue
                path =f"{r[9]} -> [{r[11]} {r[12]} {r[13]}] -> {r[10]} -> [{r[1]} {r[2]} {r[3]}]"
                found[r[0]] = self._fact_row(r, hop=2, path=path, base=0.4)

        items = list(found.values())
        for it in items:
            it["score"] = round(it.pop("_base") * (1 + math.log(it["support"])) * it["conf"], 4)
        items.sort(key=lambda x: -x["score"])
        items = items[:limit]
        if items:
            prov = await self._q(
                """MATCH (f:Fact) WHERE f.id IN $ids
                   OPTIONAL MATCH (f)-[:EXTRACTED_FROM]->(e:Episode)
                   RETURN f.id, e.id, e.session, e.seq, e.agent, e.ts, e.redacted""",
                {"ids": [i["id"] for i in items]}, scope="read", checked=True)
            by = {i["id"]: i for i in items}
            for r in prov:
                if r[1] is not None:
                    by[r[0]]["provenance"].append(dict(episode=r[1], session=r[2], seq=r[3], agent=r[4], ts=r[5],
                                                       redacted=r[6]))
        return items

    @staticmethod
    def _fact_row(r, hop: int, path: str, base: float) -> dict:
        return dict(id=r[0], subject=r[1], predicate=r[2], object=r[3], support=r[4], conf=r[5], valid_from=r[6],
                    valid_to=r[7], current=r[8], hop=hop, path=path, provenance=[], _base=base)

    async def fact_history(self, subject: str, predicate: str) -> list[dict]:
        """Full bi-temporal chain for (subject, predicate): every value ever held, oldest first."""
        rows = await self._q(
            """MATCH (f:Fact {skey:$skey, pred:$pred})
               RETURN f.id, f.otext, f.valid_from, f.valid_to, f.cur, f.invalidated_by, f.support
               ORDER BY f.valid_from""", {"skey": norm(subject), "pred": norm(predicate)}, scope="read")
        return [dict(id=r[0], value=r[1], valid_from=r[2], valid_to=r[3], current=r[4], superseded_by=r[5],
                     support=r[6]) for r in rows]

    # ---------------------------------------------------------------- procedural
    async def add_skill(self, name: str, description: str, steps: list[str], tags: Iterable[str] = (),
                        sources: Iterable[str] = ()) -> dict:
        ts = now_ms()
        rows = await self._q(
            """
            MERGE (s:Skill {key:$key})
              ON CREATE SET s.id=$sid, s.name=$name, s.runs=0, s.wins=0, s.created_at=$ts, s.version=0
            SET s.description=$desc, s.steps=$steps, s.tags=$tags, s.updated_at=$ts, s.version=s.version+1
            RETURN s.id, s.version
            """,
            {"key": norm(name), "sid": new_id("skl"), "name": name.strip(), "ts": ts, "desc": description,
             "steps": json.dumps(steps), "tags": [norm(t) for t in tags]})
        src = list(sources)
        if src:
            await self._q("MATCH (s:Skill {key:$key}) UNWIND $src AS eid MATCH (e:Episode {id:eid}) "
                          "MERGE (s)-[:LEARNED_FROM]->(e)", {"key": norm(name), "src": src})
        return {"id": rows[0][0], "version": rows[0][1]}

    async def record_run(self, skill: str, success: bool, *, task_id: Optional[str] = None, notes: str = "",
                         agent: Optional[str] = None) -> dict:
        """Record one execution outcome; the skill's win/run counters (its ranking signal) move atomically."""
        rows = await self._q(
            """
            MATCH (s:Skill {key:$key})
            CREATE (r:Run {id:$rid, success:$ok, notes:$notes, ts:$ts, agent:$agent})-[:OF]->(s)
            SET s.runs = s.runs + 1, s.wins = s.wins + $inc, s.last_run = $ts
            WITH r, s
            OPTIONAL MATCH (t:Task {id:$tid})
            FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | CREATE (r)-[:FOR]->(t))
            RETURN r.id, s.runs, s.wins
            """,
            {"key": norm(skill), "rid": new_id("run"), "ok": success, "inc": 1 if success else 0, "notes": notes,
             "ts": now_ms(), "agent": agent or self.agent, "tid": task_id})
        if not rows:
            raise KeyError(f"unknown skill {skill!r}")
        return {"id": rows[0][0], "runs": rows[0][1], "wins": rows[0][2]}

    async def best_skills(self, tags: Iterable[str] = (), limit: int = 5) -> list[dict]:
        """Rank skills for a context by smoothed success rate (Laplace), then by experience."""
        tg = [norm(t) for t in tags]
        rows = await self._q(
            """
            MATCH (s:Skill) WHERE size($tags) = 0 OR any(t IN s.tags WHERE t IN $tags)
            RETURN s.id, s.name, s.description, s.steps, s.tags, s.runs, s.wins,
                   (toFloat(s.wins) + 1.0) / (toFloat(s.runs) + 2.0) AS score, s.version
            ORDER BY score DESC, s.runs DESC LIMIT $n
            """, {"tags": tg, "n": limit}, scope="read")
        return [dict(id=r[0], name=r[1], description=r[2], steps=json.loads(r[3]), tags=r[4], runs=r[5], wins=r[6],
                     score=round(r[7], 4), version=r[8]) for r in rows]

    async def skill_runs(self, skill: str, limit: int = 20) -> list[dict]:
        rows = await self._q(
            "MATCH (r:Run)-[:OF]->(:Skill {key:$key}) RETURN r.id, r.success, r.notes, r.agent, r.ts "
            "ORDER BY r.ts DESC LIMIT $n", {"key": norm(skill), "n": limit}, scope="read")
        return [dict(id=r[0], success=r[1], notes=r[2], agent=r[3], ts=r[4]) for r in rows]

    # ---------------------------------------------------------------- tasks & handoffs (compare-and-set)
    async def create_task(self, title: str, payload: Optional[dict] = None) -> str:
        tid = new_id("tsk")
        await self._q("CREATE (t:Task {id:$id, title:$title, payload:$payload, status:'open', version:0, "
                      "created_at:$ts, created_by:$agent})",
                      {"id": tid, "title": title, "payload": json.dumps(payload or {}), "ts": now_ms(),
                       "agent": self.agent})
        return tid

    async def claim_task(self, task_id: str, *, expected_version: Optional[int] = None) -> bool:
        """Atomic claim: succeeds for exactly one caller even if many race (guard is in the WHERE clause)."""
        rows = await self._q(
            """
            MATCH (t:Task {id:$tid}) WHERE t.status = 'open' AND ($v IS NULL OR t.version = $v)
            SET t.status='claimed', t.owner=$agent, t.version = t.version + 1
            WITH t
            MERGE (a:Agent {id:$agent})
            CREATE (t)-[:CLAIMED_BY {at:$ts}]->(a)
            RETURN t.version
            """, {"tid": task_id, "v": expected_version, "agent": self.agent, "ts": now_ms()})
        return bool(rows)

    async def handoff(self, task_id: str, to_agent: str, note: str = "", *, plan_id: Optional[str] = None,
                      expected_version: Optional[int] = None) -> bool:
        """Owner hands the task to another agent. Fails (False) if the caller is not the owner or state moved on."""
        rows = await self._q(
            """
            MATCH (t:Task {id:$tid})
            WHERE t.owner=$me AND t.status IN ['claimed','in_progress'] AND ($v IS NULL OR t.version=$v)
            SET t.status='handed_off', t.owner=$to, t.version = t.version + 1
            WITH t
            MERGE (b:Agent {id:$to})
            CREATE (t)-[:HANDED_OFF {from:$me, to:$to, at:$ts, note:$note, plan:$plan, n:t.version}]->(b)
            RETURN t.version
            """, {"tid": task_id, "me": self.agent, "to": to_agent, "note": note, "plan": plan_id,
                  "v": expected_version, "ts": now_ms()})
        return bool(rows)

    async def accept(self, task_id: str) -> bool:
        rows = await self._q("MATCH (t:Task {id:$tid}) WHERE t.status='handed_off' AND t.owner=$me "
                             "SET t.status='in_progress', t.version=t.version+1 RETURN t.version",
                             {"tid": task_id, "me": self.agent})
        return bool(rows)

    async def complete(self, task_id: str, result: str = "") -> bool:
        rows = await self._q("MATCH (t:Task {id:$tid}) WHERE t.owner=$me AND t.status IN ['claimed','in_progress'] "
                             "SET t.status='done', t.result=$res, t.done_at=$ts, t.version=t.version+1 "
                             "RETURN t.version", {"tid": task_id, "me": self.agent, "res": result, "ts": now_ms()})
        return bool(rows)

    async def get_task(self, task_id: str) -> Optional[dict]:
        rows = await self._q("MATCH (t:Task {id:$tid}) RETURN t", {"tid": task_id}, scope="read")
        if not rows:
            return None
        p = _props(rows[0][0])
        p["payload"] = json.loads(p.get("payload") or "{}")
        return p

    async def open_tasks(self, limit: int = 50) -> list[dict]:
        rows = await self._q("MATCH (t:Task {status:'open'}) RETURN t.id, t.title, t.version "
                             "ORDER BY t.created_at LIMIT $n", {"n": limit}, scope="read")
        return [dict(id=r[0], title=r[1], version=r[2]) for r in rows]

    # ---------------------------------------------------------------- plans & lineage
    async def create_plan(self, task_id: str, steps: list[str], derived_from: Iterable[str] = (),
                          revises: Optional[str] = None) -> str:
        """A plan remembers exactly which facts it was derived from, so staleness is a graph traversal."""
        pid = new_id("pln")
        rows = await self._q(
            """
            MATCH (t:Task {id:$tid})
            CREATE (p:Plan {id:$pid, steps:$steps, created_at:$ts, agent:$agent})-[:FOR]->(t)
            RETURN p.id
            """, {"tid": task_id, "pid": pid, "steps": json.dumps(steps), "ts": now_ms(), "agent": self.agent})
        if not rows:
            raise KeyError(f"unknown task {task_id!r}")
        facts = list(derived_from)
        if facts:
            await self._q("MATCH (p:Plan {id:$pid}) UNWIND $facts AS fid MATCH (f:Fact {id:fid}) "
                          "CREATE (p)-[:DERIVED_FROM {at:$ts}]->(f)", {"pid": pid, "facts": facts, "ts": now_ms()})
        if revises:
            await self._q("MATCH (n:Plan {id:$new}), (o:Plan {id:$old}) CREATE (n)-[:REVISES]->(o)",
                          {"new": pid, "old": revises})
        return pid

    async def check_plan(self, plan_id: str) -> dict:
        """Is any input of this plan outdated? Walks DERIVED_FROM then SUPERSEDES* to the current value."""
        rows = await self._q(
            """
            MATCH (p:Plan {id:$pid})-[:DERIVED_FROM]->(f:Fact)
            OPTIONAL MATCH (f)<-[:SUPERSEDES*1..10]-(n:Fact {cur:true})
            RETURN f.id, f.cur, f.sname, f.pred, f.otext, f.forgotten, n.id, n.otext
            """, {"pid": plan_id}, scope="read")
        changes, seen = [], set()
        for r in rows:
            if r[1] or r[0] in seen:
                continue
            seen.add(r[0])
            succ = [dict(id=x[6], value=x[7]) for x in rows if x[0] == r[0] and x[6]]
            changes.append(dict(fact=r[0], subject=r[2], predicate=r[3], was=r[4],
                                status="retracted" if r[5] else "superseded", now=succ))
        up = await self._q(
            """
            MATCH (p:Plan {id:$pid})-[:DERIVED_FROM]->(f:Fact {cur:true})-[:INFERRED_FROM*1..8]->(u:Fact)
            WHERE u.cur = false
            OPTIONAL MATCH (u)<-[:SUPERSEDES*1..10]-(n:Fact {cur:true})
            RETURN f.id, f.sname, f.pred, f.otext, u.id, u.otext, coalesce(u.forgotten, false), n.id, n.otext
            """, {"pid": plan_id}, scope="read", checked=True)
        for r in up:
            if r[0] in seen:
                continue
            seen.add(r[0])
            now = [dict(id=x[7], value=x[8]) for x in up if x[0] == r[0] and x[7]]
            changes.append(dict(fact=r[0], subject=r[1], predicate=r[2], was=r[3],
                                status="upstream_retracted" if r[6] else "upstream_superseded",
                                upstream=dict(fact=r[4], was=r[5]), now=now))
        inputs = {r[0] for r in rows} | {r[0] for r in up}
        return {"plan": plan_id, "inputs": len(inputs), "stale": bool(changes), "changes": changes}

    async def rebase_plan(self, plan_id: str, steps: Optional[list[str]] = None) -> dict:
        """Create a revised plan re-derived from the current versions of every input. Returns the diff."""
        chk = await self.check_plan(plan_id)
        rows = await self._q("MATCH (p:Plan {id:$pid})-[:FOR]->(t:Task) RETURN t.id, p.steps",
                             {"pid": plan_id}, scope="read")
        if not rows:
            raise KeyError(plan_id)
        task_id, old_steps = rows[0]
        keep = await self._q("MATCH (p:Plan {id:$pid})-[:DERIVED_FROM]->(f:Fact {cur:true}) RETURN f.id",
                             {"pid": plan_id}, scope="read")
        outdated = {c["fact"] for c in chk["changes"] if c["status"].startswith("upstream")}  # must be re-inferred
        facts = [r[0] for r in keep if r[0] not in outdated] + [s["id"] for c in chk["changes"] for s in c["now"]]
        new_id_ = await self.create_plan(task_id, steps or json.loads(old_steps), facts, revises=plan_id)
        return {"plan": new_id_, "revises": plan_id, "changes": chk["changes"]}

    async def resume(self, task_id: str) -> dict:
        """Everything a receiving agent needs: task, handoff chain, latest plan + staleness, plan inputs."""
        task = await self.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        chain = await self._q("MATCH (:Task {id:$tid})-[h:HANDED_OFF]->() RETURN h.from, h.to, h.at, h.note, h.plan "
                              "ORDER BY h.at", {"tid": task_id}, scope="read")
        plan = await self._q("MATCH (p:Plan)-[:FOR]->(:Task {id:$tid}) WHERE NOT ()-[:REVISES]->(p) "
                             "RETURN p.id, p.steps, p.agent, p.created_at ORDER BY p.created_at DESC LIMIT 1",
                             {"tid": task_id}, scope="read")
        out = {"task": task, "handoffs": [dict(frm=c[0], to=c[1], at=c[2], note=c[3], plan=c[4]) for c in chain],
               "plan": None}
        if plan:
            inputs = await self._q("MATCH (:Plan {id:$pid})-[:DERIVED_FROM]->(f:Fact) "
                                   "RETURN f.id, f.sname, f.pred, f.otext, f.cur", {"pid": plan[0][0]}, scope="read")
            out["plan"] = dict(id=plan[0][0], steps=json.loads(plan[0][1]), agent=plan[0][2],
                               inputs=[dict(id=i[0], fact=f"{i[1]} {i[2]} {i[3]}", current=i[4]) for i in inputs],
                               check=await self.check_plan(plan[0][0]))
        return out

    # ---------------------------------------------------------------- decision traces
    async def record_decision(self, summary: str, used: Iterable[str], answer: str = "") -> str:
        did = new_id("dec")
        await self._q("CREATE (d:Decision {id:$id, summary:$s, answer:$a, agent:$agent, ts:$ts})",
                      {"id": did, "s": summary, "a": answer, "agent": self.agent, "ts": now_ms()})
        by_label: dict[str, list[str]] = {}
        for u in used:
            label = PREFIX_LABEL.get(u.split("_", 1)[0])
            if label:
                by_label.setdefault(label, []).append(u)
        for label, ids in by_label.items():
            await self._q(f"MATCH (d:Decision {{id:$did}}) UNWIND $ids AS i MATCH (x:{label} {{id:i}}) "
                          "CREATE (d)-[:USED]->(x)", {"did": did, "ids": ids})
        return did

    async def explain(self, decision_id: str) -> dict:
        """Why did the agent decide this? Everything it used, with the episodes those facts came from."""
        d = await self._q("MATCH (d:Decision {id:$id}) RETURN d", {"id": decision_id}, scope="read")
        if not d:
            raise KeyError(decision_id)
        rows = await self._q(
            """MATCH (:Decision {id:$id})-[:USED]->(x)
               OPTIONAL MATCH (x)-[:EXTRACTED_FROM|LEARNED_FROM]->(e:Episode)
               RETURN x, labels(x)[0], collect(e.id)""", {"id": decision_id}, scope="read")
        used = []
        for x, label, eps in rows:
            p = _props(x)
            used.append(dict(type=label, id=p.get("id"), summary=self._summ(label, p), current=p.get("cur"),
                             source_episodes=eps))
        return {"decision": _props(d[0][0]), "used": used}

    @staticmethod
    def _summ(label: str, p: dict) -> str:
        if label == "Fact":
            return f"{p.get('sname')} {p.get('pred')} {p.get('otext')}"
        if label == "Episode":
            return (p.get("content") or "[redacted]")[:120]
        return p.get("name") or p.get("title") or p.get("summary") or p.get("id", "")

    # ---------------------------------------------------------------- forgetting
    async def forget_fact(self, fact_id: str, reason: str, *, redact_sources: bool = False) -> dict:
        """Retract a fact: close it, blank its content, drop its links, leave a tombstone with the reason.
        Plans derived from it will report it as 'retracted'. Optionally redact the source episodes' text."""
        rows = await self._q(
            """
            MATCH (f:Fact {id:$fid})
            OPTIONAL MATCH (f)-[:SUBJECT|OBJECT]->(en:Entity)
            WITH f, collect(DISTINCT en.key) AS keys
            SET f.cur=false, f.valid_to=coalesce(f.valid_to,$ts), f.forgotten=true, f.otext='[forgotten]',
                f.sname='[forgotten]', f.skey='', f.okey=''
            CREATE (:Tombstone {id:$tid, reason:$reason, at:$ts, by:$agent})-[:TOMBSTONES]->(f)
            RETURN keys
            """, {"fid": fact_id, "ts": now_ms(), "tid": new_id("tomb"), "reason": reason, "agent": self.agent})
        if not rows:
            raise KeyError(fact_id)
        keys = rows[0][0]
        redacted = 0
        if redact_sources:
            r = await self._q("MATCH (:Fact {id:$fid})-[:EXTRACTED_FROM]->(e:Episode) "
                              "SET e.content=null, e.redacted=true RETURN count(e)", {"fid": fact_id})
            redacted = r[0][0]
        await self._q("MATCH (:Fact {id:$fid})-[r:SUBJECT|OBJECT|EXTRACTED_FROM]->() DELETE r", {"fid": fact_id})
        await self._q("MATCH (en:Entity) WHERE en.key IN $keys AND NOT (en)<-[:SUBJECT|OBJECT]-(:Fact) DELETE en",
                      {"keys": keys})
        return {"fact": fact_id, "redacted_episodes": redacted}

    # ---------------------------------------------------------------- inspection
    async def graph_view(self, limit: int = 300) -> dict:
        """Snapshot of the tenant graph for visualization: newest nodes first, with the edges among them."""
        limit = max(1, min(int(limit), 1000))
        rows = await self._q("MATCH (n) RETURN id(n), labels(n)[0], n ORDER BY coalesce(n.ts, n.recorded_at, "
                             "n.created_at, n.started_at, n.at, 0) DESC LIMIT $n", {"n": limit}, scope="read")
        nodes, ids = [], []
        for nid, label, n in rows:
            p = _props(n)
            cap = self._summ(label, p) if label not in ("Session", "Entity", "Tombstone") else                 (p.get("name") or p.get("id") or p.get("reason") or "")
            nodes.append(dict(id=nid, label=label, caption=str(cap)[:80], uid=p.get("id"),
                              current=p.get("cur"), forgotten=bool(p.get("forgotten"))))
            ids.append(nid)
        edges = []
        if ids:
            er = await self._q("MATCH (a)-[r]->(b) WHERE id(a) IN $ids AND id(b) IN $ids "
                               "RETURN id(a), id(b), type(r)", {"ids": ids}, scope="read", checked=True)
            edges = [dict(src=r[0], dst=r[1], type=r[2]) for r in er]
        return {"nodes": nodes, "edges": edges}

    # ---------------------------------------------------------------- stats
    async def stats(self) -> dict:
        rows = await self._q("MATCH (n) RETURN labels(n)[0], count(n)", scope="read")
        return {r[0]: r[1] for r in rows}
