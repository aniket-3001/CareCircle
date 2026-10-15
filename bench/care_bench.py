"""Care Circle benchmarks. Deterministic, seeded, no LLM.

 B1 enzyme-path rule vs DDInter: how often do graph-derived enzyme interactions appear in DDInter, and how much of DDInter's
    moderate/major pairs between the same drug sets does the rule recover? (A cross-check of two independent public sources.)
 B2 carer-staleness query vs an independent Python oracle on generated circles; baseline = "only the most recent change per carer".
 B3 double-dose guard: N rounds of concurrent claims on one slot; exactly one winner each time.

  PYTHONPATH=. python bench/care_bench.py [--circles 40] [--rounds 100]
"""
import argparse, asyncio, random, time, uuid

from falkordb import FalkorDB

from graphmem import Db, GraphMem
from carecircle.reference import REF_GRAPH

H = 3_600_000


def b1():
    g = FalkorDB().select_graph(REF_GRAPH)
    rows = g.ro_query("MATCH (x:Drug)-[m:INHIBITS|INDUCES]->(e:Enzyme)<-[s:SUBSTRATE_OF]-(y:Drug) WHERE x <> y "
                      "RETURN DISTINCT x.name, y.name, s.source").result_set
    pairs_all = sorted({(x, y) for x, y, _ in rows})
    lvl = {}
    for x, y in pairs_all:                               # per-pair indexed lookups (UNWIND forms did not use the index and timed out)
        r = g.ro_query("MATCH (a:Drug {name:$a})-[i:INTERACTS]->(b:Drug {name:$b}) RETURN i.level", {"a": min(x, y), "b": max(x, y)}).result_set
        if r:
            lvl[frozenset((x, y))] = r[0][0]
    out = {}
    for label, pick in (("FDA index substrates", lambda s: s.startswith("FDA")), ("curated substrates (unverified)", lambda s: s.startswith("curated"))):
        pairs = {frozenset((x, y)) for x, y, s in rows if pick(s)}
        listed = [lvl[p] for p in pairs if p in lvl]
        out[label] = dict(path_pairs=len(pairs), listed_in_ddinter=len(listed),
                          moderate_or_major=sum(1 for l in listed if l in ("moderate", "major")))
    perp = sorted({x for x, _, _ in rows}); subs = sorted({y for _, y, _ in rows})
    pool = {frozenset((a_, b_)) for a_, b_ in g.ro_query(
        "MATCH (a:Drug)-[i:INTERACTS]-(b:Drug) WHERE a.name IN $p AND b.name IN $s AND i.level IN ['moderate','major'] "
        "RETURN a.name, b.name", {"p": perp, "s": subs}).result_set}
    covered = {frozenset((x, y)) for x, y, _ in rows}
    out["recall_of_ddinter_moderate_major_between_same_drug_sets"] = dict(ddinter_pairs=len(pool), recovered=len(pool & covered))
    return out


async def b2(circles, seed):
    rng = random.Random(seed)
    gm = GraphMem(Db())
    drugs = ["warfarin", "simvastatin", "clarithromycin", "metformin", "amlodipine", "fluconazole", "omeprazole", "metoprolol"]
    ok_set = ok_rank = base_ok = 0
    made = []
    try:
        for c in range(circles):
            t = "b2-" + uuid.uuid4().hex[:8]; made.append(t)
            carers = ["c1", "c2", "c3"]
            for a in carers:
                await gm.grant(a, t, ("read", "write"))
            m = {a: gm.open(a, t) for a in carers}
            ids, authored, acks = [], {}, {a: set() for a in carers}
            for a in carers:                                           # make every carer exist as a Person
                r0 = await m[a].care_record("p", "vitamin d")
                await m[a].care_ack(r0["id"]); ids.append(r0["id"]); authored[r0["id"]] = a; acks[a].add(r0["id"])
            for i in range(rng.randint(3, 8)):
                who = rng.choice(carers)
                r = await m[who].care_record("p", rng.choice(drugs), action=rng.choice(["set", "set", "stop"]),
                                             at=int(time.time() * 1000) - rng.randint(1, 60) * H)
                ids.append(r["id"]); authored[r["id"]] = who
            for did in ids:
                for a in carers:
                    if a != authored[did] and rng.random() < 0.5:
                        await m[a].care_ack(did); acks[a].add(did)
            truth = {a: {d for d in ids if authored[d] != a and d not in acks[a]} for a in carers}
            got = (await m["c1"].care_divergence("p"))["carers"]
            ok_set += all({u["dose"] for u in got[a]["unacknowledged"]} == truth[a] for a in carers)
            tr = sorted(carers, key=lambda a: (-len(truth[a]), a))[0] if any(truth.values()) else None
            ok_rank += (tr is None) or (len(truth[(await m["c1"].care_divergence("p"))["most_out_of_date"] or tr]) >= max(len(v) for v in truth.values()) - 1)
            last = ids[-1]
            base_ok += all(({last} - acks[a] if authored[last] != a else set()) == truth[a] for a in carers)
    finally:
        for t in made:
            await gm.db.drop_tenant(t)
        ctl = await gm._ctl()
        await ctl.query("MATCH (n) WHERE (n:Agent OR n:Tenant) AND (n.id IN ['c1','c2','c3'] OR n.id STARTS WITH 'b2-') DETACH DELETE n")
        await ctl.query("MATCH (k:ApiKey) WHERE NOT ()-[:HAS_KEY]->(k) DELETE k")
    return dict(circles=circles, exact_match_with_oracle=f"{ok_set}/{circles}", most_stale_carer_plausible=f"{ok_rank}/{circles}",
                baseline_last_change_only_exact=f"{base_ok}/{circles}")


async def b3(rounds, width=10):
    gm = GraphMem(Db()); t = "b3-" + uuid.uuid4().hex[:8]; wins = []
    for a in ("c1", "c2"):
        await gm.grant(a, t, ("read", "write"))
    m = [gm.open("c1", t), gm.open("c2", t)]
    for r in range(rounds):
        res = await asyncio.gather(*[m[i % 2].care_give("p", "metformin", f"slot-{r}") for i in range(width)])
        wins.append(sum(x["given"] for x in res))
    await gm.db.drop_tenant(t)
    ctl = await gm._ctl(); await ctl.query("MATCH (n) WHERE n.id IN ['c1','c2',$t] DETACH DELETE n", {"t": t})
    return dict(rounds=rounds, concurrent_claims_per_round=width, rounds_with_exactly_one_winner=sum(1 for w in wins if w == 1))


async def main(circles, rounds):
    import json
    print(json.dumps({"B1_enzyme_vs_ddinter": b1(), "B2_staleness": await b2(circles, 7), "B3_double_dose": await b3(rounds)}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--circles", type=int, default=40); ap.add_argument("--rounds", type=int, default=100)
    a = ap.parse_args(); asyncio.run(main(a.circles, a.rounds))
