"""FalkorDB's graph algorithms as read-only operations on a tenant's own memory graph, so an agent can ask the graph instead of writing traversals.

  graph_schema         what is in the graph: labels and relationship types with counts
  graph_path           shortest path between two nodes (breadth-first, any direction) (the "how is A connected to B" question)
  graph_influence      PageRank or betweenness: which nodes everything else hangs on
  graph_communities    weakly connected components or label propagation: which nodes belong together
  graph_neighbourhood  everything within a few hops of one node

Every operation runs on the read path (GRAPH.RO_QUERY), so it needs only read scope and cannot change anything. Nothing the caller sends is put into
the query text: labels are passed as parameters (and checked against the labels that exist), node references are parameters, hop counts and sizes
are clamped integers. Each result carries the Cypher that ran. A node is named by `ref` (its id, key or name) together with its label."""
from __future__ import annotations

import re
from typing import Optional

REF_MAX = 200
MAX_TOP = 50
MAX_HOPS = 10
MAX_NEIGHBOURS = 100
MAX_VISIT = 20000
EXPAND = "MATCH (a)-[r]-(b) WHERE id(a) IN $f AND NOT b:Schema RETURN id(a), type(r), id(b) ORDER BY id(a), id(b), type(r)"

# how a node is shown: its label, the value it is referred to by, and a short human title
SHOW = ("labels({n})[0] AS label, coalesce({n}.id, {n}.key, {n}.name) AS ref, "
        "coalesce({n}.summary, {n}.title, {n}.name, {n}.drug, left(toString({n}.content), 80), {n}.id) AS title")
SHOW_MAP = ("{{label: labels({n})[0], ref: coalesce({n}.id, {n}.key, {n}.name), "
            "title: coalesce({n}.summary, {n}.title, {n}.name, {n}.drug, left(toString({n}.content), 80), {n}.id)}}")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _clamp(v, lo: int, hi: int, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{what} must be a whole number")
    return max(lo, min(v, hi))


def _ref(v, what: str = "a node reference") -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > REF_MAX:
        raise ValueError(f"{what} is the node's id, key or name (1 to {REF_MAX} characters)")
    return v


def _cfg(label: Optional[str]) -> str:
    """Algorithm configuration: every label, or one (the label travels as the parameter $label; older servers reject a null list, so the map differs)."""
    return "{}" if label is None else "{nodeLabels: [$label]}"


def _node(row) -> dict:
    return {"label": row[0], "ref": row[1], "title": row[2]}


class GraphAlgoMixin:
    async def _labels(self) -> list[str]:
        return sorted(r[0] for r in await self._q("CALL db.labels() YIELD label RETURN label", scope="read"))

    async def _label_arg(self, label: Optional[str]) -> Optional[str]:
        """None for "all", else a label that exists in this graph (anything else is an error naming the labels there are)."""
        if label in (None, ""):
            return None
        if not isinstance(label, str) or not NAME.match(label):
            raise ValueError("label is the name of a node label")
        have = await self._labels()
        if label not in have:
            raise ValueError(f"no node label {label!r} in this graph; there are: {', '.join(have) or 'none'}")
        return label

    async def _find(self, ref: str, label: Optional[str]):
        """The internal id of the node a reference names (first match when several share a name), or None."""
        pat = f"(n:`{label}`)" if label else "(n)"            # label was checked against db.labels() and NAME
        rows = await self._q(f"MATCH {pat} WHERE n.id = $r OR n.key = $r OR n.name = $r RETURN id(n) LIMIT 1", {"r": ref}, scope="read")
        return rows[0][0] if rows else None

    async def graph_schema(self) -> dict:
        """What this graph holds: node labels and relationship types, each with a count."""
        nodes = await self._q("MATCH (n) WHERE NOT n:Schema RETURN labels(n)[0] AS l, count(n) AS c ORDER BY c DESC, l", scope="read")
        rels = await self._q("MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS c ORDER BY c DESC, t", scope="read")
        return {"nodes": [{"label": r[0], "count": r[1]} for r in nodes], "relationships": [{"type": r[0], "count": r[1]} for r in rels],
                "cypher": "MATCH (n) WHERE NOT n:Schema RETURN labels(n)[0], count(n)  |  MATCH ()-[r]->() RETURN type(r), count(r)"}

    async def graph_path(self, source: str, target: str, max_hops: int = 8, source_label: Optional[str] = None,
                         target_label: Optional[str] = None) -> dict:
        """Shortest path between two nodes, ignoring edge direction: the nodes on it and the relationship between each pair."""
        source, target = _ref(source, "source"), _ref(target, "target")
        hops = _clamp(max_hops, 1, MAX_HOPS, "max_hops")
        sl, tl = await self._label_arg(source_label), await self._label_arg(target_label)
        a, b = await self._find(source, sl), await self._find(target, tl)
        if a is None or b is None:
            return {"found": False, "reason": "unknown node: " + ("source" if a is None else "target"), "path": []}
        if a == b:
            n = (await self._q(f"MATCH (x) WHERE id(x) = $a RETURN {SHOW.format(n='x')}", {"a": a}, scope="read"))[0]
            return {"found": True, "length": 0, "path": [_node(n)], "relationships": [], "cypher": EXPAND}
        # Breadth-first, one query per hop, ignoring direction. FalkorDB's own undirected shortestPath exists only in newer versions (4.22 lacks it), and this
        # gives the same answer on every version. Ties are broken by internal id, so the same question always gets the same path.
        parent: dict[int, Optional[tuple[int, str]]] = {a: None}
        frontier = [a]
        for _ in range(hops):
            if b in parent or not frontier:
                break
            nxt = []
            for x, rel, y in await self._q(EXPAND, {"f": frontier}, scope="read"):
                if y not in parent:
                    parent[y] = (x, rel)
                    nxt.append(y)
            if len(parent) > MAX_VISIT:
                return {"found": False, "reason": f"stopped after {len(parent)} records; ask for fewer hops or name a label", "path": [], "cypher": EXPAND}
            frontier = nxt
        if b not in parent:
            return {"found": False, "reason": f"no connection within {hops} hops", "path": [], "cypher": EXPAND}
        ids, types, at = [b], [], b
        while parent[at] is not None:
            at, rel = parent[at]
            ids.append(at)
            types.append(rel)
        ids.reverse()
        types.reverse()
        shown = {r[0]: _node(r[1:]) for r in await self._q(f"MATCH (x) WHERE id(x) IN $ids RETURN id(x), {SHOW.format(n='x')}", {"ids": ids}, scope="read")}
        return {"found": True, "length": len(types), "path": [shown[i] for i in ids], "relationships": types, "cypher": EXPAND}

    async def graph_influence(self, metric: str = "pagerank", label: Optional[str] = None, top: int = 10) -> dict:
        """The most influential nodes: metric 'pagerank' (many well-connected nodes point here) or 'betweenness' (many shortest paths go through here)."""
        top = _clamp(top, 1, MAX_TOP, "top")
        lab = await self._label_arg(label)
        if metric == "pagerank":
            call = "CALL algo.pageRank($label, null) YIELD node, score"
        elif metric == "betweenness":
            call = f"CALL algo.betweenness({_cfg(lab)}) YIELD node, score"
        else:
            raise ValueError("metric is 'pagerank' or 'betweenness'")
        cypher = f"{call} WITH node, score WHERE NOT node:Schema WITH node, score ORDER BY score DESC LIMIT $top RETURN {SHOW.format(n='node')}, score"
        rows = await self._q(cypher, {"label": lab, "top": top}, scope="read")
        return {"metric": metric, "label": lab, "rows": [{**_node(r), "score": round(r[3], 5)} for r in rows], "cypher": cypher}

    async def graph_communities(self, method: str = "wcc", label: Optional[str] = None, top: int = 10) -> dict:
        """Groups of nodes that belong together: method 'wcc' (connected components) or 'labelpropagation' (communities inside a connected graph)."""
        top = _clamp(top, 1, MAX_TOP, "top")
        lab = await self._label_arg(label)
        cfg = _cfg(lab)
        if method == "wcc":
            call = f"CALL algo.WCC({cfg}) YIELD node, componentId AS cid"
        elif method == "labelpropagation":
            call = f"CALL algo.labelPropagation({cfg}) YIELD node, communityId AS cid"
        else:
            raise ValueError("method is 'wcc' or 'labelpropagation'")
        cypher = (f"{call} WITH cid, node WHERE NOT node:Schema WITH cid, collect(node) AS ns ORDER BY size(ns) DESC LIMIT $top "
                  f"RETURN cid, size(ns), [x IN ns | labels(x)[0]], [x IN ns[0..5] | {SHOW_MAP.format(n='x')}]")
        rows = await self._q(cypher, {"label": lab, "top": top}, scope="read")
        total = (await self._q("MATCH (n) WHERE NOT n:Schema RETURN count(n)", scope="read"))[0][0]
        out = []
        for cid, size, labels, sample in rows:
            kinds: dict[str, int] = {}
            for k in labels:
                kinds[k] = kinds.get(k, 0) + 1
            out.append({"group": cid, "size": size, "kinds": kinds, "sample": [dict(x) for x in sample]})
        return {"method": method, "label": lab, "groups": out, "nodes_in_graph": total, "cypher": cypher}

    async def graph_neighbourhood(self, ref: str, depth: int = 2, label: Optional[str] = None, limit: int = 50) -> dict:
        """Everything within `depth` hops of one node, ignoring direction, nearest first (at most `limit` nodes)."""
        ref = _ref(ref, "ref")
        depth = _clamp(depth, 1, 3, "depth")
        limit = _clamp(limit, 1, MAX_NEIGHBOURS, "limit")
        start = await self._find(ref, await self._label_arg(label))
        if start is None:
            return {"found": False, "nodes": []}
        seen, frontier, out = {start}, [start], []
        cypher = ("MATCH (a)-[r]-(b) WHERE id(a) IN $f AND NOT b:Schema RETURN id(b), type(r), id(a), " + SHOW.format(n="b") + " ORDER BY id(b), type(r) LIMIT 2000")
        for hop in range(1, depth + 1):
            if not frontier or len(out) >= limit:
                break
            nxt = []
            for bid, rel, via, *shown in await self._q(cypher, {"f": frontier}, scope="read"):
                if bid in seen or len(out) >= limit:
                    continue
                seen.add(bid)
                nxt.append(bid)
                out.append({"hop": hop, **_node(shown), "via": rel})
            frontier = nxt
        return {"found": True, "depth": depth, "nodes": out, "truncated": len(out) >= limit, "cypher": cypher}
