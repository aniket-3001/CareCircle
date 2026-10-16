"""Does memory survive the database restarting? Starts a throwaway FalkorDB with the production persistence settings (append-only file, fsync every second,
a named volume), writes memory through the engine, restarts the container, and reads it back with a brand-new client. Needs Docker. Removes what it made.

  PYTHONPATH=. python scripts/check_persistence.py
"""
import asyncio
import subprocess
import sys
import time

from graphmem import Db, GraphMem

NAME, VOL, PORT = "cc-persist-check", "cc-persist-check-data", 6391


def sh(*a, check=True):
    return subprocess.run(a, capture_output=True, text=True, check=check).stdout.strip()


def up():
    sh("docker", "run", "-d", "--name", NAME, "-p", f"{PORT}:6379", "-v", f"{VOL}:/var/lib/falkordb/data",
       "-e", "REDIS_ARGS=--appendonly yes --appendfsync everysec", "falkordb/falkordb:latest")


def wait():
    for _ in range(60):
        if sh("docker", "exec", NAME, "redis-cli", "ping", check=False) == "PONG":
            return
        time.sleep(1)
    raise SystemExit("database did not come back")


async def write():
    gm = GraphMem(Db(port=PORT))
    t = "tt-persist"
    await gm.grant("al", t, ("read", "write"))
    m = gm.open("al", t)
    for i in range(30):
        await m.add_episode("chat", "user" if i % 2 == 0 else "agent", f"turn {i}")
    await m.assert_fact("Alice", "lives_in", "Paris", exclusive=True, at=1000)
    await m.assert_fact("Alice", "lives_in", "Berlin", exclusive=True, at=2000)
    await m.add_skill("restart", "Restart it", ["drain", "restart"], ["ops"])
    await m.record_run("restart", True)
    task = await m.create_task("job")
    await m.claim_task(task)
    await m.care_record("asha", "warfarin", dose_text="4 mg", freq_text="daily")
    return task


async def read(task):
    gm = GraphMem(Db(port=PORT))                                                    # a new client: nothing is cached from before
    m = gm.open("al", "tt-persist")
    h = await m.history("chat", limit=100)
    assert [e["seq"] for e in h] == list(range(1, 31)), "history changed"
    assert (await m.add_episode("chat", "user", "after restart"))["seq"] == 31, "numbering restarted"
    assert [f["object"] for f in await m.recall("alice")] == ["Berlin"], "fact lost"
    assert [x["object"] if "object" in x else x["value"] for x in await m.fact_history("Alice", "lives_in")] == ["Paris", "Berlin"]
    assert (await m.best_skills(["ops"]))[0]["runs"] == 1, "skill outcome lost"
    assert (await m.get_task(task))["owner"] == "al", "task owner lost"
    assert [r["drug"] for r in await m.care_regimen("asha")] == ["warfarin"], "care record lost"
    return True


def main():
    sh("docker", "rm", "-f", NAME, check=False)
    sh("docker", "volume", "rm", "-f", VOL, check=False)
    ok = False
    try:
        up(); wait()
        task = asyncio.run(write())
        time.sleep(2)                                                               # fsync is every second
        sh("docker", "restart", NAME)                                               # an orderly restart
        wait()
        ok = asyncio.run(read(task))
        print("restart (docker restart): history, facts, skills, tasks and the care record all came back: PASS")
        sh("docker", "kill", NAME)                                                  # then a hard kill with no chance to flush
        sh("docker", "start", NAME)
        wait()
        n = len(asyncio.run(GraphMem(Db(port=PORT)).open("al", "tt-persist").history("chat", limit=100)))
        assert n >= 30, f"only {n} of 31 events after a hard kill"
        print(f"hard kill (SIGKILL), then start: {n} of 31 events present (at most the last second may be lost by design: fsync everysec): PASS")
    finally:
        sh("docker", "rm", "-f", NAME, check=False)
        sh("docker", "volume", "rm", "-f", VOL, check=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
