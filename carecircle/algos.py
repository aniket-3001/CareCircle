"""FalkorDB graph algorithms over the shared reference graph (read-only). Each returns rows plus the exact Cypher that ran.

 hub_drugs     PageRank over HAZARD (symmetric moderate/major interaction graph): drugs that sit at the centre of many hazards
 clusters      WCC over HAZARD: groups of drugs connected by hazards
 regimen_hubs  which drugs in THIS regimen take part in most hazards within it (degree inside the induced subgraph)
"""
from __future__ import annotations

import os

from falkordb import FalkorDB

from .reference import REF_GRAPH, norm

Q_PR = "CALL algo.pageRank('Drug','HAZARD') YIELD node, score RETURN node.name, score ORDER BY score DESC LIMIT $n"
Q_WCC = ("CALL algo.WCC({nodeLabels:['Drug'], relationshipTypes:['HAZARD']}) YIELD node, componentId "
         "RETURN componentId, count(node) AS size, collect(node.name)[0..5] AS sample ORDER BY size DESC LIMIT $n")
Q_REG = ("MATCH (a:Drug)-[h:HAZARD]->(b:Drug) WHERE a.name IN $d AND b.name IN $d "
         "RETURN a.name, count(b) AS hazards, sum(h.w) AS weight ORDER BY weight DESC")
Q_PATHWAYS = ("MATCH (d:Drug)-[r:INHIBITS|INDUCES|SUBSTRATE_OF]->(e:Enzyme) WHERE d.name IN $d "
              "RETURN e.name, e.kind, d.name, type(r), r.strength, r.source ORDER BY e.name, d.name")

SEVERITY_RANK = {"major": 0, "moderate": 1, "minor": 2}


def order_flags(res: dict, hubs: dict) -> None:
    """Put each list of flags in the order that is most useful to read, WITHOUT adding or removing any: severity first (as listed by the source), then how connected
    the two medicines are inside THIS person's regimen (the summed weight of the moderate and major interaction lines each takes part in, from the regimen's own induced
    subgraph), then names. A medicine that interacts with several others on her list therefore comes first among flags of the same severity. Every flag also gets
    `centrality` (that figure) so the order can be seen and checked. The severity data alone decides what is flagged; this only decides what is read first."""
    w = {r["drug"]: float(r["weight"]) for r in hubs.get("rows", [])}
    for f in res.get("direct", []) + res.get("unrated", []):
        f["centrality"] = round(sum(w.get(d, 0.0) for d in f["drugs"]), 2)
    for f in res.get("enzyme_paths", []):
        f["centrality"] = round(w.get(f["x"], 0.0) + w.get(f["y"], 0.0), 2)
    res["direct"].sort(key=lambda f: (SEVERITY_RANK.get(str(f["level"]).lower(), 3), -f["centrality"], sorted(f["drugs"])))
    res["unrated"].sort(key=lambda f: (-f["centrality"], sorted(f["drugs"])))
    strength = {"strong": 0, "moderate": 1, "in vitro": 2}                     # clinical evidence first: a laboratory finding never outranks it
    res["enzyme_paths"].sort(key=lambda f: (strength.get(f["strength"], 3), -f["centrality"], f["x"], f["y"], f["enzyme"]))


def group_pathways(rows: list, drugs: list[str]) -> dict:
    """Group the medicines on record by the enzyme or transporter they share. `rows` are (enzyme, kind, drug, relation, strength, source). A pathway with two or more
    of her medicines is a shared route: they are processed by, or act on, the same thing. Only medicines the FDA tables cover can appear, and `uncovered` lists the
    rest, so a short answer is never mistaken for 'nothing shared'."""
    by: dict[str, dict] = {}
    for enz, kind, drug, rel, strength, source in rows:
        g = by.setdefault(enz, {"enzyme": enz, "kind": kind or "enzyme", "members": {}})
        m = g["members"].setdefault(drug, {"drug": drug, "roles": [], "sources": []})
        role = {"SUBSTRATE_OF": "is cleared by it", "INHIBITS": "slows it", "INDUCES": "speeds it up"}[rel]
        if role not in m["roles"]:
            m["roles"].append(role)
        if source and source not in m["sources"]:
            m["sources"].append(source)
    groups = []
    for g in by.values():
        if len(g["members"]) < 2:
            continue
        members = sorted(g["members"].values(), key=lambda m: m["drug"])
        acting = [m["drug"] for m in members if any(r != "is cleared by it" for r in m["roles"])]
        groups.append({"enzyme": g["enzyme"], "kind": g["kind"], "drugs": [m["drug"] for m in members], "members": members,
                       "shares_route": True, "acting": acting,
                       "meaning": (f"{', '.join(m['drug'] for m in members[:-1])} and {members[-1]['drug']} all share {g['enzyme']}"
                                   if len(members) > 2 else f"{members[0]['drug']} and {members[1]['drug']} share {g['enzyme']}")
                                  + (f" ({', '.join(acting)} {'slows or speeds' if len(acting) == 1 else 'slow or speed'} it up)" if acting else "")})
    groups.sort(key=lambda g: (-len(g["drugs"]), g["enzyme"]))
    covered = {m["drug"] for g in by.values() for m in g["members"].values()}
    return {"groups": groups, "covered": sorted(covered & set(drugs)), "uncovered": sorted(set(drugs) - covered)}


class Algos:
    def __init__(self, host="localhost", port=int(os.getenv("FALKORDB_PORT", "6379"))):
        self.g = FalkorDB(host=host, port=port, password=os.getenv("GRAPHMEM_DB_PASSWORD") or None).select_graph(REF_GRAPH)

    def _run(self, q, p):
        return {"cypher": " ".join(q.split()), "rows": self.g.ro_query(q, p).result_set}

    def hub_drugs(self, n: int = 10) -> dict:
        r = self._run(Q_PR, {"n": n})
        r["rows"] = [{"drug": a, "score": round(b, 5)} for a, b in r["rows"]]
        return r

    def drug_profile(self, drugs: list[str]) -> dict:
        """Interaction counts per drug by listed severity (DDInter), for the metadata shown on a graph node.
        One indexed query per drug: a single UNWIND form cannot use the name index and times out for heavy drugs."""
        out = {}
        for d in drugs:
            levels: dict[str, int] = {}
            for lvl, c in self.g.ro_query("MATCH (:Drug {name:$n})-[r:INTERACTS]-() RETURN r.level, count(r)", {"n": d}).result_set:
                levels[str(lvl).lower()] = c
            out[d] = {"levels": levels, "total": sum(levels.values())}
        return out

    def clusters(self, n: int = 5) -> dict:
        r = self._run(Q_WCC, {"n": n})
        r["rows"] = [{"component": a, "size": b, "sample": c} for a, b, c in r["rows"]]
        return r

    def pathways(self, drugs: list[str]) -> dict:
        """The medicines on record grouped by the enzyme or transporter they share (a traversal from each drug to the Enzyme nodes of the FDA tables), with the Cypher."""
        d = sorted({norm(x) for x in drugs})
        r = self._run(Q_PATHWAYS, {"d": d})
        out = group_pathways(r["rows"], d)
        out["cypher"] = r["cypher"]
        return out

    def regimen_hubs(self, drugs: list[str]) -> dict:
        r = self._run(Q_REG, {"d": sorted({norm(x) for x in drugs})})
        r["rows"] = [{"drug": a, "hazards_in_regimen": b, "weight": round(w, 2)} for a, b, w in r["rows"]]
        return r
