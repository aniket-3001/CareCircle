"""Proof harness. Runs each Track 02 requirement as an end-to-end scenario against a live FalkorDB and prints PASS/FAIL
with the evidence. Also restarts the FalkorDB container to test durability, and compares recall against a flat
(no-links) baseline.   Usage: PYTHONPATH=. python bench/proof.py [--no-restart]"""
import asyncio
import subprocess
import sys
import time
import uuid

from graphmem import Db, GraphMem, PermissionDenied

RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}", flush=True)


class FlatBaseline:
    """Same data, no relationships: a list of (subject, predicate, object) rows and keyword search over them.
    Deliberately the simplest alternative store; a comparison point, not a claim about all databases."""

    def __init__(self):
        self.rows = []

    def add(self, s, p, o):
        self.rows.append((s.lower(), p, o.lower()))

    def recall(self, q):
        q = q.lower()
        return [r for r in self.rows if q in r[0] or q in r[2]]


async def main(restart: bool):
    db = Db(max_connections=128)
    gm = GraphMem(db)
    run = uuid.uuid4().hex[:5]
    made = []

    def T(label):
        t = f"pf-{run}-{label}"
        made.append(t)
        return t

    try:
        # 1. isolation under concurrency: 20 tenants x 3 agents write secrets concurrently, then try cross-reads
        tenants = [T(f"t{i}") for i in range(20)]
        mems = {}
        for t in tenants:
            for a in range(3):
                await gm.grant(f"{t}-ag{a}", t)
                mems[(t, a)] = gm.open(f"{t}-ag{a}", t)

        async def writer(t, a):
            m = mems[(t, a)]
            for j in range(10):
                await m.add_episode("s", "u", f"SECRET-{t}-{a}-{j}")
                await m.assert_fact(f"{t}-subject", "knows", f"SECRET-{t}-{a}")

        t0 = time.perf_counter()
        await asyncio.gather(*[writer(t, a) for t in tenants for a in range(3)])
        dt = time.perf_counter() - t0
        leaks = denied = 0
        for i, t in enumerate(tenants):
            other = tenants[(i + 1) % len(tenants)]
            for a in range(3):
                h = await mems[(t, a)].search_episodes("SECRET-" + t)
                leaks += sum(1 for e in h if not e["content"].startswith("SECRET-" + t))
            try:
                await gm.open(f"{t}-ag0", other).history("s")
            except PermissionDenied:
                denied += 1
        total = len(tenants) * 3 * 10 * 2
        record("tenant isolation under concurrency", leaks == 0 and denied == len(tenants),
               f"{total} writes by 60 agents in {dt:.1f}s; cross-tenant leaks={leaks}; cross-tenant reads denied {denied}/{len(tenants)}")

        # 2. ordering and no lost writes in one shared session
        t = T("order")
        ags = [f"{t}-w{i}" for i in range(12)]
        for a in ags:
            await gm.grant(a, t)
        ms = [gm.open(a, t) for a in ags]
        await asyncio.gather(*[m.add_episode("shared", "a", f"{i}-{j}") for i, m in enumerate(ms) for j in range(25)])
        h = await ms[0].history("shared", limit=1000)
        seqs = [e["seq"] for e in h]
        record("concurrent writers, one session", seqs == list(range(1, 301)),
               f"300 writes from 12 agents -> {len(h)} stored, seq gap/dup-free={seqs == list(range(1, 301))}")

        # 3. exactly one winner among 30 racers, repeated 10 times
        wins = []
        for r in range(10):
            t = T(f"race{r}")
            ags = [f"{t}-a{i}" for i in range(30)]
            for a in ags:
                await gm.grant(a, t)
            ms = [gm.open(a, t) for a in ags]
            tk = await ms[0].create_task("x")
            wins.append(sum(await asyncio.gather(*[m.claim_task(tk) for m in ms])))
        record("task claim race", wins == [1] * 10, f"10 rounds x 30 agents, winners per round={wins}")

        # 4. stale plan across a handoff
        t = T("plan")
        await gm.grant(f"{t}-a", t)
        await gm.grant(f"{t}-b", t)
        a, b = gm.open(f"{t}-a", t), gm.open(f"{t}-b", t)
        f = await a.assert_fact("deadline", "is", "friday", exclusive=True, at=1000)
        tk = await a.create_task("t")
        await a.claim_task(tk)
        pl = await a.create_plan(tk, ["go"], derived_from=[f["id"]])
        await a.handoff(tk, f"{t}-b", plan_id=pl)
        before = (await b.check_plan(pl))["stale"]
        await a.assert_fact("deadline", "is", "wednesday", exclusive=True, at=2000)
        after = (await b.check_plan(pl))["stale"]
        record("stale plan caught after handoff", (before, after) == (False, True),
               f"stale before change={before}, after change={after}")

        # 5. graph recall vs flat baseline: chains the query never mentions directly
        t = T("hops")
        await gm.grant(f"{t}-x", t)
        m = gm.open(f"{t}-x", t)
        flat = FlatBaseline()
        for s_, p_, o_ in [("dana", "works_at", "initech"), ("initech", "located_in", "austin"),
                           ("austin", "in_state", "texas")]:
            await m.assert_fact(s_, p_, o_)
            flat.add(s_, p_, o_)
        g1 = {r["object"] for r in await m.recall("dana", hops=1)}
        g2 = {r["object"] for r in await m.recall("dana", hops=2)}
        fl = {r[2] for r in flat.recall("dana")}
        record("multi-hop recall vs flat baseline", "austin" in g2 and "austin" not in g1 and "austin" not in fl,
               f"query 'dana': flat={sorted(fl)} graph(1 hop)={sorted(g1)} graph(2 hops)={sorted(g2)}")

        # 6. every recalled fact has provenance and a path
        t = T("prov")
        await gm.grant(f"{t}-x", t)
        m = gm.open(f"{t}-x", t)
        ep = await m.add_episode("s", "u", "Erin joined Globex")
        await m.assert_fact("erin", "joined", "globex", sources=[ep["id"]])
        r = (await m.recall("erin"))[0]
        record("answers carry provenance + path", bool(r["provenance"]) and bool(r["path"]),
               f"path='{r['path']}' source={r['provenance'][0]['episode'] if r['provenance'] else None}")

        # 7. forget leaves nothing behind
        ep = await m.add_episode("s", "u", "pin is 7421")
        f = await m.assert_fact("pin", "is", "7421", sources=[ep["id"]])
        await m.forget_fact(f["id"], "test", redact_sources=True)
        left = (await m._q("MATCH (n) WHERE any(k IN keys(n) WHERE toString(n[k]) CONTAINS '7421') RETURN count(n)",
                           scope="read"))[0][0]
        record("forget removes value from whole graph", left == 0, f"nodes still containing the value={left}")

        # 8. durability across a real FalkorDB container restart
        if restart:
            t = T("dur")
            await gm.grant(f"{t}-x", t)
            m = gm.open(f"{t}-x", t)
            ep = await m.add_episode("s", "u", "survive the restart")
            await m.assert_fact("durable", "fact", "yes", sources=[ep["id"]])
            subprocess.run(["docker", "restart", "falkordb-dev"], capture_output=True, timeout=120)
            db2 = None
            for _ in range(40):
                try:
                    db2 = Db()
                    await db2.client.list_graphs()
                    break
                except Exception:
                    db2 = None
                    time.sleep(1)
            if db2 is None:
                record("durability across FalkorDB container restart", False, "server did not come back")
            else:
                gm2 = GraphMem(db2)
                try:
                    m2 = gm2.open(f"{t}-x", t)
                    ok = ((await m2.history("s"))[0]["content"] == "survive the restart"
                          and (await m2.recall("durable"))[0]["object"] == "yes"
                          and "write" in await gm2.scopes(f"{t}-x", t))
                    record("durability across FalkorDB container restart", ok,
                           f"history, facts and grants survived={ok}")
                except Exception as e:
                    record("durability across FalkorDB container restart", False, f"{type(e).__name__}: {e}")
                db, gm = db2, gm2
    finally:
        for t in made:
            try:
                await db.drop_tenant(t)
            except Exception:
                pass
        try:
            await (await gm._ctl()).query("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n", {"p": f"pf-{run}"})
        except Exception:
            pass
    bad = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} scenarios passed" + (f"; FAILED: {bad}" if bad else ""))
    sys.exit(1 if bad else 0)


asyncio.run(main("--no-restart" not in sys.argv))
