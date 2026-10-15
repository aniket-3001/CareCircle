"""Interaction checks over the shared reference graph. Reads only (GRAPH.RO_QUERY). Never says 'safe' and never advises."""
from __future__ import annotations

import difflib

from falkordb import FalkorDB

from .aliases import ALIASES
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
        mech, seen_paths = [], set()
        for x, rel, strength, enz, y, src in self.g.ro_query(MECH, {"d": d}).result_set:
            w = ENZYME_WEIGHT[strength]
            kind = "raise exposure of" if rel == "INHIBITS" else "lower exposure of"
            key = tuple(sorted((x, y)))
            if (x, rel, enz, y) in seen_paths:
                continue
            seen_paths.add((x, rel, enz, y))
            mech.append({"kind": "enzyme_path", "path": f"{x} -{rel}({strength})-> {enz} <-SUBSTRATE_OF- {y}",
                         "meaning": f"{x} may {kind} {y} via {enz}", "weight": w, "also_in_ddinter": key in pairs,
                         "x": x, "y": y, "enzyme": enz, "relation": rel, "strength": strength,
                         "source": f"FDA CYP index table; substrate: {src}"})
            weights.append(w) if key not in pairs else None
        return {"checked": d, "not_in_reference": sorted(set(d) - known), "direct": direct, "unrated": unrated,
                "enzyme_paths": mech, "regimen_risk": regimen_risk(weights), "notice": NOTICE}


    _names = None

    def candidates(self, text: str, n: int = 3) -> list[dict]:
        """Top-n drug names for a noisy string (OCR output). The human picks one; nothing is auto-accepted."""
        if self._names is None:
            self._names = [r[0] for r in self.g.ro_query("MATCH (d:Drug) RETURN d.name").result_set]
        t = norm(text)
        if not t:
            return []
        squashed = t.replace(" ", "")
        scored = {}
        for name in self._names:
            nn = name.replace(" ", "")
            if len(nn) >= 4 and nn in squashed:
                scored[name] = 0.9 + min(len(nn), 12) / 200
        for name in difflib.get_close_matches(t, self._names, n=n, cutoff=0.8):
            scored.setdefault(name, difflib.SequenceMatcher(None, t, name).ratio())
        known = set(self._names)
        for word in t.replace("-", " ").split():
            if ALIASES.get(word) in known:
                scored[ALIASES[word]] = max(scored.get(ALIASES[word], 0), 0.95)
        for word in {w for w in t.split() if len(w) >= 6 and w.isalpha()}:      # speech/OCR misspell single words: "chlorythromycin"
            for name in difflib.get_close_matches(word, self._names, n=n, cutoff=0.8):
                scored[name] = max(scored.get(name, 0), difflib.SequenceMatcher(None, word, name).ratio())
        top = sorted(scored.items(), key=lambda kv: -kv[1])[:n]
        return [{"name": k, "score": round(v, 3)} for k, v in top]
