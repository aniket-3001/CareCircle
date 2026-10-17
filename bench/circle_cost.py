"""B8: what a new care circle costs the database, with the generic memory engine's indexes created up front (the old behaviour) and created only when used.

  GRAPHMEM_EAGER_ENGINE=1 PYTHONPATH=. python bench/circle_cost.py --n 150      (all 20 indexes when the graph is made)
                          PYTHONPATH=. python bench/circle_cost.py --n 150      (only the care indexes)

Each run makes N circles through the same code path as the app (a grant, then one medicine recorded and confirmed), and reports the database's own memory
(`INFO memory`, used_memory) before and after, the time per circle, and the index count of one of them. Run each mode in its own process: the setting is read at import.
It measures a development database on one machine; the point is the difference between the two modes, not the absolute numbers.
"""
import argparse
import asyncio
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    a = ap.parse_args()
    from graphmem import db as dbmod
    from graphmem.db import Db
    from graphmem.policy import GraphMem
    gm = GraphMem(Db())
    r = gm.db.client.connection
    made = []
    try:
        await (await gm._ctl()).query("RETURN 1")
        before = int((await r.info("memory"))["used_memory"])
        t0 = time.perf_counter()
        for i in range(a.n):
            t = "b8-" + uuid.uuid4().hex[:10]
            made.append(t)
            await gm.grant("b8agent", t, ("read", "write"))
            m = gm.open("b8agent", t)
            await m.care_record("asha", "metformin", dose_text="500 mg", freq_text="twice daily")
        secs = time.perf_counter() - t0
        after = int((await r.info("memory"))["used_memory"])
        g = gm.db.client.select_graph(gm.db.graph_name(made[0]))
        idx = (await g.query("CALL db.indexes() YIELD label, properties RETURN count(*)")).result_set[0][0]
        print(f"mode: {'all 20 indexes up front' if dbmod.EAGER_ENGINE else 'care indexes only'}")
        print(f"circles: {a.n}   indexes on one circle's graph: {idx}")
        print(f"memory per circle: {(after - before) / a.n / 1024:.1f} KiB   time per circle: {secs / a.n * 1000:.0f} ms")
    finally:
        for t in made:
            await gm.db.drop_tenant(t)
        ctl = await gm._ctl()
        await ctl.query("MATCH (n) WHERE (n:Agent AND n.id = 'b8agent') OR (n:Tenant AND n.id STARTS WITH 'b8-') DETACH DELETE n")


asyncio.run(main())
