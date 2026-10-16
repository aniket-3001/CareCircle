"""Run a benchmark several times and report the spread, so a figure is not one lucky or unlucky run.

  PYTHONPATH=. python bench/repeat.py care_bench --runs 5          # B1-B5: exact results must be identical every run, latencies get median/min/max
  PYTHONPATH=. python bench/repeat.py track02_stress --runs 5      # load test: req/s and p50/p95/p99 per phase and operation, plus whether every audit passed
  PYTHONPATH=. python bench/repeat.py track02_stress --runs 5 --markdown out.md -- --agents 20

Everything after `--` goes to the benchmark. The script prints a table; `--markdown FILE` also writes it. It exits 1 if any run failed its own checks or an exact result
differed between runs. It runs the benchmarks one after another, never at the same time (they share one database)."""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

RATE = re.compile(r"^(?P<phase>.+?): (?P<n>\d+) requests in (?P<s>[\d.]+)s = (?P<rps>\d+) req/s")
LAT = re.compile(r"^\s+(?P<op>[\w.:/-]+)\s+(?:n=\d+\s+)?p50=\s*(?P<p50>[\d.]+) ms\s+p95=\s*(?P<p95>[\d.]+) ms\s+p99=\s*(?P<p99>[\d.]+) ms")
EVENTS = re.compile(r"^\s*(?P<what>one request per event|batches of 20)\s*:\s*(?P<eps>\d+) events/s")
VERDICT = re.compile(r"result: (ALL PASS|FAILED.*)$")


def parse_stress(text: str) -> dict:
    """{'metrics': {name: number}, 'passed': bool|None} from one run of track02_stress.py (names are 'phase / op / p95_ms' and 'phase / req/s')."""
    metrics, phase, passed = {}, "", None
    for line in text.splitlines():
        if m := RATE.match(line.strip()):
            phase = m["phase"]
            metrics[f"{phase} / req/s"] = float(m["rps"])
        elif line.startswith("E batch writes"):
            phase = "E batch writes"
        elif m := EVENTS.match(line):
            metrics[f"{phase} / {m['what']} / events/s"] = float(m["eps"])
        elif m := LAT.match(line):
            for k in ("p50", "p95", "p99"):
                metrics[f"{phase} / {m['op']} / {k}_ms"] = float(m[k])
        elif m := VERDICT.search(line):
            passed = m[1] == "ALL PASS"
    return {"metrics": metrics, "passed": passed}


def parse_care(path: str) -> dict:
    """{'metrics': {name: (value, kind)}} from care_bench's --out file."""
    with open(path, encoding="utf-8") as f:
        return {k: (v["value"], v["kind"]) for k, v in json.load(f)["metrics"].items()}


def spread(xs: list[float]) -> tuple[float, float, float]:
    return statistics.median(xs), min(xs), max(xs)


def summarise_stress(runs: list[dict]) -> tuple[list[list[str]], bool]:
    names = sorted({k for r in runs for k in r["metrics"]})
    rows = []
    for n in names:
        xs = [r["metrics"][n] for r in runs if n in r["metrics"]]
        med, lo, hi = spread(xs)
        rows.append([n, f"{med:g}", f"{lo:g}", f"{hi:g}", str(len(xs))])
    ok = all(r["passed"] is True for r in runs)
    return rows, ok


def summarise_care(runs: list[dict]) -> tuple[list[list[str]], bool]:
    rows, ok = [], True
    for n in sorted(runs[0]):
        vals = [r[n][0] for r in runs]
        kind = runs[0][n][1]
        if kind in ("exact", "info") or not all(isinstance(v, (int, float)) for v in vals):
            same = all(v == vals[0] for v in vals)
            if kind == "exact" and not same:
                ok = False
            rows.append([n, str(vals[0]) if same else f"DIFFERS: {vals}", "", "", str(len(vals))])
        else:
            med, lo, hi = spread(vals)
            rows.append([n, f"{med:g}", f"{lo:g}", f"{hi:g}", str(len(vals))])
    return rows, ok


def table(rows: list[list[str]]) -> str:
    head = ["metric", "median", "min", "max", "runs"]
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def run_one(bench: str, extra: list[str], tmp: str) -> tuple[int, str]:
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, os.path.join(HERE, f"{bench}.py"), *extra]
    if bench == "care_bench":
        cmd += ["--out", tmp]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT)
    return p.returncode, p.stdout + p.stderr


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bench", choices=["care_bench", "track02_stress"])
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--markdown", help="also write the table to this file")
    a, extra = ap.parse_known_args(argv)
    extra = [x for x in extra if x != "--"]
    if a.runs < 2:
        ap.error("--runs must be at least 2, or there is no spread to report")
    results, bad_exit = [], 0
    with tempfile.TemporaryDirectory() as d:
        for i in range(a.runs):
            tmp = os.path.join(d, f"run{i}.json")
            code, out = run_one(a.bench, extra, tmp)
            bad_exit += code != 0
            print(f"run {i + 1}/{a.runs}: exit {code}", flush=True)
            if a.bench == "care_bench":
                if code == 0:
                    results.append(parse_care(tmp))
            else:
                results.append(parse_stress(out))
    if not results:
        print("no run produced results")
        return 1
    rows, ok = (summarise_care if a.bench == "care_bench" else summarise_stress)(results)
    text = table(rows)
    print("\n" + text)
    verdict = f"{len(results)} of {a.runs} runs produced results; {bad_exit} exited with an error; checks " + ("passed in every run" if ok and not bad_exit else "FAILED somewhere")
    print("\n" + verdict)
    if a.markdown:
        with open(a.markdown, "w", encoding="utf-8") as f:
            f.write(text + "\n\n" + verdict + "\n")
    return 0 if ok and not bad_exit else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
