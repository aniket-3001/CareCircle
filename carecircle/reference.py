"""Shared, read-only reference graph (`cc_ref`): drugs, DDInter interactions, FDA CYP index inhibitors/inducers/substrates.

Sources and licences are stored ON the edges (`source`), so every flag can say where it came from.
  DDInter 2.0 (CC BY-NC-SA 4.0, non-commercial) -> (:Drug)-[:INTERACTS {level, source}]-(:Drug)
  FDA "Table of Substrates, Inhibitors and Inducers" (index drugs only; the page says it is not exhaustive)
  curated supplement (carecircle/curated.py): a few common substrates, labelled `curated`, to be verified before any real use.
"""
from __future__ import annotations

import os

import csv
import html
import re
from pathlib import Path

from .curated import CURATED_SUBSTRATES

REF_GRAPH = "cc_ref"
REF_VERSION = 4          # bump when the shape of the reference graph changes: start-up reloads it when the stored version is older (2: laboratory and transporter tables; 3: allergy classes; 4: combination brands)
DATA = Path(__file__).resolve().parent.parent / "data" / "ref"


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", name or "")).strip().lower()


def parse_ddinter(paths: list[Path]) -> list[tuple[str, str, str]]:
    """(drug_a, drug_b, level) with a<b ordering, deduplicated; level in minor|moderate|major|unknown (worst wins on conflict)."""
    rank = {"unknown": 0, "minor": 1, "moderate": 2, "major": 3}
    best: dict[tuple[str, str], str] = {}
    for p in paths:
        with open(p, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                a, b = norm(r["Drug_A"]), norm(r["Drug_B"])
                if not a or not b or a == b:
                    continue
                key = (a, b) if a < b else (b, a)
                lvl = (r["Level"] or "unknown").strip().lower()
                lvl = lvl if lvl in rank else "unknown"
                if key not in best or rank[lvl] > rank[best[key]]:
                    best[key] = lvl
    return [(a, b, l) for (a, b), l in best.items()]


def _cells(row_html: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row_html, re.S)]


def _drugs(cell: str) -> list[str]:
    cell = re.sub(r"\([^()]*\)", " ", cell)                                  # every bracketed group: footnote markers like (c,d) or (a,b,d,,h,i), and code names like (GF120918)
    out = []
    for part in cell.split(","):
        n = re.sub(r"^[sr]-", "", norm(part))
        if n and n != "-":
            out.append(n)
    return out


def _enzyme_name(cell: str) -> str:
    """'CYP3A4/5' -> 'CYP3A' (the name the clinical tables and the rest of the graph use); 'CYP2C19' stays."""
    n = re.sub(r"\s*\(.*", "", cell).strip().upper()
    return "CYP3A" if n.startswith("CYP3A") else n


def parse_fda_cyp(html_text: str) -> dict:
    """Index tables only. Returns {'inhibits': [(drug, enzyme, 'strong'|'moderate')], 'induces': [...], 'substrates': [(drug, enzyme)]}."""
    tables = re.findall(r"<table.*?</table>", html_text, re.S)
    out = {"inhibits": [], "induces": [], "substrates": [], "vitro_inhibits": [], "vitro_induces": [], "transporter_substrates": [], "transporter_inhibits": []}
    for t in tables:
        rows = [_cells(r) for r in re.findall(r"<tr.*?</tr>", t, re.S)]
        if not rows:
            continue
        head = " ".join(rows[0]).lower()
        enzyme_col = lambda c: re.sub(r"\s*\(.*", "", c).strip().upper()
        if "sensitive index substrate" in head:
            for r in rows[1:]:
                for d in _drugs(r[1]) if len(r) > 1 else []:
                    out["substrates"].append((d, enzyme_col(r[0])))
        elif "strong index inhibitors" in head:
            for r in rows[1:]:
                for i, strength in ((1, "strong"), (2, "moderate")):
                    for d in _drugs(r[i]) if len(r) > i else []:
                        out["inhibits"].append((d, enzyme_col(r[0]), strength))
        elif head.strip() in ("enzyme inhibitor", "enzyme inducer"):                       # Tables 1-2 and 1-3: laboratory (in vitro) findings, a weaker kind of evidence
            key = "vitro_inhibits" if head.strip().endswith("inhibitor") else "vitro_induces"
            for r in rows[1:]:
                for d in _drugs(r[1]) if len(r) > 1 else []:
                    out[key].append((d, _enzyme_name(r[0]), "in vitro"))
        elif head.strip() in ("transporter gene substrate", "transporter gene inhibitor"):       # Tables 3-1 and 3-2: transporter proteins that move medicines in and out of cells
            key = "transporter_substrates" if head.strip().endswith("substrate") else "transporter_inhibits"
            for r in rows[1:]:
                if len(r) < 3:
                    continue
                for tname in [x.strip() for x in re.split(r"[,\n]", r[0]) if x.strip()]:
                    for d in _drugs(r[2]):
                        out[key].append((d, tname.upper() if tname.upper() != "P-GP" else "P-gp"))
        elif "strong inducers" in head:
            for r in rows[1:]:
                for i, strength in ((1, "strong"), (2, "moderate")):
                    for d in _drugs(r[i]) if len(r) > i else []:
                        out["induces"].append((d, enzyme_col(r[0]), strength))
    return out


def load(host: str = "localhost", port: int = 6379, data_dir: Path = DATA) -> dict:
    from falkordb import FalkorDB
    g = FalkorDB(host=host, port=port, password=os.getenv("GRAPHMEM_DB_PASSWORD") or None).select_graph(REF_GRAPH)
    try:
        g.delete()
    except Exception:
        pass
    g.query("CREATE INDEX FOR (d:Drug) ON (d.name)")
    g.query("CREATE INDEX FOR (e:Enzyme) ON (e.name)")
    pairs = parse_ddinter(sorted(data_dir.glob("ddinter_*.csv")))
    names = sorted({x for a, b, _ in pairs for x in (a, b)})
    base = set(names)                                              # medicines DDInter knows: the in vitro and transporter tables only add edges between these
    fda = parse_fda_cyp((data_dir / "fda_cyp.html").read_text(encoding="utf-8", errors="ignore"))
    for d, *_ in fda["inhibits"] + fda["induces"] + [(s[0],) for s in fda["substrates"]] + [(s[0],) for s in CURATED_SUBSTRATES]:
        names.append(d)
    names = sorted(set(names))
    for i in range(0, len(names), 1000):
        g.query("UNWIND $r AS n MERGE (:Drug {name:n})", {"r": names[i:i + 1000]})
    rows = [{"a": a, "b": b, "l": l} for a, b, l in pairs]
    for i in range(0, len(rows), 2000):
        g.query("UNWIND $r AS x MATCH (a:Drug {name:x.a}) MATCH (b:Drug {name:x.b}) "
                "CREATE (a)-[:INTERACTS {level:x.l, source:'DDInter 2.0'}]->(b)", {"r": rows[i:i + 2000]})
    # PageRank needs a symmetric graph (INTERACTS is stored once per pair, a<b): add both directions for moderate/major pairs only.
    sym = [{"a": a, "b": b, "w": 0.7 if l == "major" else 0.3} for a, b, l in pairs if l in ("major", "moderate")]
    for i in range(0, len(sym), 2000):
        g.query("UNWIND $r AS x MATCH (a:Drug {name:x.a}) MATCH (b:Drug {name:x.b}) "
                "CREATE (a)-[:HAZARD {w:x.w}]->(b) CREATE (b)-[:HAZARD {w:x.w}]->(a)", {"r": sym[i:i + 2000]})
    vitro_i = [(d, e, s) for d, e, s in fda["vitro_inhibits"] if d in base]
    vitro_u = [(d, e, s) for d, e, s in fda["vitro_induces"] if d in base]
    t_sub = [(d, t) for d, t in fda["transporter_substrates"] if d in base]
    t_inh = [(d, t) for d, t in fda["transporter_inhibits"] if d in base]
    enzymes = sorted({e for _, e, *_ in fda["inhibits"] + fda["induces"] + vitro_i + vitro_u} | {e for _, e in fda["substrates"]} | {e for _, e, *_ in CURATED_SUBSTRATES})
    transporters = sorted({t for _, t in t_sub + t_inh})
    g.query("UNWIND $r AS n MERGE (:Enzyme {name:n, kind:'enzyme'})", {"r": enzymes})
    g.query("UNWIND $r AS n MERGE (:Enzyme {name:n, kind:'transporter'})", {"r": transporters})             # a transporter is stored beside the enzymes: the same traversal finds both
    for rel, items, src in (("INHIBITS", fda["inhibits"], "FDA CYP index table"), ("INDUCES", fda["induces"], "FDA CYP index table"),
                            ("INHIBITS", vitro_i, "FDA in vitro table (laboratory finding)"), ("INDUCES", vitro_u, "FDA in vitro table (laboratory finding)"),
                            ("INHIBITS", [(d, t, "in vitro") for d, t in t_inh], "FDA transporter in vitro table (laboratory finding)")):
        g.query(f"UNWIND $r AS x MATCH (d:Drug {{name:x.d}}) MATCH (e:Enzyme {{name:x.e}}) "
                f"CREATE (d)-[:{rel} {{strength:x.s, source:$src}}]->(e)",
                {"r": [{"d": d, "e": e, "s": s} for d, e, s in items], "src": src})
    sub = [{"d": d, "e": e, "src": "FDA CYP index table"} for d, e in fda["substrates"]]
    sub += [{"d": d, "e": t, "src": "FDA transporter in vitro table (laboratory finding)"} for d, t in t_sub]
    sub += [{"d": d, "e": e, "src": "curated (unverified)"} for d, e, *_ in CURATED_SUBSTRATES]
    g.query("UNWIND $r AS x MATCH (d:Drug {name:x.d}) MATCH (e:Enzyme {name:x.e}) "
            "CREATE (d)-[:SUBSTRATE_OF {source:x.src}]->(e)", {"r": sub})
    from .classes import CLASS_TABLE, words_for
    g.query("CREATE INDEX FOR (c:Class) ON (c.name)")
    g.query("CREATE INDEX FOR (m:Member) ON (m.name)")
    for name, c in CLASS_TABLE.items():                              # (:Member)-[:IN_CLASS {source}]->(:Class): which ingredient belongs to which class, and who says so
        g.query("MERGE (c:Class {name:$n}) SET c.words = $w, c.atc = $a", {"n": name, "w": words_for(name, c["also"]), "a": c["atc"]})
        mem = [{"m": m, "s": s} for m, s in c["members"].items()]
        for i in range(0, len(mem), 500):
            g.query("MATCH (c:Class {name:$n}) UNWIND $r AS x MERGE (m:Member {name:x.m}) CREATE (m)-[:IN_CLASS {source:x.s}]->(c)", {"n": name, "r": mem[i:i + 500]})
    from .brands import COMBINATIONS, SOURCE as BRAND_SOURCE, squash
    g.query("CREATE INDEX FOR (b:Brand) ON (b.key)")
    g.query("CREATE INDEX FOR (i:Ingredient) ON (i.name)")
    for brand, ings in COMBINATIONS.items():                         # (:Brand)-[:CONTAINS {pos}]->(:Ingredient)-[:IS]->(:Drug): the ingredient is linked to the interaction data where the data has it
        g.query("MERGE (b:Brand {key:$k}) SET b.name = $n, b.source = $s", {"k": squash(brand), "n": brand, "s": BRAND_SOURCE})
        g.query("MATCH (b:Brand {key:$k}) UNWIND $r AS x MERGE (i:Ingredient {name:x.i}) CREATE (b)-[:CONTAINS {pos:x.p}]->(i)",
                {"k": squash(brand), "r": [{"i": i, "p": p} for p, i in enumerate(ings)]})
    g.query("UNWIND $n AS x MATCH (i:Ingredient {name:x}) MATCH (d:Drug {name:x}) MERGE (i)-[:IS]->(d)", {"n": sorted({i for ings in COMBINATIONS.values() for i in ings})})
    g.query("MERGE (m:Meta {key:'ref'}) SET m.version = $v, m.loaded_at = timestamp()", {"v": REF_VERSION})
    return {"drugs": len(names), "interacts": len(rows), "enzymes": len(enzymes), "transporters": len(transporters), "classes": len(CLASS_TABLE), "brands": len(COMBINATIONS), "fda": {k: len(v) for k, v in fda.items()}}


if __name__ == "__main__":
    print(load())
