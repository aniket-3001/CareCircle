"""FalkorDB graph algorithms over the shared reference graph (read-only). Each returns rows plus the exact Cypher that ran.

 hub_drugs     PageRank over HAZARD (symmetric moderate/major interaction graph): drugs that sit at the centre of many hazards
 clusters      WCC over HAZARD: groups of drugs connected by hazards
 regimen_hubs  which drugs in THIS regimen take part in most hazards within it (degree inside the induced subgraph)
"""
from __future__ import annotations

from falkordb import FalkorDB

from .reference import REF_GRAPH, norm

Q_PR = "CALL algo.pageRank('Drug','HAZARD') YIELD node, score RETURN node.name, score ORDER BY score DESC LIMIT $n"
Q_WCC = ("CALL algo.WCC({nodeLabels:['Drug'], relationshipTypes:['HAZARD']}) YIELD node, componentId "
         "RETURN componentId, count(node) AS size, collect(node.name)[0..5] AS sample ORDER BY size DESC LIMIT $n")
Q_REG = ("MATCH (a:Drug)-[h:HAZARD]->(b:Drug) WHERE a.name IN $d AND b.name IN $d "
         "RETURN a.name, count(b) AS hazards, sum(h.w) AS weight ORDER BY weight DESC")


class Algos:
    def __init__(self, host="localhost", port=6379):
        self.g = FalkorDB(host=host, port=port).select_graph(REF_GRAPH)

    def _run(self, q, p):
        return {"cypher": " ".join(q.split()), "rows": self.g.ro_query(q, p).result_set}

    def hub_drugs(self, n: int = 10) -> dict:
        r = self._run(Q_PR, {"n": n})
        r["rows"] = [{"drug": a, "score": round(b, 5)} for a, b in r["rows"]]
        return r

    def clusters(self, n: int = 5) -> dict:
        r = self._run(Q_WCC, {"n": n})
        r["rows"] = [{"component": a, "size": b, "sample": c} for a, b, c in r["rows"]]
        return r

    def regimen_hubs(self, drugs: list[str]) -> dict:
        r = self._run(Q_REG, {"d": sorted({norm(x) for x in drugs})})
        r["rows"] = [{"drug": a, "hazards_in_regimen": b, "weight": round(w, 2)} for a, b, w in r["rows"]]
        return r
