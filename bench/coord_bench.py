"""Coordination benchmark: when shared facts change under a set of planning agents, which plans must be redone?

Scenario (per seed)
  - B base facts; D "derived" facts each inferred from 2 base facts; E second-level facts inferred from 1 derived + 1 base.
  - P plans, each built from K inputs sampled from all facts (so many depend on bases only indirectly).
  - C base facts then change (superseded).
Ground truth is computed in plain Python from the generator's own dependency table (no database involved):
a plan is stale iff one of its inputs, or anything its inputs were inferred from (transitively), changed.

Systems compared (each only decides "does this plan need a redo?")
  flat      shared store, no checks            -> never flags
  occ       one global version (optimistic CC) -> flags every plan once anything changed
  perkey    per-key versions on direct inputs  -> flags plans whose *direct* inputs changed (a fair, smarter baseline)
  graphmem  lineage in FalkorDB                -> check_plan traverses DERIVED_FROM / INFERRED_FROM / SUPERSEDES

Metrics: missed (stale plan acted on = unsafe), wasted (redo of a plan that was fine), precision, recall.
Usage: PYTHONPATH=. python bench/coord_bench.py [--seeds 5] [--bases 300] [--plans 200] [--changes 15]
"""
import argparse
import asyncio
import random
import statistics
import time
import uuid

from graphmem import Db, GraphMem


def make_world(rng, nb, nd, ne, nplans, k, nchanges):
    base = [f"b{i}" for i in range(nb)]
    deps = {b: [] for b in base}                                   # fact -> facts it was inferred from
    derived = [f"d{i}" for i in range(nd)]
    for d in derived:
        deps[d] = rng.sample(base, 2)
    second = [f"e{i}" for i in range(ne)]
    for e in second:
        deps[e] = [rng.choice(derived), rng.choice(base)]
    allf = base + derived + second
    plans = [rng.sample(allf, k) for _ in range(nplans)]
    changed = set(rng.sample(base, nchanges))
    return base, derived, second, deps, plans, changed


def closure(f, deps, memo):
    if f not in memo:
        out = {f}
        for u in deps[f]:
            out |= closure(u, deps, memo)
        memo[f] = out
    return memo[f]


def truth(plans, deps, changed):
    memo = {}
    return {i for i, inputs in enumerate(plans) if any(closure(f, deps, memo) & changed for f in inputs)}


def score(name, flagged, true_stale, n, secs):
    missed = len(true_stale - flagged)
    wasted = len(flagged - true_stale)
    tp = len(flagged & true_stale)
    prec = tp / len(flagged) if flagged else 1.0
    rec = tp / len(true_stale) if true_stale else 1.0
    return dict(system=name, missed=missed, wasted=wasted, precision=prec, recall=rec, secs=secs, n=n, stale=len(true_stale))


async def run_seed(gm, seed, a):
    rng = random.Random(seed)
    base, derived, second, deps, plans, changed = make_world(rng, a.bases, a.bases // 2, a.bases // 6, a.plans, a.k, a.changes)
    t_true = truth(plans, deps, changed)
    tenant = f"cb-{uuid.uuid4().hex[:6]}"
    await gm.grant("bench", tenant)
    m = gm.open("bench", tenant)
    fid = {}
    try:
        for i, b in enumerate(base):
            fid[b] = (await m.assert_fact(b, "val", f"v{i}", exclusive=True, at=1_000))["id"]
        for f in derived + second:
            fid[f] = (await m.assert_fact(f, "val", "x", inferred_from=[fid[u] for u in deps[f]], at=1_000))["id"]
        task = await m.create_task("bench")
        pids = [await m.create_plan(task, ["go"], derived_from=[fid[f] for f in inputs]) for inputs in plans]
        for b in changed:
            await m.assert_fact(b, "val", "CHANGED", exclusive=True, at=2_000)
        res = []
        res.append(score("flat (no checks)", set(), t_true, len(plans), 0.0))
        res.append(score("occ (global version)", set(range(len(plans))) if changed else set(), t_true, len(plans), 0.0))
        perkey = {i for i, inp in enumerate(plans) if any(f in changed for f in inp)}
        res.append(score("per-key versions", perkey, t_true, len(plans), 0.0))
        t0 = time.perf_counter()
        sem = asyncio.Semaphore(16)

        async def chk(i, p):
            async with sem:
                return i, (await m.check_plan(p))["stale"]

        flagged = {i for i, st in await asyncio.gather(*[chk(i, p) for i, p in enumerate(pids)]) if st}
        res.append(score("graphmem (FalkorDB lineage)", flagged, t_true, len(plans), time.perf_counter() - t0))
        return res
    finally:
        await gm.db.drop_tenant(tenant)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--bases", type=int, default=300)
    ap.add_argument("--plans", type=int, default=200)
    ap.add_argument("--changes", type=int, default=15)
    ap.add_argument("--k", type=int, default=4, help="inputs per plan")
    a = ap.parse_args()
    gm = GraphMem(Db(max_connections=64))
    allres = {}
    try:
        for seed in range(a.seeds):
            for r in await run_seed(gm, seed, a):
                allres.setdefault(r["system"], []).append(r)
            print(f"seed {seed} done", flush=True)
    finally:
        await (await gm._ctl()).query("MATCH (n) WHERE n.id = 'bench' DETACH DELETE n")
    r0 = next(iter(allres.values()))[0]
    print(f"\n{a.seeds} seeds; per seed: {a.plans} plans x {a.k} inputs over {a.bases} base + {a.bases//2} derived + {a.bases//6} second-level facts; "
          f"{a.changes} base facts changed; avg truly-stale plans = {statistics.mean(x['stale'] for x in next(iter(allres.values()))):.1f}/{a.plans}\n")
    print(f"{'system':32s} {'missed (unsafe)':>16s} {'wasted redos':>13s} {'precision':>10s} {'recall':>8s}")
    for name, rs in allres.items():
        f = lambda key: statistics.mean(x[key] for x in rs)
        print(f"{name:32s} {f('missed'):16.1f} {f('wasted'):13.1f} {f('precision'):10.3f} {f('recall'):8.3f}")
    g = allres["graphmem (FalkorDB lineage)"]
    print(f"\ngraphmem check time for {a.plans} plans: {statistics.mean(x['secs'] for x in g)*1e3:.0f} ms (16 concurrent)")


asyncio.run(main())
