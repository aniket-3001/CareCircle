"""Interaction checks over the shared reference graph. Reads only (GRAPH.RO_QUERY). Never says 'safe' and never advises."""
from __future__ import annotations

import os
import re

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
        "RETURN x.name, type(m), m.strength, e.name, y.name, s.source, m.source, e.kind")
KNOWN = "MATCH (d:Drug) WHERE d.name IN $d RETURN d.name"
NOTICE = "Flags are for discussion with a prescriber or pharmacist. Different references may disagree. Absence of a flag is not a statement of safety."


class Checker:
    def __init__(self, host="localhost", port=6379):
        self.g = FalkorDB(host=host, port=port, password=os.getenv("GRAPHMEM_DB_PASSWORD") or None).select_graph(REF_GRAPH)

    def class_hits(self, text: str, drugs: list[str]) -> dict:
        """Which of these medicines belong to a class the typed allergy names, by walking (:Member)-[:IN_CLASS]->(:Class) in the reference graph.
        {classes: [names found in the text], hits: [{class, drug, source}], from_graph: bool}. When the reference graph holds no classes (an older copy), the
        same two sources are read from the files instead, so the answer does not depend on which copy is loaded."""
        t = " " + re.sub(r"[^a-z0-9+\- ]+", " ", text.lower()) + " "
        try:
            rows = self.g.ro_query("MATCH (c:Class) RETURN c.name, c.words").result_set
        except Exception:
            rows = []
        if not rows:
            from .classes import CLASS_TABLE, classes_named_in
            named = classes_named_in(text)
            return {"classes": named, "from_graph": False, "hits": [{"class": n, "drug": d, "source": CLASS_TABLE[n]["members"][d]} for n in named for d in drugs if d in CLASS_TABLE[n]["members"]]}
        named = [n for n, words in rows if any(f" {w} " in t for w in words)]
        hits = []
        for n in named:
            hits += [{"class": n, "drug": r[0], "source": r[1]} for r in self.g.ro_query(
                "MATCH (m:Member)-[r:IN_CLASS]->(c:Class {name:$c}) WHERE m.name IN $d RETURN m.name, r.source", {"c": n, "d": list(drugs)}).result_set]
        return {"classes": named, "hits": hits, "from_graph": True}

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
        rows = sorted(self.g.ro_query(MECH, {"d": d}).result_set, key=lambda r: ({"strong": 0, "moderate": 1, "in vitro": 2}.get(r[2], 3), r[0], r[4], r[3]))      # clinical evidence first: a laboratory finding never replaces it
        for x, rel, strength, enz, y, src, msrc, ekind in rows:
            w = ENZYME_WEIGHT[strength]
            kind = "raise exposure of" if rel == "INHIBITS" else "lower exposure of"
            transporter = ekind == "transporter"
            vitro = strength == "in vitro"
            key = tuple(sorted((x, y)))
            if (x, rel, enz, y) in seen_paths:
                continue
            seen_paths.add((x, rel, enz, y))
            if transporter:                                       # one flag per pair and relation, naming every transporter they share (not one line per protein)
                same = next((m for m in mech if m["x"] == x and m["y"] == y and m["relation"] == rel and m["target"] == "transporter"), None)
                if same is not None:
                    same.setdefault("also_via", []).append(enz)
                    same["meaning"] = same["meaning"].replace(" transporter", f" transporter (also {', '.join(same['also_via'])})", 1) if len(same["also_via"]) == 1                         else re.sub(r"\(also [^)]*\)", f"(also {', '.join(same['also_via'])})", same["meaning"], count=1)
                    continue
            mech.append({"kind": "enzyme_path", "path": f"{x} -{rel}({strength})-> {enz} <-SUBSTRATE_OF- {y}",
                         "meaning": (f"{x} may {kind} {y} via {enz}" if not transporter else f"{x} may {kind} {y} through the {enz} transporter")
                                    + (" (a laboratory finding, not shown in people)" if vitro else ""), "weight": w, "also_in_ddinter": key in pairs,
                         "x": x, "y": y, "enzyme": enz, "relation": rel, "strength": strength, "target": "transporter" if transporter else "enzyme",
                         "source": f"{msrc or 'FDA CYP index table'}; substrate: {src}"})
            weights.append(w) if key not in pairs else None
        n_known = len(known)
        total = n_known * (n_known - 1) // 2
        covered = len(pairs)
        coverage = {"medicines": len(d), "in_reference": n_known, "pairs_possible": total, "pairs_listed": covered, "rated": len(direct), "unrated": len(unrated),
                    "not_listed": total - covered, "enzyme_paths": len(mech),
                    "statement": (f"Of {total} possible pairs among the {n_known} medicines the reference data knows, the source lists {covered}: {len(direct)} with a severity, "
                                  f"{len(unrated)} without one; {total - covered} are not listed. A pair that is not listed has not been rated as safe." if total else "Fewer than two medicines are known to the reference data.")}
        return {"checked": d, "not_in_reference": sorted(set(d) - known), "direct": direct, "unrated": unrated,
                "enzyme_paths": mech, "regimen_risk": regimen_risk(weights), "coverage": coverage, "notice": NOTICE}


    _names = None

    def known_names(self) -> set[str]:
        if self._names is None:
            self._names = [r[0] for r in self.g.ro_query("MATCH (d:Drug) RETURN d.name").result_set]
        return set(self._names)

    def resolve(self, text: str, n: int = 3) -> list[dict]:
        """candidates(), then, when none is a strong match, RxNorm (a public NLM service, name only). Only ingredients that exist in the reference
        graph are kept, so every suggestion can be checked, and each carries where it came from. A person still picks."""
        from . import external
        out = self.candidates(text, n)
        if out and out[0]["score"] >= 0.9:
            return out
        known = self.known_names()
        for ing in external.rxnorm_ingredients(text):
            if ing["name"] in known and ing["name"] not in {c["name"] for c in out}:
                out.append({"name": ing["name"], "score": 0.9, "via": ing["source"], "rxcui": ing["rxcui"]})
        return sorted(out, key=lambda c: -c["score"])[:n]

    def search(self, text: str, n: int = 8) -> list[dict]:
        """Medicines in the reference list whose name starts with, or contains, what was typed (a plain name search, for a person looking something up)."""
        if self._names is None:
            self._names = [r[0] for r in self.g.ro_query("MATCH (d:Drug) RETURN d.name").result_set]
        t = norm(text)
        if len(t) < 2:
            return []
        starts = sorted(x for x in self._names if x.startswith(t))
        inside = sorted(x for x in self._names if t in x and not x.startswith(t))
        return [{"name": x, "score": 1.0 if x.startswith(t) else 0.8} for x in (starts + inside)[:max(1, min(n, 20))]]

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
