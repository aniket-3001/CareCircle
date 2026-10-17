"""B6: the same coordination question put to Care Circle, to Mem0, and to a model that is simply given everything.

  PYTHONPATH=. python bench/memory_compare.py --system ours  [--circles 20] [--seed 7] --out ours.json      (the project's Python environment)
  python bench/memory_compare.py --system mem0|fullcontext   [--circles 20] [--seed 7] --out mem0.json      (Mem0 needs its own environment: pip install mem0ai litellm boto3 faiss-cpu)
  python bench/memory_compare.py --merge ours.json mem0.json fullcontext.json

The question. In a generated circle, three carers change and stop medicines and acknowledge each other's changes. Then, for each carer: "which medicines has
this carer not yet seen the current change of?". The answer is computed by a plain-Python oracle from the generated events, never by any of the systems, and a
system is right for a circle only if its answer is exactly the oracle's for all three carers.

The three systems. ours = Care Circle's `care_divergence` over a FalkorDB graph. mem0 = Mem0 (open-source, its default LLM extraction) with Amazon Nova Pro on Bedrock
and Titan embeddings; the question is answered by Nova Pro from the memories Mem0 retrieves. fullcontext = no memory layer at all: every event goes into one prompt to Nova Pro.

What this shows and does not. The circles are tiny (3 to 6 changes), which is the best case for the systems that read text. It is one question, one seed per run, and
the two baselines are used as their documentation describes, not tuned: a person who tuned Mem0's prompts and settings could do better. Mem0 is a general
personal-memory store and was never meant to answer this question, so the point is what is needed to ask it, not a verdict on Mem0. The second half measures the
other thing the product needs, a claim that exactly one of many racing callers wins: ours has a single atomic claim; the baselines have no such operation, so
the test counts how many of ten simultaneous "I gave it" writes each accepts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
import uuid

CARERS = ["ravi", "meena", "sam"]
DRUGS = ["warfarin", "simvastatin", "metformin", "amlodipine", "omeprazole", "metoprolol", "atorvastatin"]
MODEL = "us.amazon.nova-pro-v1:0"


# ------------------------------------------------------------------------------------------------------------------ the generated circle and its oracle
def generate(rng: random.Random) -> list[dict]:
    """Events in time order: {'i', 'kind': 'set'|'stop'|'ack', 'by', 'drug', 'dose', 'of': index of the change an ack refers to}."""
    events: list[dict] = []
    live: set[str] = set()
    for _ in range(rng.randint(3, 6)):
        who, drug = rng.choice(CARERS), rng.choice(DRUGS)
        if drug in live and rng.random() < 0.3:
            events.append({"i": len(events), "kind": "stop", "by": who, "drug": drug}); live.discard(drug)
        else:
            events.append({"i": len(events), "kind": "set", "by": who, "drug": drug, "dose": f"{5 * (len(events) + 1) + rng.choice([0, 1])} mg"}); live.add(drug)
        change = events[-1]["i"]
        for c in CARERS:                                                     # some of the other carers acknowledge exactly that change
            if c != who and rng.random() < 0.5:
                events.append({"i": len(events), "kind": "ack", "by": c, "of": change})
    return events


def oracle(events: list[dict]) -> dict[str, set[str]]:
    """For each carer: the medicines whose current change was made by someone else and which that carer has not acknowledged."""
    cur: dict[str, dict] = {}
    for e in events:
        if e["kind"] in ("set", "stop"):
            cur[e["drug"]] = e
    out = {c: set() for c in CARERS}
    for drug, ch in cur.items():
        seen = {e["by"] for e in events if e["kind"] == "ack" and e["of"] == ch["i"]}
        for c in CARERS:
            if c != ch["by"] and c not in seen:
                out[c].add(drug)
    return out


def sentence(e: dict, events: list[dict]) -> str:
    name = e["by"].capitalize()
    if e["kind"] == "set":
        return f"{name} changed Asha's {e['drug']} to {e['dose']}."
    if e["kind"] == "stop":
        return f"{name} stopped Asha's {e['drug']}."
    ch = events[e["of"]]
    what = f"change of {ch['drug']} to {ch['dose']}" if ch["kind"] == "set" else f"stopping of {ch['drug']}"
    return f"{name} acknowledged {ch['by'].capitalize()}'s {what}."


# ------------------------------------------------------------------------------------------------------------------ asking a model
def _bedrock():
    import boto3
    return boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))


def ask_llm(client, facts: str, carer: str) -> set[str]:
    """The model may reason first (that helps it); the answer is the JSON list after the last 'ANSWER:'. A reply with no such line is a wrong answer, not a guess."""
    prompt = (f"These are the recorded facts about Asha's medicines, in order:\n{facts}\n\n"
              f"A medicine's CURRENT change is the latest change or stop of it. {carer.capitalize()} has NOT YET SEEN a current change when it was made by someone else and "
              f"{carer.capitalize()} has not acknowledged that same change. Which medicines has {carer.capitalize()} not yet seen the current change of? "
              f"Work it out from the facts above only. End your reply with one line of the form  ANSWER: [\"medicine\", ...]  using [] if there are none.")
    r = client.converse(modelId=MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}], inferenceConfig={"maxTokens": 900, "temperature": 0})
    text = r["output"]["message"]["content"][0]["text"]
    found = re.findall(r"ANSWER:\s*(\[.*?\])", text, re.S)
    try:
        return {str(x).strip().lower() for x in json.loads(found[-1])} if found else {"<no answer line>"}
    except Exception:
        return {"<unreadable answer>"}

# ------------------------------------------------------------------------------------------------------------------ the systems
async def run_ours(circles: int, seed: int) -> dict:
    from graphmem.db import Db
    from graphmem.policy import GraphMem
    rng = random.Random(seed)
    gm = GraphMem(Db())
    ok, made = 0, []
    try:
        for _ in range(circles):
            events = generate(rng)
            t = "b6-" + uuid.uuid4().hex[:8]; made.append(t)
            mem = {}
            for c in CARERS:
                await gm.grant(c, t, ("read", "write"))
                mem[c] = gm.open(c, t)
                await mem[c]._q("MERGE (c:Person {id:$a}) ON CREATE SET c.role='carer'", {"a": c})      # what joining a circle does in the app (carecircle/accounts.py): a carer who has not acted yet still exists
            ids: dict[int, str] = {}
            base = int(time.time() * 1000) - 10 * 3_600_000
            for e in events:
                m = mem[e["by"]]
                if e["kind"] == "ack":
                    await m.care_ack(ids[e["of"]])
                else:
                    r = await m.care_record("asha", e["drug"], action=e["kind"], dose_text=e.get("dose", ""), at=base + e["i"] * 60_000)
                    ids[e["i"]] = r["id"]
            div = (await mem["ravi"].care_divergence("asha"))["carers"]
            truth = oracle(events)
            ok += all({u["drug"] for u in div.get(c, {}).get("unacknowledged", [])} == truth[c] for c in CARERS)
    finally:
        for t in made:
            await gm.db.drop_tenant(t)
        ctl = await gm._ctl()
        await ctl.query("MATCH (n) WHERE (n:Agent OR n:Tenant) AND (n.id IN ['ravi','meena','sam'] OR n.id STARTS WITH 'b6-') DETACH DELETE n")
    return {"system": "ours", "circles": circles, "exact": ok}


def run_fullcontext(circles: int, seed: int) -> dict:
    rng, client, ok = random.Random(seed), _bedrock(), 0
    for _ in range(circles):
        events = generate(rng)
        facts = "\n".join(f"{n + 1}. {sentence(e, events)}" for n, e in enumerate(events))
        truth = oracle(events)
        ok += all(ask_llm(client, facts, c) == truth[c] for c in CARERS)
    return {"system": "fullcontext", "circles": circles, "exact": ok}


def mem0_memory():
    import tempfile
    os.environ["MEM0_TELEMETRY"] = "False"
    from mem0 import Memory
    return Memory.from_config({
        "llm": {"provider": "litellm", "config": {"model": f"bedrock/{MODEL}", "temperature": 0.0, "max_tokens": 800}},
        "embedder": {"provider": "aws_bedrock", "config": {"model": "amazon.titan-embed-text-v2:0"}},
        "vector_store": {"provider": "faiss", "config": {"path": tempfile.mkdtemp(), "embedding_model_dims": 1024}},
    })


def run_mem0(circles: int, seed: int) -> dict:
    rng, client, m, ok, mem_counts = random.Random(seed), _bedrock(), mem0_memory(), 0, []
    for _ in range(circles):
        events = generate(rng)
        uid = "circle-" + uuid.uuid4().hex[:8]
        for e in events:
            m.add([{"role": "user", "content": sentence(e, events)}], user_id=uid)                  # one event at a time, as they would happen
        truth = oracle(events)
        stored = m.get_all(filters={"user_id": uid}).get("results", [])
        mem_counts.append((len(stored), len(events)))
        good = True
        for c in CARERS:
            hits = m.search(f"Which medicine changes has {c.capitalize()} not yet seen?", filters={"user_id": uid}, top_k=10).get("results", [])
            facts = "\n".join(f"{n + 1}. {h['memory']}" for n, h in enumerate(sorted(hits, key=lambda h: h.get("created_at", ""))))
            good &= ask_llm(client, facts, c) == truth[c]
        ok += good
    return {"system": "mem0", "circles": circles, "exact": ok, "memories_kept_vs_events": mem_counts}


def race_mem0(rounds: int = 3, callers: int = 10) -> dict:
    """Ten callers each write 'I gave metformin at 08:00' at the same moment. There is no claim operation: count how many writes each system accepts."""
    from concurrent.futures import ThreadPoolExecutor
    m, accepted = mem0_memory(), []
    for _ in range(rounds):
        uid = "race-" + uuid.uuid4().hex[:8]
        with ThreadPoolExecutor(callers) as pool:
            res = list(pool.map(lambda i: m.add([{"role": "user", "content": f"Caller {i} gave Asha's metformin for the 08:00 slot."}], user_id=uid), range(callers)))
        accepted.append(sum(1 for r in res if r.get("results")))
    return {"rounds": rounds, "callers": callers, "writes_accepted_per_round": accepted, "note": "every write is accepted; nothing says who was first or that a second was refused"}


async def race_ours(rounds: int = 3, callers: int = 10) -> dict:
    from graphmem.db import Db
    from graphmem.policy import GraphMem
    gm = GraphMem(Db())
    t, wins = "b6r-" + uuid.uuid4().hex[:8], []
    try:
        for c in range(callers):
            await gm.grant(f"c{c}", t, ("read", "write"))
        m0 = gm.open("c0", t)
        await m0.care_record("asha", "metformin", dose_text="500 mg", at=int(time.time() * 1000) - 3 * 24 * 3_600_000)
        for r in range(rounds):
            slot = f"{time.strftime('%Y-%m-%d', time.gmtime(time.time() - 86400))} {8 + r:02d}:00"
            res = await asyncio.gather(*[gm.open(f"c{c}", t).care_give("asha", "metformin", slot) for c in range(callers)])
            wins.append(sum(1 for x in res if x["given"]))
    finally:
        await gm.db.drop_tenant(t)
        ctl = await gm._ctl()
        await ctl.query("MATCH (n) WHERE (n:Agent OR n:Tenant) AND (n.id STARTS WITH 'c' AND size(n.id) < 4 OR n.id STARTS WITH 'b6r-') DETACH DELETE n")
    return {"rounds": rounds, "callers": callers, "writes_accepted_per_round": wins, "note": "one winner; the others are told who was first"}


def merge(paths: list[str]) -> None:
    rows = [json.load(open(p, encoding="utf-8")) for p in paths]
    print("| system | circles answered exactly | races: writes accepted out of 10 |\n|---|---|---|")
    for r in rows:
        race = r.get("race", {}).get("writes_accepted_per_round", "n/a")
        print(f"| {r['system']} | {r['exact']}/{r['circles']} | {race} |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", choices=["ours", "mem0", "fullcontext"])
    ap.add_argument("--circles", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out")
    ap.add_argument("--merge", nargs="+")
    a = ap.parse_args()
    if a.merge:
        merge(a.merge)
        return
    if a.system == "ours":
        res = asyncio.run(run_ours(a.circles, a.seed)); res["race"] = asyncio.run(race_ours())
    elif a.system == "mem0":
        res = run_mem0(a.circles, a.seed); res["race"] = race_mem0()
    else:
        res = run_fullcontext(a.circles, a.seed); res["race"] = {"writes_accepted_per_round": "no write operation (the model is only given text)"}
    print(json.dumps(res, indent=1))
    if a.out:
        json.dump(res, open(a.out, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    main()
