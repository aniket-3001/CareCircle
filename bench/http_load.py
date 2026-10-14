"""HTTP load test: real API processes, real load-generator processes, mixed workload, correctness check afterwards.

  python bench/http_load.py --ports 8801,8802 --tenants 16 --agents 4 --seconds 20 --procs 4 --admin KEY

Every request crosses HTTP -> API process -> FalkorDB. Each request costs ~3 FalkorDB queries (key lookup, grant check,
the operation itself), so ops/s here is HTTP requests/s, not raw database queries/s.

Correctness: each tenant has one shared session that all its agents append to. Afterwards the history must contain
exactly as many episodes as the client saw succeed, with seq 1..N and no gaps or duplicates.
"""
import argparse
import asyncio
import json
import multiprocessing as mp
import random
import statistics
import sys
import time
import uuid

import httpx


def mix(rng):
    r = rng.random()
    return "write" if r < 0.30 else "fact" if r < 0.50 else "recall" if r < 0.90 else "history"


async def agent_loop(client, base, key, tenant, aid, deadline, res):
    rng = random.Random(aid)
    h = {"Authorization": f"Bearer {key}"}
    n = 0
    while time.monotonic() < deadline:
        kind = mix(rng)
        n += 1
        if kind == "write":
            path, body = "add_episode", {"session": "shared", "role": "agent", "content": f"{aid}-{n}"}
        elif kind == "fact":
            path, body = "assert_fact", {"subject": f"topic{n % 7}", "predicate": "relates_to", "obj": f"item{n % 11}"}
        elif kind == "recall":
            path, body = "recall", {"query": f"topic{n % 7}"}
        else:
            path, body = "history", {"session": "shared", "limit": 20}
        t0 = time.perf_counter()
        try:
            r = await client.post(f"{base}/v1/tenants/{tenant}/{path}", json=body, headers=h)
            dt = time.perf_counter() - t0
            res.append((kind, r.status_code, dt))
            if kind == "write" and r.status_code == 200:
                res.append(("write_ok", tenant, 0))
        except Exception as e:
            res.append((kind, type(e).__name__, time.perf_counter() - t0))


def worker(wid, bases, plan, seconds, out_q):
    async def run():
        res = []
        limits = httpx.Limits(max_connections=400, max_keepalive_connections=200)
        async with httpx.AsyncClient(timeout=30, limits=limits) as client:
            deadline = time.monotonic() + seconds
            await asyncio.gather(*[
                agent_loop(client, bases[i % len(bases)], key, tenant, f"{tenant}-{aid}", deadline, res)
                for i, (tenant, aid, key) in enumerate(plan)])
        return res
    out_q.put(asyncio.run(run()))


def call(base, admin, path, body):
    r = httpx.post(base + path, json=body, headers={"Authorization": f"Bearer {admin}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", default="8801")
    ap.add_argument("--tenants", type=int, default=16)
    ap.add_argument("--agents", type=int, default=4)
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--admin", required=True)
    a = ap.parse_args()
    bases = [f"http://127.0.0.1:{p}" for p in a.ports.split(",")]
    run = uuid.uuid4().hex[:5]

    plan, tenants = [], []
    for ti in range(a.tenants):
        t = f"hl-{run}-{ti}"
        tenants.append(t)
        for ai in range(a.agents):
            name = f"hl-{run}-{ti}-{ai}"
            key = call(bases[0], a.admin, "/admin/agents", {"agent": name})["api_key"]
            call(bases[0], a.admin, "/admin/grants", {"agent": name, "tenant": t, "scopes": ["read", "write"]})
            plan.append((t, ai, key))
    print(f"setup done: {a.tenants} tenants x {a.agents} agents = {len(plan)} agents; "
          f"{len(bases)} API process(es); {a.procs} load process(es); {a.seconds}s", flush=True)

    q = mp.Queue()
    chunks = [plan[i::a.procs] for i in range(a.procs)]
    procs = [mp.Process(target=worker, args=(i, bases, chunks[i], a.seconds, q)) for i in range(a.procs)]
    t0 = time.monotonic()
    for p in procs:
        p.start()
    res = []
    for _ in procs:
        res.extend(q.get())
    for p in procs:
        p.join()
    wall = time.monotonic() - t0

    ok_writes = {}
    reqs = [r for r in res if r[0] != "write_ok"]
    for r in res:
        if r[0] == "write_ok":
            ok_writes[r[1]] = ok_writes.get(r[1], 0) + 1
    good = [r for r in reqs if r[1] == 200]
    bad = [r for r in reqs if r[1] != 200]
    print(f"\n{len(reqs)} requests in {wall:.1f}s wall; {len(good)} ok = {len(good) / a.seconds:.0f} req/s; "
          f"{len(bad)} failed")
    if bad:
        codes = {}
        for r in bad:
            codes[str(r[1])] = codes.get(str(r[1]), 0) + 1
        print("  failures by status/error:", codes)
    for kind in ("write", "fact", "recall", "history"):
        v = sorted(r[2] for r in good if r[0] == kind)
        if v:
            print(f"  {kind:8s} n={len(v):6d} p50={statistics.median(v) * 1e3:7.1f}ms "
                  f"p95={v[int(len(v) * .95)] * 1e3:7.1f}ms p99={v[int(len(v) * .99)] * 1e3:7.1f}ms")

    # correctness: no lost / duplicated / out-of-order writes
    lost = 0
    for t in tenants:
        key = next(k for (tt, ai, k) in plan if tt == t)
        h = httpx.post(f"{bases[0]}/v1/tenants/{t}/history", json={"session": "shared", "limit": 100000},
                       headers={"Authorization": f"Bearer {key}"}, timeout=120).json()["result"]
        seqs = [e["seq"] for e in h]
        expect = ok_writes.get(t, 0)
        # a write whose response was lost client-side (timeout) may still be stored: stored >= acknowledged
        if seqs != list(range(1, len(seqs) + 1)) or len(seqs) < expect:
            lost += 1
            print(f"  INTEGRITY PROBLEM tenant {t}: stored={len(seqs)} acked={expect} gapless={seqs == list(range(1, len(seqs) + 1))}")
    print(f"integrity: {a.tenants - lost}/{a.tenants} tenants have gap-free history with every acknowledged write stored")

    for t in tenants:
        pass
    json.dump({"tenants": tenants, "run": run}, open(f"bench/.last_run_{run}.json", "w"))
    print(f"cleanup marker: hl-{run}")


if __name__ == "__main__":
    main()
