"""B6: retrieval quality on hand-written questions with known answers.

A fixed corpus of 30 facts; 30 questions of three kinds, each with one expected fact:
  exact       shares a content word with the fact                       ("who owns the billing service")
  paraphrase  no shared content word, needs semantics                   ("which person is responsible for invoicing software")
  multihop    answer is one hop beyond the entity the question names    ("where does the owner of billing work")
Systems: lexical (token match on entities), graph (lexical + 2-hop expansion = current default), vector only, hybrid (graph + vector).
Metric: recall@3 per question kind (is the expected fact among the top 3 results?). Small and hand-written: it shows the mechanism,
it is not a leaderboard number. Needs fastembed:  PYTHONPATH=. python bench/retrieval_bench.py
"""
import asyncio
import os
import uuid

from graphmem import Db, GraphMem
import graphmem.embed as embed

FACTS = [("billing service", "owned_by", "dana"), ("dana", "works_in", "austin"), ("auth service", "owned_by", "erin"),
         ("erin", "works_in", "berlin"), ("search service", "owned_by", "frank"), ("frank", "works_in", "tokyo"),
         ("invoice", "due_date", "march 3"), ("release", "freeze_date", "friday"), ("database", "backup_window", "2am utc"),
         ("api", "rate_limit", "600 per minute"), ("checkout page", "uses_library", "react"), ("mobile app", "min_version", "ios 15"),
         ("staging cluster", "hosted_on", "gcp"), ("production cluster", "hosted_on", "aws"), ("incident 42", "root_cause", "expired certificate"),
         ("incident 43", "root_cause", "full disk"), ("pager rotation", "lead", "gina"), ("gina", "works_in", "lisbon"),
         ("quarterly budget", "approved_by", "henry"), ("henry", "works_in", "london"), ("onboarding guide", "maintained_by", "ivy"),
         ("ivy", "works_in", "sydney"), ("security audit", "scheduled_for", "november"), ("data retention", "period", "90 days"),
         ("login endpoint", "protected_by", "two factor"), ("payment provider", "is", "stripe"), ("log pipeline", "built_with", "kafka"),
         ("dashboard", "refresh_interval", "30 seconds"), ("test suite", "runs_on", "github actions"), ("design system", "owned_by", "jo")]
QUESTIONS = [
    ("exact", "who owns the billing service", "billing service owned_by dana"),
    ("exact", "what is the invoice due date", "invoice due_date march 3"),
    ("exact", "which cloud hosts the staging cluster", "staging cluster hosted_on gcp"),
    ("exact", "what was the root cause of incident 42", "incident 42 root_cause expired certificate"),
    ("exact", "what is the api rate limit", "api rate_limit 600 per minute"),
    ("exact", "who maintains the onboarding guide", "onboarding guide maintained_by ivy"),
    ("exact", "when is the security audit scheduled", "security audit scheduled_for november"),
    ("exact", "how long is data retention period", "data retention period 90 days"),
    ("exact", "what library does the checkout page use", "checkout page uses_library react"),
    ("exact", "who leads the pager rotation", "pager rotation lead gina"),
    ("paraphrase", "which person is responsible for invoicing software", "billing service owned_by dana"),
    ("paraphrase", "when must the bill be paid", "invoice due_date march 3"),
    ("paraphrase", "where does our test environment run", "staging cluster hosted_on gcp"),
    ("paraphrase", "why did the outage with the lapsed cert happen", "incident 42 root_cause expired certificate"),
    ("paraphrase", "how many calls per minute are allowed", "api rate_limit 600 per minute"),
    ("paraphrase", "who looks after the new hire documentation", "onboarding guide maintained_by ivy"),
    ("paraphrase", "what month is the penetration test", "security audit scheduled_for november"),
    ("paraphrase", "for how long do we keep user records", "data retention period 90 days"),
    ("paraphrase", "which frontend framework renders the purchase screen", "checkout page uses_library react"),
    ("paraphrase", "who is the on call coordinator", "pager rotation lead gina"),
    ("paraphrase", "which company processes our card payments", "payment provider is stripe"),
    ("paraphrase", "what runs our continuous integration", "test suite runs_on github actions"),
    ("multihop", "where does the owner of the billing service work", "dana works_in austin"),
    ("multihop", "in which city is the auth service owner based", "erin works_in berlin"),
    ("multihop", "where does the search service owner live", "frank works_in tokyo"),
    ("multihop", "where is the pager rotation lead located", "gina works_in lisbon"),
    ("multihop", "where does who approved the quarterly budget work", "henry works_in london"),
    ("multihop", "in which city does the onboarding guide maintainer work", "ivy works_in sydney"),
]


def key(r):
    return f"{r['subject']} {r['predicate']} {r['object']}".lower()


async def main():
    os.environ["GRAPHMEM_EMBEDDINGS"] = "1"
    gm, t = GraphMem(Db()), "b6-" + uuid.uuid4().hex[:6]
    await gm.db.drop_tenant(t)
    await gm.grant("bench", t, ("read", "write"))
    m = gm.open("bench", t)
    for s, p, o in FACTS:
        await m.assert_fact(s, p, o)
    res = {}
    for mode in ("lexical", "graph", "vector", "hybrid"):
        for kind, q, exp in QUESTIONS:
            os.environ["GRAPHMEM_EMBEDDINGS"] = "0" if mode in ("lexical", "graph") else "1"
            out = await m.recall(q, hops=1 if mode == "lexical" else 2, limit=10,
                                 mode={"lexical": "lexical", "graph": "lexical", "vector": "vector", "hybrid": "hybrid"}[mode])
            hit = exp in [key(r) for r in out[:3]]
            res.setdefault((mode, kind), []).append(hit)
    kinds = ["exact", "paraphrase", "multihop"]
    print("| system | " + " | ".join(f"{k} recall@3 (n={sum(1 for x in QUESTIONS if x[0]==k)})" for k in kinds) + " |\n|---|---|---|---|")
    for mode in ("lexical", "graph", "vector", "hybrid"):
        print(f"| {mode} | " + " | ".join(f"{sum(res[(mode,k)])/len(res[(mode,k)]):.2f}" for k in kinds) + " |")
    await gm.db.drop_tenant(t)
    await (await gm._ctl()).query("MATCH (n) WHERE n.id IN ['bench', $t] DETACH DELETE n", {"t": t})


asyncio.run(main())
