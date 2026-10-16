"""Restore drill: take the newest backup from the production bucket, load it into a throwaway FalkorDB, and check the data through the real engine.

A backup nobody has restored is a hope, not a backup. Run this before you rely on one (and after changing how backups are made):

  AWS_PROFILE=vayu PYTHONPATH=. python scripts/restore_drill.py [--bucket carecircle-backups-534212416249]

Needs the AWS CLI with read access to the bucket, and Docker. Nothing is written to the bucket or to production. Prints how long each step took.
"""
import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
import time

from graphmem import Db, GraphMem

NAME, PORT = "cc-restore-drill", 6392


def sh(*a, check=True):
    r = subprocess.run(a, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"{' '.join(a[:3])} failed: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def newest(bucket):
    lines = sh("aws", "s3", "ls", f"s3://{bucket}/falkordb/").splitlines()
    rows = sorted((l.split() for l in lines if l.strip().endswith(".rdb")), key=lambda x: x[-1])
    if not rows:
        raise SystemExit("no backups in the bucket")
    d, t, size, key = rows[-1][0], rows[-1][1], int(rows[-1][2]), rows[-1][3]
    return key, size, f"{d} {t}"


async def verify(port):
    gm = GraphMem(Db(port=port))
    out = {}
    graphs = set(await gm.db.list_tenant_graphs())
    out["graphs"] = sorted(graphs)
    ref = gm.db.client.select_graph("cc_ref")
    out["drugs"] = (await ref.query("MATCH (d:Drug) RETURN count(d)")).result_set[0][0]
    out["interactions"] = (await ref.query("MATCH ()-[i:INTERACTS]->() RETURN count(i)")).result_set[0][0]
    ctl = gm.db.client.select_graph("ctl")
    out["accounts"] = [r[0] for r in (await ctl.query("MATCH (a:Account) RETURN a.email ORDER BY a.email")).result_set]
    out["plaintext_keys"] = (await ctl.query("MATCH (k:ApiKey) WHERE k.hash STARTS WITH 'gm_' RETURN count(k)")).result_set[0][0]
    demo = "demo-shared"
    if demo in graphs:
        asha = gm.open("ravi-demo-reader", demo)
        await gm.grant("ravi-demo-reader", demo, ("read",))
        out["demo_regimen"] = len(await asha.care_regimen("asha"))
        out["demo_events"] = len(await asha.care_timeline("asha", limit=1000))
        out["demo_readings"] = len(await asha.care_measures("asha"))
        await gm.revoke("ravi-demo-reader", demo)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default="carecircle-backups-534212416249")
    a = ap.parse_args()
    steps = {}
    t0 = time.perf_counter()
    key, size, when = newest(a.bucket)
    print(f"newest backup: {key} ({size / 1e6:.1f} MB, written {when} UTC)")
    sh("docker", "rm", "-f", NAME, check=False)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dump = os.path.join(tmp, "dump.rdb")
            sh("aws", "s3", "cp", f"s3://{a.bucket}/falkordb/{key}", dump, "--only-show-errors")
            steps["download"] = time.perf_counter() - t0
            t1 = time.perf_counter()
            sh("docker", "create", "--name", NAME, "-p", f"{PORT}:6379", "falkordb/falkordb:latest")
            sh("docker", "cp", dump, f"{NAME}:/var/lib/falkordb/data/dump.rdb")           # docker cp, not a bind mount (Windows)
            sh("docker", "start", NAME)
            for _ in range(120):
                if sh("docker", "exec", NAME, "redis-cli", "ping", check=False) == "PONG" and "cc_ref" in sh("docker", "exec", NAME, "redis-cli", "GRAPH.LIST", check=False):
                    break
                time.sleep(1)
            steps["load into a fresh database"] = time.perf_counter() - t1
        t2 = time.perf_counter()
        v = asyncio.run(verify(PORT))
        steps["verify through the engine"] = time.perf_counter() - t2
        print(f"restored graphs: {len(v['graphs'])} circle graphs; cc_ref: {v['drugs']} drugs, {v['interactions']} interactions")
        print(f"accounts: {len(v['accounts'])} (demo accounts present: {all(e in v['accounts'] for e in ('ravi@demo.carecircle.app', 'meena@demo.carecircle.app'))})")
        if "demo_regimen" in v:
            print(f"demo circle: {v['demo_regimen']} medicines, {v['demo_events']} timeline events, {v['demo_readings']} readings")
        problems = []
        if v["drugs"] < 1000 or v["interactions"] < 100_000:
            problems.append("reference graph is incomplete")
        if not all(e in v["accounts"] for e in ("ravi@demo.carecircle.app", "meena@demo.carecircle.app")):
            problems.append("demo accounts missing")
        if v.get("demo_regimen", 0) < 5 or v.get("demo_events", 0) < 50:
            problems.append("demo circle is missing or thin")
        if v["plaintext_keys"]:
            problems.append("an API key is stored in plain text")
        total = time.perf_counter() - t0
        print("timings: " + ", ".join(f"{k} {x:.0f}s" if k == "download" else f"{k} {x:.0f}s" for k, x in steps.items()) + f"; total {total:.0f}s")
        print("RESTORE DRILL: " + ("PASS" if not problems else "FAIL: " + "; ".join(problems)))
        return 0 if not problems else 1
    finally:
        sh("docker", "rm", "-f", NAME, check=False)


if __name__ == "__main__":
    sys.exit(main())
