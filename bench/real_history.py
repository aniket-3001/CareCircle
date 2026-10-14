"""B4: does the code graph predict what really changes together in real git history?

For each repo: load the imports/calls/co-change graph from the OLDEST 80% of commits into FalkorDB, then for each of the NEWEST
20% commits (2..15 python files) ask, for every file in the commit, "which other files change with this one?" and check against
what the commit actually touched. Ranked lists of 10 candidates; metrics: recall@10 (share of the commit's other files found) and
MRR of the first correct file.

Methods (all but `random` and `name` are FalkorDB queries through the engine's own tools):
  random     10 random tracked files            name   same directory / shared filename tokens
  cochange   past co-change counts only         graph  import-graph neighbours by hop distance (dependants + dependencies)
  fused      reciprocal-rank fusion of cochange and graph

Caveats printed with results: import/call structure is read from the repo's HEAD, so a few test-commit edges may be visible to the
graph that were not yet present at train time (the co-change signal is leak-free); repos have short histories in this environment.

  PYTHONPATH=. python bench/real_history.py <repo_dir> [<repo_dir> ...]
"""
import asyncio
import random
import re
import sys
from pathlib import Path

from graphmem import Db, GraphMem
from graphmem.repo_loader import load_repo

K = 10


def toks(p):
    return set(re.findall(r"[a-z]+", Path(p).stem.lower())) - {"init", "test", "tests"}


def name_rank(f, files):
    d = str(Path(f).parent)
    sc = [(2 * (str(Path(o).parent) == d) + len(toks(f) & toks(o)), o) for o in files if o != f]
    return [o for s, o in sorted(sc, key=lambda x: (-x[0], x[1])) if s > 0][:K]


def rrf(*lists):
    s = {}
    for lst in lists:
        for r, x in enumerate(lst):
            s[x] = s.get(x, 0) + 1 / (60 + r)
    return [x for x, _ in sorted(s.items(), key=lambda kv: (-kv[1], kv[0]))][:K]


def score(pred, truth):
    hits = [i for i, p in enumerate(pred) if p in truth]
    return len(set(pred) & truth) / len(truth), (1 / (hits[0] + 1) if hits else 0.0)


async def run(repo):
    data = load_repo(repo)
    files = [f["id"] for f in data["files"] if f["kind"] == "file"]
    commits = sorted(data["commits"], key=lambda c: c["ts"])
    cut = int(len(commits) * 0.8)
    train, test = commits[:cut], [c for c in commits[cut:] if 2 <= len(c["files"]) <= 15]
    db = Db(); gm = GraphMem(db)
    tenant = "b4-" + re.sub(r"[^a-z0-9]", "", Path(repo).name.lower())[:30]
    await db.drop_tenant(tenant)
    await gm.grant("bench", tenant, ("read", "write", "admin"))
    m = gm.open("bench", tenant)
    await m.code_load(**{**data, "commits": train})
    rng = random.Random(7)
    res = {k: [] for k in ("random", "name", "cochange", "graph", "fused")}
    fileset = set(files)
    for c in test:
        cf = [f for f in c["files"] if f in fileset]
        for f in cf:
            truth = set(cf) - {f}
            if not truth:
                continue
            co = [r["file"] for r in (await m.co_changed(f, K))["rows"]]
            dn = [r["file"] for r in (await m.blast_radius(f, 2, K))["rows"]]
            up = (await m.dependencies_of(f, 2, K))["rows"]
            gr = []
            for x in dn + up:
                if x not in gr and x != f:
                    gr.append(x)
            preds = {"random": rng.sample([x for x in files if x != f], min(K, len(files) - 1)), "name": name_rank(f, files),
                     "cochange": co, "graph": gr[:K], "fused": rrf(co, gr)}
            for k, p in preds.items():
                res[k].append(score(p, truth))
    await db.drop_tenant(tenant)
    n = len(res["random"])
    return dict(repo=Path(repo).name, files=len(files), train=len(train), test=len(test), queries=n,
                scores={k: (sum(r for r, _ in v) / n, sum(m for _, m in v) / n) if n else (0, 0) for k, v in res.items()})


async def main(repos):
    rows = [await run(r) for r in repos]
    print("| repo | py files | train/test commits | queries | method | recall@10 | MRR |\n|---|---|---|---|---|---|---|")
    for r in rows:
        for k, (rc, mrr) in r["scores"].items():
            print(f"| {r['repo']} | {r['files']} | {r['train']}/{r['test']} | {r['queries']} | {k} | {rc:.3f} | {mrr:.3f} |")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
