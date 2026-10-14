"""B2: concurrent agents editing shared state - how much work is lost, redone or silently overwritten?

8 agents start from the same snapshot of 200 exclusive facts (one value per key). Each does a task of 20 writes; a fraction `overlap`
of the writes goes to a small hot set of 10 keys the others also write (with their own values), the rest to private keys.
Ground truth: serial execution in agent order (last writer wins per key); a key is in true conflict when an earlier-merged agent
wrote a different value to it.

  lww        everyone writes straight to shared state          -> conflicts caught 0, silent overwrites = every lost write
  occ        each task commits atomically, aborts and redoes the WHOLE task if any key it wrote changed since its snapshot
  graph      real graphmem: each agent forks (GRAPH.COPY), writes on its fork, dry-run merge, apply with on_conflict=skip, then
             re-asserts only the skipped (conflicting) writes on the tenant -> redo = conflicting writes only
  lock       one global lock: nothing lost or redone, but tasks run strictly one after another (wall time = sum)

Metrics: conflicts caught, silent overwrites (must be 0 for any system that claims safety), redone writes, parallel wall time in
"write units" (lock = sum of tasks; others = longest task + redo), final-state equals serial truth.
"Wall" assumes agents work in parallel and OCC redoes run in parallel, while graph redo writes go through one tenant graph
(serialized), which is why graph is not faster than OCC in wall time. Caveat: lww/occ/lock are in-process models of the strategies, only `graph` runs on FalkorDB. Synthetic workload, 3 seeds.

  PYTHONPATH=. python bench/branch_bench.py [--seeds 3]
"""
import argparse
import asyncio
import os
import random
import statistics

os.environ.setdefault("GRAPHMEM_MAX_FORKS", "32")

from graphmem import Db, GraphMem                                    # noqa: E402
from graphmem.branch import fork, merge, open_fork                  # noqa: E402

AGENTS, STEPS, KEYS, HOT = 8, 20, 200, 10


def workload(rng, overlap):
    tasks = []
    for a in range(AGENTS):
        w, hot_used = [], rng.sample(range(HOT), min(HOT, int(STEPS * overlap)))
        priv = rng.sample(range(HOT + a * 20, HOT + a * 20 + 20), STEPS - len(hot_used))
        for k in hot_used + priv:
            w.append((f"k{k}", f"v{a}-{k}"))
        tasks.append(w)
    return tasks


def truth(tasks):
    final, conflicts = {}, 0
    for w in tasks:
        for k, v in w:
            if k in final and final[k] != v:
                conflicts += 1
            final[k] = v
    return final, conflicts


def sim_lww(tasks, tr):
    final = {}
    for w in tasks:
        for k, v in w:
            final[k] = v
    return dict(caught=0, silent=tr[1], redone=0, wall=STEPS, ok=final == tr[0])


def sim_occ(tasks, tr):
    final, redone = {}, 0
    for w in tasks:                                   # all started from the same snapshot; commit in order
        if any(k in final for k, _ in w):             # something it wrote was committed by someone else since the snapshot
            redone += len(w)
        for k, v in w:
            final[k] = v
    return dict(caught=tr[1], silent=0, redone=redone, wall=STEPS + (STEPS if redone else 0), ok=final == tr[0])


def sim_lock(tasks, tr):
    return dict(caught=0, silent=0, redone=0, wall=STEPS * AGENTS, ok=True)


async def run_graph(tasks, tr, gm, tenant):
    await gm.db.drop_tenant(tenant)
    await gm.grant("lead", tenant, ("read", "write"))
    base = gm.open("lead", tenant)
    for i in range(KEYS + HOT + AGENTS * 20):
        await base.assert_fact(f"k{i}", "val", "v0", exclusive=True)
    forks = [await fork(gm, "lead", tenant, f"agent{a}") for a in range(AGENTS)]
    for a, w in enumerate(tasks):                       # concurrent work, each on its own fork
        fm = await open_fork(gm, "lead", forks[a]["id"])
        for k, v in w:
            await fm.assert_fact(k, "val", v, exclusive=True)
    caught = redone = 0
    for a, w in enumerate(tasks):
        dry = await merge(gm, "lead", forks[a]["id"])
        rep = await merge(gm, "lead", forks[a]["id"], apply=True, on_conflict="skip")
        assert len(dry["conflicts"]) == len(rep["conflicts"])
        caught += len(rep["conflicts"])
        for c in rep["conflicts"]:                      # resolve: redo only the skipped writes, as the newest value
            await base.assert_fact(c["subject"], "val", c["fork_value"], exclusive=True)
            redone += 1
    cur = (await base._q("MATCH (f:Fact {pred:'val', cur:true}) RETURN f.sname, f.otext", scope="read"))
    final = {r[0]: r[1] for r in cur if r[1] != "v0"}
    await gm.db.drop_tenant(tenant)
    return dict(caught=caught, silent=0, redone=redone, wall=STEPS + redone, ok=final == tr[0])


async def main(seeds):
    gm = GraphMem(Db())
    print("| overlap | system | true conflicts | caught | silent overwrites | redone writes | wall (write units) | final == serial truth |\n|---|---|---|---|---|---|---|---|")
    for overlap in (0.0, 0.25, 0.5):
        acc = {}
        for seed in range(seeds):
            tasks = workload(random.Random(seed), overlap)
            tr = truth(tasks)
            res = {"lww": sim_lww(tasks, tr), "occ": sim_occ(tasks, tr), "lock": sim_lock(tasks, tr),
                   "graph": await run_graph(tasks, tr, gm, f"b2-{seed}")}
            for s, r in res.items():
                acc.setdefault(s, []).append({**r, "true": tr[1]})
        for s in ("lww", "occ", "lock", "graph"):
            m = lambda k: statistics.mean(r[k] for r in acc[s])
            print(f"| {int(overlap*100)}% | {s} | {m('true'):.1f} | {m('caught'):.1f} | {m('silent'):.1f} | {m('redone'):.1f} | {m('wall'):.1f} | {sum(r['ok'] for r in acc[s])}/{seeds} |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--seeds", type=int, default=3)
    asyncio.run(main(ap.parse_args().seeds))
