"""Load test: T tenants x A agents each, mixed workload through the real engine (policy checks included)."""
import asyncio, random, statistics, sys, time, uuid
from graphmem import Db, GraphMem

T = int(sys.argv[1]) if len(sys.argv) > 1 else 8
A = int(sys.argv[2]) if len(sys.argv) > 2 else 4
OPS = int(sys.argv[3]) if len(sys.argv) > 3 else 40

async def agent(mem, i, lat):
    sid = f"s{i}"
    for j in range(OPS):
        r = random.random()
        t0 = time.perf_counter()
        if r < 0.35:
            ep = await mem.add_episode(sid, "agent", f"obs {i}-{j} about topic{j%7}")
            op = "add_episode"
        elif r < 0.6:
            await mem.assert_fact(f"topic{j%7}", "relates_to", f"item{j%11}"); op = "assert_fact"
        elif r < 0.9:
            await mem.recall(f"topic{j%7}"); op = "recall"
        else:
            await mem.history(sid, 20); op = "history"
        lat.setdefault(op, []).append(time.perf_counter() - t0)

async def main():
    db = Db(max_connections=128); gm = GraphMem(db)
    run = uuid.uuid4().hex[:5]; tenants = [f"bn-{run}-{i}" for i in range(T)]
    mems = []
    for t in tenants:
        for a in range(A):
            await gm.grant(f"ag{a}", t, ("read", "write"))
            mems.append(gm.open(f"ag{a}", t))
    lat = {}
    t0 = time.perf_counter()
    await asyncio.gather(*[agent(m, i, lat) for i, m in enumerate(mems)])
    dt = time.perf_counter() - t0
    n = sum(len(v) for v in lat.values())
    print(f"{T} tenants x {A} agents, {n} ops in {dt:.2f}s = {n/dt:.0f} ops/s")
    for op, v in sorted(lat.items()):
        v.sort(); print(f"  {op:12s} n={len(v):5d} p50={statistics.median(v)*1e3:6.1f}ms p99={v[int(len(v)*.99)]*1e3:7.1f}ms")
    for t in tenants: await db.drop_tenant(t)
    g = db.client.select_graph("ctl"); await g.query("MATCH (t:Tenant) WHERE t.id STARTS WITH $p DETACH DELETE t", {"p": f"bn-{run}"})
asyncio.run(main())
