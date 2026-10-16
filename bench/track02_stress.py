"""Track 02 load test: many agents reading and writing at once over the HTTP API, then a consistency audit of what was stored.

  PYTHONPATH=. python bench/track02_stress.py                         # in-process app against the local FalkorDB (no network hop)
  python bench/track02_stress.py --url https://host --admin-key KEY    # a deployed server (creates and removes its own throwaway tenants)

Phases (each prints throughput and p50/p95/p99 latency per operation, and checks the result is exact):
  A  write storm      W agents append to ONE shared session and assert facts at the same time
  B  mixed            readers and writers on the same tenant together; every read must see an unbroken history
  C  claim race       K agents claim one task; exactly one may win; then 1 task per agent in parallel
  D  many tenants     T tenants written at once; each must hold exactly its own data
"""
import argparse
import asyncio
import statistics
import sys
import time
import uuid

import httpx

LAT: dict[str, list[float]] = {}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


class Api:
    def __init__(self, client, admin):
        self.c, self.admin = client, {"Authorization": f"Bearer {admin}"}
        self.errors = 0

    async def call(self, h, tenant, op, **args):
        t0 = time.perf_counter()
        for attempt in range(4):
            r = await self.c.post(f"/v1/tenants/{tenant}/{op}", json=args, headers=h)
            if r.status_code in (429, 503):                                  # shed load: back off and retry, as a client should
                await asyncio.sleep(0.05 * (attempt + 1))
                continue
            break
        LAT.setdefault(op, []).append((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            self.errors += 1
            raise RuntimeError(f"{op} {r.status_code} {r.text[:120]}")
        return r.json()["result"]

    async def agent(self, name, tenant, scopes=("read", "write")):
        r = await self.c.post("/admin/agents", json={"agent": name}, headers=self.admin)
        key = r.json()["api_key"]
        await self.c.post("/admin/grants", json={"agent": name, "tenant": tenant, "scopes": list(scopes)}, headers=self.admin)
        return {"Authorization": f"Bearer {key}"}


def report(title, n_ops, secs, ops):
    print(f"\n{title}: {n_ops} requests in {secs:.1f}s = {n_ops / secs:.0f} req/s")
    for op in ops:
        xs = LAT.get(op, [])
        if xs:
            print(f"  {op:<14} n={len(xs):<6} p50={pct(xs, .5):6.1f} ms  p95={pct(xs, .95):6.1f} ms  p99={pct(xs, .99):6.1f} ms  max={max(xs):6.1f} ms")


async def main(a):
    if a.url:
        client = httpx.AsyncClient(base_url=a.url, timeout=60, limits=httpx.Limits(max_connections=200))
        cleanup = None
    else:
        from graphmem import Db, GraphMem
        from graphmem.api import create_app
        gm = GraphMem(Db())
        app = create_app(gm, admin_key="stress-admin", rate_limit=10**9) if "rate_limit" in create_app.__code__.co_varnames else create_app(gm, admin_key="stress-admin")
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://stress", timeout=120)
        a.admin_key = "stress-admin"
    api = Api(client, a.admin_key)
    run = uuid.uuid4().hex[:6]
    made_tenants: list[str] = []
    bad = []

    # ---- A: write storm on one shared session
    t = f"tt-stress-a-{run}"; made_tenants.append(t)
    hs = [await api.agent(f"st{run}-w{i}", t) for i in range(a.agents)]

    async def writer(h, i):
        for j in range(a.per_agent):
            await api.call(h, t, "add_episode", session="shared", role="agent", content=f"{i}-{j}")
            if j % 2 == 0:
                await api.call(h, t, "assert_fact", subject=f"topic{j % 5}", predicate="seen_by", obj=f"w{i}")

    t0 = time.perf_counter()
    await asyncio.gather(*[writer(h, i) for i, h in enumerate(hs)])
    dt = time.perf_counter() - t0
    n_ep = a.agents * a.per_agent
    hist = await api.call(hs[0], t, "history", session="shared", limit=n_ep + 10)
    ok_a = len(hist) == n_ep and [e["seq"] for e in hist] == list(range(1, n_ep + 1)) and len({e["content"] for e in hist}) == n_ep
    report(f"A write storm ({a.agents} agents -> 1 session)", n_ep + len(LAT["assert_fact"]), dt, ["add_episode", "assert_fact"])
    print(f"  audit: {len(hist)}/{n_ep} events stored, seq 1..{n_ep} unbroken and unique: {'PASS' if ok_a else 'FAIL'}")
    bad += [] if ok_a else ["A"]

    # ---- B: readers and writers together
    t = f"tt-stress-b-{run}"; made_tenants.append(t)
    hs = [await api.agent(f"st{run}-m{i}", t) for i in range(a.agents)]
    writers, readers = hs[: a.agents * 2 // 3], hs[a.agents * 2 // 3:]
    stop, torn = asyncio.Event(), []
    for k in LAT:
        LAT[k].clear()

    async def mix_writer(h, i):
        for j in range(a.per_agent):
            await api.call(h, t, "add_episode", session="live", role="agent", content=f"{i}-{j}")
            await api.call(h, t, "assert_fact", subject="counter", predicate=f"v{j % 3}", obj=str(i), exclusive=True)

    async def mix_reader(h):
        while not stop.is_set():
            hi = await api.call(h, t, "history", session="live", limit=50)          # what an agent really reads: the recent turns
            sq = [e["seq"] for e in hi]
            if sq and sq != list(range(sq[0], sq[0] + len(sq))):
                torn.append(sq[:5])
            await api.call(h, t, "recall", query="counter")
            await api.call(h, t, "search_text", query="agent")
            await asyncio.sleep(0.02)                                               # a short think time between reads

    t0 = time.perf_counter()
    rtasks = [asyncio.create_task(mix_reader(h)) for h in readers]
    await asyncio.gather(*[mix_writer(h, i) for i, h in enumerate(writers)])
    stop.set()
    await asyncio.gather(*rtasks)
    dt = time.perf_counter() - t0
    total = sum(len(v) for v in LAT.values())
    final = await api.call(hs[0], t, "history", session="live", limit=5000)
    cur = (await api.call(hs[0], t, "recall", query="counter"))
    ok_b = not torn and len(final) == len(writers) * a.per_agent and len({f["predicate"] for f in cur if f["current"]}) == len([f for f in cur if f["current"]])
    report(f"B mixed ({len(writers)} writers + {len(readers)} readers)", total, dt, ["add_episode", "assert_fact", "history", "recall", "search_text"])
    print(f"  audit: {len(torn)} torn reads, {len(final)}/{len(writers) * a.per_agent} events stored, one current value per fact: {'PASS' if ok_b else 'FAIL'}")
    bad += [] if ok_b else ["B"]

    # ---- C: claim race
    t = f"tt-stress-c-{run}"; made_tenants.append(t)
    hs = [await api.agent(f"st{run}-c{i}", t) for i in range(a.agents * 2)]
    for k in LAT:
        LAT[k].clear()
    task = await api.call(hs[0], t, "create_task", title="one job")
    tasks = await asyncio.gather(*[api.call(hs[0], t, "create_task", title=f"job {i}") for i in range(len(hs))])
    LAT["create_task"].clear()
    t0 = time.perf_counter()
    wins = await asyncio.gather(*[api.call(h, t, "claim_task", task_id=task) for h in hs])
    wins2 = await asyncio.gather(*[api.call(h, t, "claim_task", task_id=tk) for h, tk in zip(hs, tasks)])
    dt = time.perf_counter() - t0
    ok_c = wins.count(True) == 1 and all(wins2)
    report(f"C claim race ({len(hs)} agents: all on 1 task, then 1 task each)", len(hs) * 2, dt, ["claim_task"])
    print(f"  audit: winners on the contended task = {wins.count(True)} (must be 1); uncontended claims all succeeded = {all(wins2)}: {'PASS' if ok_c else 'FAIL'}")
    bad += [] if ok_c else ["C"]

    # ---- D: many tenants at once
    for k in LAT:
        LAT[k].clear()
    tens = [f"tt-stress-d{i}-{run}" for i in range(a.tenants)]
    made_tenants += tens
    pairs = [(await api.agent(f"st{run}-d{i}", t)) for i, t in enumerate(tens)]

    async def tenant_job(i):
        for j in range(a.per_agent):
            await api.call(pairs[i], tens[i], "add_episode", session="s", role="agent", content=f"{i}:{j}")
        await api.call(pairs[i], tens[i], "assert_fact", subject="who", predicate="am", obj=str(i), exclusive=True)

    t0 = time.perf_counter()
    await asyncio.gather(*[tenant_job(i) for i in range(a.tenants)])
    dt = time.perf_counter() - t0
    leaks = 0
    for i in range(a.tenants):
        hi = await api.call(pairs[i], tens[i], "history", session="s", limit=1000)
        if len(hi) != a.per_agent or any(not e["content"].startswith(f"{i}:") for e in hi):
            leaks += 1
    report(f"D many tenants ({a.tenants} tenants at once)", a.tenants * (a.per_agent + 1), dt, ["add_episode", "assert_fact"])
    print(f"  audit: tenants holding anything other than exactly their own data = {leaks}: {'PASS' if leaks == 0 else 'FAIL'}")
    bad += [] if leaks == 0 else ["D"]

    print(f"\nrequest errors: {api.errors}   result: {'ALL PASS' if not bad and api.errors == 0 else 'FAILED ' + ','.join(bad)}")
    if not a.url:                                                           # a throwaway local run leaves nothing behind
        for tn in made_tenants:
            try:
                await gm.db.drop_tenant(tn)
            except Exception:
                pass
        ctl = gm.db.client.select_graph("ctl")
        await ctl.query("MATCH (a:Agent) WHERE a.id STARTS WITH $p DETACH DELETE a", {"p": f"st{run}"})
    await client.aclose()
    return 0 if not bad and api.errors == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--admin-key", default="")
    ap.add_argument("--agents", type=int, default=30)
    ap.add_argument("--per-agent", type=int, default=20)
    ap.add_argument("--tenants", type=int, default=30)
    sys.exit(asyncio.run(main(ap.parse_args())))
