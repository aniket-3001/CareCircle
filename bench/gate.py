"""Paired comparison of two benchmark runs: a baseline and a candidate. It refuses to compare runs that are not alike, then prints every check.

  python bench/care_bench.py --out candidate.json
  python bench/gate.py bench/baselines/care_bench.json candidate.json [--tolerance 0.25] [--skip B1,B5]

Exit 0: no regression.  Exit 1: at least one metric got worse.  Exit 2: the two runs are not comparable, so nothing was judged.

A result file is {"bench", "schema", "meta": {"seed", "params", "host", "falkordb", "git"}, "metrics": {name: {"value", "kind"}}}.
Each metric states how it is judged:
  exact    must be identical (a count that comes from the data or the design, e.g. pairs found, rounds run)
  higher   must not fall (a count of things done right)
  lower    must not rise by more than the tolerance plus a small noise floor (a latency); judged only when both runs ran on the same machine
  info     printed, never judged
"""
from __future__ import annotations

import argparse
import json
import sys

SCHEMA = 1
NOISE_MS = 2.0                 # a latency may also wander this much in absolute terms, so a 3 ms to 4 ms move is not "33% worse"


class Refused(Exception):
    """The two runs differ in something that makes a comparison meaningless."""


def _need(doc: dict, name: str) -> None:
    for key in ("bench", "schema", "meta", "metrics"):
        if key not in doc:
            raise Refused(f"{name} is not a benchmark result: no '{key}'")
    if doc["schema"] != SCHEMA:
        raise Refused(f"{name} has schema {doc['schema']}, this gate reads schema {SCHEMA}")


def compare(base: dict, cand: dict, tolerance: float = 0.25, skip: tuple[str, ...] = ()) -> tuple[int, list[str]]:
    """Returns (exit code, every line to print). Pure: no files, no clock."""
    out: list[str] = []
    try:
        _need(base, "the baseline")
        _need(cand, "the candidate")
        problems = []
        if base["bench"] != cand["bench"]:
            problems.append(f"different benchmarks: {base['bench']!r} vs {cand['bench']!r}")
        for key in ("seed", "params"):
            if base["meta"].get(key) != cand["meta"].get(key):
                problems.append(f"{key} differs: baseline {base['meta'].get(key)!r}, candidate {cand['meta'].get(key)!r}")
        only_base = sorted(set(base["metrics"]) - set(cand["metrics"]))
        only_cand = sorted(set(cand["metrics"]) - set(base["metrics"]))
        if only_base:
            problems.append(f"metrics missing from the candidate: {', '.join(only_base)}")
        if only_cand:
            problems.append(f"metrics missing from the baseline: {', '.join(only_cand)}")
        for name in sorted(set(base["metrics"]) & set(cand["metrics"])):
            if base["metrics"][name]["kind"] != cand["metrics"][name]["kind"]:
                problems.append(f"{name} is judged differently in the two runs")
        if problems:
            raise Refused("; ".join(problems))
    except Refused as e:
        return 2, [f"REFUSED  {e}", "Nothing was compared: a gate that compared unlike runs would prove nothing."]

    same_host = base["meta"].get("host") == cand["meta"].get("host")
    for key in ("falkordb", "git"):
        if base["meta"].get(key) != cand["meta"].get(key):
            out.append(f"note     {key}: baseline {base['meta'].get(key)!r}, candidate {cand['meta'].get(key)!r}")
    if not same_host:
        out.append("note     different machines: latencies are not judged")
    failed = 0
    for name in sorted(base["metrics"]):
        b, c = base["metrics"][name], cand["metrics"][name]
        bv, cv, kind = b["value"], c["value"], b["kind"]
        shown = f"{name}: baseline {bv}, candidate {cv}"
        if any(name.startswith(p) for p in skip if p):
            out.append(f"SKIP     {shown}  (skipped by request)")
        elif kind == "info":
            out.append(f"info     {shown}")
        elif kind == "exact":
            ok = bv == cv
            failed += not ok
            out.append(f"{'PASS' if ok else 'FAIL'}     {shown}  (must be identical)")
        elif kind == "higher":
            ok = cv >= bv
            failed += not ok
            out.append(f"{'PASS' if ok else 'FAIL'}     {shown}  (must not fall)")
        elif kind == "lower":
            if not same_host:
                out.append(f"SKIP     {shown}  (different machine)")
                continue
            limit = bv * (1 + tolerance) + NOISE_MS
            ok = cv <= limit
            failed += not ok
            out.append(f"{'PASS' if ok else 'FAIL'}     {shown}  (must stay within {limit:.1f})")
        else:
            return 2, [f"REFUSED  {name} has an unknown kind {kind!r}"]
    out.append(f"REGRESSION  {failed} of {len(base['metrics'])} metrics got worse" if failed else f"OK  no metric got worse ({len(base['metrics'])} listed)")
    return (1 if failed else 0), out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--tolerance", type=float, default=0.25, help="how much a latency may rise, as a fraction (default 0.25)")
    ap.add_argument("--skip", default="", help="comma-separated metric name prefixes not to judge (they are listed as SKIP)")
    a = ap.parse_args(argv)
    docs = []
    for path in (a.baseline, a.candidate):
        try:
            with open(path, encoding="utf-8") as f:
                docs.append(json.load(f))
        except (OSError, ValueError) as e:
            print(f"REFUSED  cannot read {path}: {e}")
            return 2
    code, lines = compare(docs[0], docs[1], a.tolerance, tuple(p.strip() for p in a.skip.split(",")))
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
