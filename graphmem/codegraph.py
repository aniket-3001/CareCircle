"""Code-structure graph and graph-algorithm tools, mixed into TenantMemory.

Model (in the tenant's own graph, next to its memory):
  (Code {id, kind, name, path})-[:DEPENDS_ON {cap}]->(Code)       file imports file ("cap" = number of import statements)
  (Code file)-[:DEFINES]->(Code func)                             (Code func)-[:CALLS]->(Code func)
  (Person)-[:AUTHORED]->(Commit {sha, ts, msg})-[:TOUCHED]->(Code file)

Every tool is read-only and returns the Cypher it ran, so a caller can show or re-run it. Algorithms are FalkorDB's
built-in `algo.*` procedures (BFS, pageRank, betweenness, WCC, labelPropagation, maxFlow, SPpaths).
"""
from __future__ import annotations

from typing import Iterable, Optional

ALGO_LIMIT = 200_000     # refuse algorithm runs on absurdly large graphs rather than stall the database


class CodeGraphMixin:
    # ---------------------------------------------------------------- loading
    async def code_load(self, files: list[dict], deps: list[list] = (), defs: list[list] = (), calls: list[list] = (),
                        commits: list[dict] = ()) -> dict:
        """Bulk-load a code graph (idempotent: MERGE on indexed ids).
        files: [{id, name, path, kind}], deps/calls: [[from_id, to_id, cap]], defs: [[file_id, func_id]],
        commits: [{sha, ts, msg, author, files: [file_id, ...]}]."""
        await self._guard_write()
        for i in range(0, len(files), 500):
            await self._q("UNWIND $rows AS r MERGE (c:Code {id:r.id}) SET c.name=r.name, c.path=r.path, c.kind=r.kind",
                          {"rows": files[i:i + 500]}, checked=True)
        for typ, rows in (("DEPENDS_ON", deps), ("CALLS", calls)):
            for i in range(0, len(rows), 500):
                chunk = [{"a": r[0], "b": r[1], "cap": float(r[2]) if len(r) > 2 else 1.0} for r in rows[i:i + 500]]
                await self._q(f"UNWIND $rows AS r MATCH (a:Code {{id:r.a}}) MATCH (b:Code {{id:r.b}}) "
                              f"MERGE (a)-[e:{typ}]->(b) SET e.cap=r.cap", {"rows": chunk}, checked=True)
        for i in range(0, len(defs), 500):
            await self._q("UNWIND $rows AS r MATCH (a:Code {id:r[0]}) MATCH (b:Code {id:r[1]}) MERGE (a)-[:DEFINES]->(b)",
                          {"rows": [list(x) for x in defs[i:i + 500]]}, checked=True)
        for i in range(0, len(commits), 100):
            chunk = commits[i:i + 100]
            await self._q(
                "UNWIND $rows AS r MERGE (m:Commit {sha:r.sha}) SET m.ts=r.ts, m.msg=r.msg "
                "MERGE (p:Person {id:r.author}) MERGE (p)-[:AUTHORED]->(m)",
                {"rows": [{k: c[k] for k in ("sha", "ts", "msg", "author")} for c in chunk]}, checked=True)
            pairs = [{"sha": c["sha"], "f": f} for c in chunk for f in c.get("files", [])]
            for j in range(0, len(pairs), 1000):
                await self._q("UNWIND $rows AS r MATCH (m:Commit {sha:r.sha}) MATCH (f:Code {id:r.f}) MERGE (m)-[:TOUCHED]->(f)",
                              {"rows": pairs[j:j + 1000]}, checked=True)
        return await self._stats(checked=True)

    async def _guard_write(self) -> None:
        if self._guard:
            await self._guard("write")

    async def code_stats(self) -> dict:
        return await self._stats()

    async def _stats(self, checked: bool = False) -> dict:
        r = await self._q("MATCH (c:Code) WITH count(c) AS nodes OPTIONAL MATCH (:Code)-[d:DEPENDS_ON]->(:Code) "
                          "WITH nodes, count(d) AS deps OPTIONAL MATCH (m:Commit) RETURN nodes, deps, count(m)", scope="read", checked=checked)
        return dict(code_nodes=r[0][0], depends_on_edges=r[0][1], commits=r[0][2])

    async def _run(self, cypher: str, params: dict, shape) -> dict:
        rows = await self._q(cypher, params, scope="read", checked=True)
        return {"cypher": " ".join(cypher.split()), "params": params, "rows": shape(rows)}

    async def _ensure_code(self, *ids: str) -> None:
        for i in ids:
            r = await self._q("MATCH (c:Code {id:$i}) RETURN count(c)", {"i": i}, scope="read", checked=True)
            if not r[0][0]:
                raise KeyError(f"no code node {i!r}")

    async def _read(self) -> None:
        if self._guard:
            await self._guard("read")

    # ---------------------------------------------------------------- tools
    async def blast_radius(self, path: str, depth: int = 3, limit: int = 100) -> dict:
        """What breaks if this file changes: files that (transitively, up to depth) depend on it, nearest first."""
        await self._read()
        depth = max(1, min(int(depth), 8))
        await self._ensure_code(path)
        return await self._run(
            f"MATCH p=(x:Code)-[:DEPENDS_ON*1..{depth}]->(:Code {{id:$p}}) "
            "WITH x, min(length(p)) AS hops RETURN x.id, hops ORDER BY hops, x.id LIMIT $n",
            {"p": path, "n": limit}, lambda rs: [dict(file=r[0], hops=r[1]) for r in rs])

    async def dependencies_of(self, path: str, depth: int = 3, limit: int = 100) -> dict:
        """Transitive dependencies of a file via FalkorDB's algo.BFS."""
        await self._read()
        depth = max(1, min(int(depth), 8))
        await self._ensure_code(path)
        return await self._run(
            "MATCH (s:Code {id:$p}) CALL algo.BFS(s, $d, 'DEPENDS_ON') YIELD nodes "
            "UNWIND nodes AS n RETURN n.id LIMIT $n", {"p": path, "d": depth, "n": limit},
            lambda rs: [r[0] for r in rs])

    async def criticality(self, limit: int = 10) -> dict:
        """Which files matter most: PageRank over DEPENDS_ON (a file is important if important files depend on it)."""
        await self._read()
        return await self._run(
            "CALL algo.pageRank('Code','DEPENDS_ON') YIELD node, score RETURN node.id, score ORDER BY score DESC LIMIT $n",
            {"n": limit}, lambda rs: [dict(file=r[0], score=round(r[1], 5)) for r in rs])

    async def single_points_of_failure(self, limit: int = 10) -> dict:
        """Files that sit on the most shortest dependency paths (betweenness centrality): changing them ripples widest."""
        await self._read()
        return await self._run(
            "CALL algo.betweenness({nodeLabels:['Code'], relationshipTypes:['DEPENDS_ON']}) YIELD node, score "
            "RETURN node.id, score ORDER BY score DESC LIMIT $n", {"n": limit},
            lambda rs: [dict(file=r[0], score=round(r[1], 3)) for r in rs])

    async def failure_domains(self) -> dict:
        """Weakly connected components of the dependency graph (independent failure domains) with sizes."""
        await self._read()
        return await self._run(
            "CALL algo.WCC({nodeLabels:['Code'], relationshipTypes:['DEPENDS_ON']}) YIELD node, componentId "
            "RETURN componentId, count(node) AS size, collect(node.id)[0..5] AS sample ORDER BY size DESC",
            {}, lambda rs: [dict(component=r[0], size=r[1], sample=r[2]) for r in rs])

    async def communities(self, limit: int = 20) -> dict:
        """Label-propagation communities: groups of files that reference each other more than the rest."""
        await self._read()
        return await self._run(
            "CALL algo.labelPropagation({nodeLabels:['Code'], relationshipTypes:['DEPENDS_ON']}) YIELD node, communityId "
            "RETURN communityId, count(node) AS size, collect(node.id)[0..5] AS sample ORDER BY size DESC LIMIT $n",
            {"n": limit}, lambda rs: [dict(community=r[0], size=r[1], sample=r[2]) for r in rs])

    async def failover_capacity(self, source: str, sink: str) -> dict:
        """Max flow from source to sink over DEPENDS_ON (capacity = import count): how many independent routes link them."""
        await self._read()
        await self._ensure_code(source, sink)
        return await self._run(
            "MATCH (s:Code {id:$s}),(t:Code {id:$t}) CALL algo.maxFlow({sourceNodes:[s], targetNodes:[t], "
            "relationshipTypes:['DEPENDS_ON'], capacityProperty:'cap'}) YIELD maxFlow RETURN maxFlow",
            {"s": source, "t": sink}, lambda rs: rs[0][0] if rs else 0)

    async def cheapest_route(self, source: str, target: str, max_paths: int = 3) -> dict:
        """Cheapest dependency routes source -> target (hop-count weighted) via algo.SPpaths."""
        await self._read()
        await self._ensure_code(source, target)
        return await self._run(
            "MATCH (s:Code {id:$s}),(t:Code {id:$t}) CALL algo.SPpaths({sourceNode:s, targetNode:t, "
            "relTypes:['DEPENDS_ON'], weightProp:'cap', pathCount:$k}) YIELD path, pathWeight "
            "RETURN pathWeight, [n IN nodes(path) | n.id]", {"s": source, "t": target, "k": max(1, min(max_paths, 10))},
            lambda rs: [dict(weight=r[0], route=r[1]) for r in rs])

    async def co_changed(self, path: str, limit: int = 10) -> dict:
        """Files most often committed together with this one."""
        await self._read()
        await self._ensure_code(path)
        return await self._run(
            "MATCH (:Code {id:$p})<-[:TOUCHED]-(m:Commit)-[:TOUCHED]->(o:Code) WHERE o.id <> $p "
            "RETURN o.id, count(m) AS n ORDER BY n DESC, o.id LIMIT $k", {"p": path, "k": limit},
            lambda rs: [dict(file=r[0], commits=r[1]) for r in rs])

    async def who_to_ask(self, path: str, limit: int = 5) -> dict:
        """People who know this file: weighted by commits touching it (x3) and files it depends on or that depend on it."""
        await self._read()
        await self._ensure_code(path)
        return await self._run(
            """MATCH (c:Code {id:$p})
               OPTIONAL MATCH (c)-[:DEPENDS_ON]-(nb:Code)
               WITH c, collect(DISTINCT nb) AS nbs
               UNWIND ([c] + nbs) AS f
               MATCH (a:Person)-[:AUTHORED]->(m:Commit)-[:TOUCHED]->(f)
               WITH a, sum(CASE WHEN f = c THEN 3 ELSE 1 END) AS score, count(DISTINCT m) AS commits
               RETURN a.id, score, commits ORDER BY score DESC, a.id LIMIT $k""", {"p": path, "k": limit},
            lambda rs: [dict(person=r[0], score=r[1], commits=r[2]) for r in rs])

    async def change_impact(self, paths: list[str], depth: int = 3, limit: int = 30) -> dict:
        """Dry-run for a planned edit: union of blast radius and historical co-change for the files you intend to touch."""
        await self._read()
        paths = [p for p in paths][:20]
        for p in paths:
            await self._ensure_code(p)
        dependants = await self._run(
            f"MATCH p=(x:Code)-[:DEPENDS_ON*1..{max(1, min(int(depth), 8))}]->(c:Code) WHERE c.id IN $ps AND NOT x.id IN $ps "
            "WITH x, min(length(p)) AS hops RETURN x.id, hops ORDER BY hops, x.id LIMIT $n", {"ps": paths, "n": limit},
            lambda rs: [dict(file=r[0], hops=r[1]) for r in rs])
        cochange = await self._run(
            "MATCH (c:Code)<-[:TOUCHED]-(m:Commit)-[:TOUCHED]->(o:Code) WHERE c.id IN $ps AND NOT o.id IN $ps "
            "RETURN o.id, count(m) AS n ORDER BY n DESC, o.id LIMIT $n", {"ps": paths, "n": limit},
            lambda rs: [dict(file=r[0], commits=r[1]) for r in rs])
        return dict(files=paths, dependants=dependants, co_changed=cochange)
