"""Care Circle benchmarks. Deterministic, seeded, no LLM.

 B1 enzyme-path rule vs DDInter: how often do graph-derived enzyme interactions appear in DDInter, and how much of DDInter's
    moderate/major pairs between the same drug sets does the rule recover? (A cross-check of two independent public sources.)
 B2 carer-staleness query vs an independent Python oracle on generated circles; baseline = "only the most recent change per carer".
 B3 double-dose guard: N rounds of concurrent claims on one slot; exactly one winner each time.
 B5 latency of the interaction check for a 10-medicine regimen.

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


def _sql_staleness(entries, authored, acks, carers):
    """The same question answered with SQLite: an entries table and an acknowledgements table, the current entry per medicine by a window function.
    It is here so the benchmark can say plainly that a table does this job too."""
    import sqlite3
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE entries(id TEXT, drug TEXT, at INTEGER, ord INTEGER, author TEXT)")
    db.execute("CREATE TABLE acks(carer TEXT, id TEXT)")
    db.executemany("INSERT INTO entries VALUES(?,?,?,?,?)", [(did, d, at, o, authored[did]) for d, at, o, did in entries])
    db.executemany("INSERT INTO acks VALUES(?,?)", [(a, i) for a, s in acks.items() for i in s])
    out = {}
    for a in carers:
        rows = db.execute("""SELECT id FROM (SELECT id, author, ROW_NUMBER() OVER (PARTITION BY drug ORDER BY at DESC, ord DESC) AS rn FROM entries)
                              WHERE rn = 1 AND author <> ? AND id NOT IN (SELECT id FROM acks WHERE carer = ?)""", (a, a)).fetchall()
        out[a] = {r[0] for r in rows}
    return out


async def b2(circles, seed):
    rng = random.Random(seed)
    gm = GraphMem(Db())
    drugs = ["warfarin", "simvastatin", "clarithromycin", "metformin", "amlodipine", "fluconazole", "omeprazole", "metoprolol"]
    ok_set = ok_rank = base_ok = sql_ok = 0
    made = []
    try:
        for c in range(circles):
            t = "b2-" + uuid.uuid4().hex[:8]; made.append(t)
            carers = ["c1", "c2", "c3"]
            for a in carers:
                await gm.grant(a, t, ("read", "write"))
            m = {a: gm.open(a, t) for a in carers}
            ids, authored, acks, entries = [], {}, {a: set() for a in carers}, []   # entries: (medicine, date, order, id), the oracle's own log

            def note(r, who, drug, at):
                if r.get("unchanged"):                                  # re-typing what is already current records nothing new
                    return
                ids.append(r["id"]); authored[r["id"]] = who; entries.append((drug, at, len(entries), r["id"]))

            for a in carers:                                           # make every carer exist as a Person
                at0 = int(time.time() * 1000)
                r0 = await m[a].care_record("p", "vitamin d", at=at0)
                note(r0, a, "vitamin d", at0)
                await m[a].care_ack(r0["id"]); acks[a].add(r0["id"])
            live = {"vitamin d"}                                          # a medicine can only be stopped once it has been recorded
            for i in range(rng.randint(3, 8)):
                who = rng.choice(carers)
                drug = rng.choice(drugs)
                action = rng.choice(["set", "set", "stop"]) if drug in live else "set"
                live.add(drug) if action == "set" else live.discard(drug)
                at = int(time.time() * 1000) - rng.randint(1, 60) * H
                note(await m[who].care_record("p", drug, action=action, at=at), who, drug, at)
            for did in ids:
                for a in carers:
                    if a != authored[did] and rng.random() < 0.5:
                        await m[a].care_ack(did); acks[a].add(did)
            latest = {}                                                 # the oracle: a carer is behind on a medicine when its entry that stands now
            for drug, _, _, did in sorted(entries, key=lambda e: (e[1], e[2])):   # (by date) is someone else's and they have not seen it
                latest[drug] = did
            truth = {a: {d for d in latest.values() if authored[d] != a and d not in acks[a]} for a in carers}
            got = (await m["c1"].care_divergence("p"))["carers"]
            ok_set += all({u["dose"] for u in got[a]["unacknowledged"]} == truth[a] for a in carers)
            tr = sorted(carers, key=lambda a: (-len(truth[a]), a))[0] if any(truth.values()) else None
            ok_rank += (tr is None) or (len(truth[(await m["c1"].care_divergence("p"))["most_out_of_date"] or tr]) >= max(len(v) for v in truth.values()) - 1)
            sql_ok += _sql_staleness(entries, authored, acks, carers) == truth    # a fair baseline: two plain tables and one query
            last = ids[-1]                                              # baseline: only the most recent change, whatever medicine it was about
            base_ok += all(({last} - acks[a] if authored[last] != a else set()) == truth[a] for a in carers)
    finally:
        for t in made:
            await gm.db.drop_tenant(t)
        ctl = await gm._ctl()
        await ctl.query("MATCH (n) WHERE (n:Agent OR n:Tenant) AND (n.id IN ['c1','c2','c3'] OR n.id STARTS WITH 'b2-') DETACH DELETE n")
        await ctl.query("MATCH (k:ApiKey) WHERE NOT ()-[:HAS_KEY]->(k) DELETE k")
    return dict(circles=circles, exact_match_with_oracle=f"{ok_set}/{circles}", most_stale_carer_plausible=f"{ok_rank}/{circles}",
                baseline_last_change_only_exact=f"{base_ok}/{circles}", baseline_two_sql_tables_exact=f"{sql_ok}/{circles}")


async def b3(rounds, width=10):
    gm = GraphMem(Db()); t = "b3-" + uuid.uuid4().hex[:8]; wins = []
    for a in ("c1", "c2"):
        await gm.grant(a, t, ("read", "write"))
    m = [gm.open("c1", t), gm.open("c2", t)]
    await m[0].care_record("p", "metformin", dose_text="500 mg", freq_text="twice daily", at=int(time.time() * 1000) - (rounds + 3) * 24 * H)     # a slot needs a medicine on record
    # one slot per day: with no times set, two gives within an hour of each other are the same dose (the 21:00 / 21:15 rule), so slots a minute apart would not be separate doses
    days = [time.strftime("%Y-%m-%d", time.gmtime(time.time() - (r + 1) * 86400)) for r in range(rounds)]
    for r in range(rounds):
        res = await asyncio.gather(*[m[i % 2].care_give("p", "metformin", f"{days[r]} 08:00") for i in range(width)])
        wins.append(sum(x["given"] for x in res))
    await gm.db.drop_tenant(t)
    ctl = await gm._ctl(); await ctl.query("MATCH (n) WHERE n.id IN ['c1','c2',$t] DETACH DELETE n", {"t": t})
    return dict(rounds=rounds, concurrent_claims_per_round=width, rounds_with_exactly_one_winner=sum(1 for w in wins if w == 1))


def b5(runs=200):
    """B5 latency of the interaction check on a 10-medicine regimen (direct pairs + enzyme paths + combined weight), warm, one process."""
    from carecircle.checks import Checker
    c = Checker("localhost", 6379)
    drugs = ["metformin", "amlodipine", "atorvastatin", "lisinopril", "levothyroxine", "omeprazole", "warfarin", "vitamin d", "clarithromycin", "ibuprofen"]
    c.check(drugs)
    ts = []
    for _ in range(runs):
        t = time.perf_counter(); c.check(drugs); ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    return {"regimen_size": len(drugs), "runs": runs, "p50_ms": round(ts[len(ts) // 2], 1), "p95_ms": round(ts[int(len(ts) * 0.95)], 1), "max_ms": round(ts[-1], 1)}


def metrics(r):
    """The numbers bench/gate.py judges. Counts that come from the data or the design must be identical between runs; counts of things
    done right must not fall; latency may not rise much (and is judged only on the same machine)."""
    fda, cur = r["B1_enzyme_vs_ddinter"]["FDA index substrates"], r["B1_enzyme_vs_ddinter"]["curated substrates (unverified)"]
    rec = r["B1_enzyme_vs_ddinter"]["recall_of_ddinter_moderate_major_between_same_drug_sets"]
    right = lambda text: int(text.split("/")[0])  # noqa: E731  "40/40" -> 40
    m = {}
    for tag, d in (("fda", fda), ("curated", cur)):
        for k, v in d.items():
            m[f"B1.{tag}.{k}"] = (v, "exact")
    m["B1.recall.ddinter_pairs"], m["B1.recall.recovered"] = (rec["ddinter_pairs"], "exact"), (rec["recovered"], "exact")
    b2_, b3_, b5_ = r["B2_staleness"], r["B3_double_dose"], r["B5_check_latency"]
    m["B2.circles"] = (b2_["circles"], "exact")
    m["B2.exact_match_with_oracle"] = (right(b2_["exact_match_with_oracle"]), "higher")
    m["B2.most_stale_carer_plausible"] = (right(b2_["most_stale_carer_plausible"]), "higher")
    m["B2.baseline_last_change_only_exact"] = (right(b2_["baseline_last_change_only_exact"]), "info")
    m["B3.rounds"] = (b3_["rounds"], "exact")
    m["B3.rounds_with_exactly_one_winner"] = (b3_["rounds_with_exactly_one_winner"], "higher")
    m["B5.p50_ms"], m["B5.p95_ms"] = (b5_["p50_ms"], "lower"), (b5_["p95_ms"], "lower")
    return {k: {"value": v, "kind": kind} for k, (v, kind) in m.items()}


def meta(circles, rounds, seed):
    import hashlib
    import platform
    import subprocess
    from falkordb import FalkorDB
    try:
        git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        git = ""
    host = hashlib.sha1(f"{platform.node()}|{platform.machine()}|{__import__('os').cpu_count()}".encode()).hexdigest()[:10]     # a fingerprint, not the machine's name
    version = FalkorDB().connection.info("server").get("redis_version", "")
    return {"seed": seed, "params": {"circles": circles, "rounds": rounds, "regimen_runs": 200, "claims_per_round": 10}, "host": host, "falkordb": version, "git": git}


async def main(circles, rounds, seed=7, out=None):
    import json
    r = {"B1_enzyme_vs_ddinter": b1(), "B2_staleness": await b2(circles, seed), "B3_double_dose": await b3(rounds), "B5_check_latency": b5()}
    print(json.dumps(r, indent=1))
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"bench": "care_bench", "schema": 1, "meta": meta(circles, rounds, seed), "metrics": metrics(r)}, f, indent=1, sort_keys=True)
            f.write(chr(10))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--circles", type=int, default=40); ap.add_argument("--rounds", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7, help="seed of the generated circles (B2)")
    ap.add_argument("--out", help="also write a result file for bench/gate.py")
    a = ap.parse_args(); asyncio.run(main(a.circles, a.rounds, a.seed, a.out))
