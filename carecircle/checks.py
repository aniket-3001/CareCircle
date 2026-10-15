"""Interaction checks over the shared reference graph. Reads only (GRAPH.RO_QUERY). Never says 'safe' and never advises."""
from __future__ import annotations

from falkordb import FalkorDB

from .reference import REF_GRAPH, norm
from .risk import ENZYME_WEIGHT, regimen_risk, severity_weight

DIRECT = ("MATCH (a:Drug)-[i:INTERACTS]-(b:Drug) WHERE a.name IN $d AND b.name IN $d AND a.name < b.name "
          "RETURN a.name, b.name, i.level, i.source")
# inhibitor/inducer X of enzyme E and substrate Y of E, both in the list, and no direct DDInter row already covers the pair
MECH = ("MATCH (x:Drug)-[m:INHIBITS|INDUCES]->(e:Enzyme)<-[s:SUBSTRATE_OF]-(y:Drug) "
        "WHERE x.name IN $d AND y.name IN $d AND x.name <> y.name "
        "RETURN x.name, type(m), m.strength, e.name, y.name, s.source")
KNOWN = "MATCH (d:Drug) WHERE d.name IN $d RETURN d.name"
NOTICE = "Flags are for discussion with a prescriber or pharmacist. Different references may disagree. Absence of a flag is not a statement of safety."


class Checker:
    def __init__(self, host="localhost", port=6379):
        self.g = FalkorDB(host=host, port=port).select_graph(REF_GRAPH)

    def check(self, drugs: list[str]) -> dict:
        d = sorted({norm(x) for x in drugs if x})
        known = {r[0] for r in self.g.ro_query(KNOWN, {"d": d}).result_set}
        direct, unrated, weights = [], [], []
        pairs = set()
        for a, b, lvl, src in self.g.ro_query(DIRECT, {"d": d}).result_set:
            pairs.add((a, b))
            w = severity_weight(lvl)
            item = {"kind": "direct", "drugs": [a, b], "level": lvl, "source": src}
            if w is None:
                unrated.append(item)
            else:
                item["weight"] = w
                direct.append(item); weights.append(w)
        mech = []
        for x, rel, strength, enz, y, src in self.g.ro_query(MECH, {"d": d}).result_set:
            w = ENZYME_WEIGHT[strength]
            kind = "raises exposure of" if rel == "INHIBITS" else "lowers exposure of"
            key = tuple(sorted((x, y)))
            mech.append({"kind": "enzyme_path", "path": f"{x} -{rel}({strength})-> {enz} <-SUBSTRATE_OF- {y}",
                         "meaning": f"{x} may {kind} {y} via {enz}", "weight": w, "also_in_ddinter": key in pairs,
                         "source": f"FDA CYP index table; substrate: {src}"})
            weights.append(w) if key not in pairs else None
        return {"checked": d, "not_in_reference": sorted(set(d) - known), "direct": direct, "unrated": unrated,
                "enzyme_paths": mech, "regimen_risk": regimen_risk(weights), "notice": NOTICE}
