import json

import httpx
import pytest

from graphmem import GraphMem
from graphmem.extract import LLMExtractor, RuleExtractor, Triple, parse_llm_output
from conftest import tid


async def test_rule_extractor_statements():
    ex = RuleExtractor()
    got = await ex.extract("Alice lives in Paris. The deadline for the report is Friday. Bob works at Acme; Carol likes tea!")
    assert Triple("Alice", "lives_in", "Paris", True) in got
    assert Triple("the report", "deadline", "Friday", True) in got
    assert Triple("Bob", "works_at", "Acme", True) in got
    assert Triple("Carol", "likes", "tea", False) in got
    assert await ex.extract("What time is it? Maybe later, who knows.") == []


async def test_ingest_end_to_end_with_supersession_and_provenance(gm):
    t = tid(gm)
    await gm.grant("tt-a", t)
    m = gm.open("tt-a", t)
    r1 = await m.ingest("s", "user", "Dana lives in Oslo.")
    r2 = await m.ingest("s", "user", "Dana moved to Rome.")
    assert r1["facts"][0]["created"] and r2["facts"][0]["superseded"] == [r1["facts"][0]["id"]]
    now = [f for f in await m.recall("dana") if f["predicate"] == "lives_in"]
    assert [f["object"] for f in now] == ["Rome"]
    assert now[0]["provenance"][0]["episode"] == r2["episode"]["id"]


def test_llm_output_validation_is_strict():
    ok = '{"facts":[{"subject":"Ann","predicate":"Works At","object":"Initech","exclusive":true}]}'
    assert parse_llm_output(ok) == [Triple("Ann", "works_at", "Initech", True)]
    assert parse_llm_output("```json\n" + ok + "\n```") == [Triple("Ann", "works_at", "Initech", True)]
    for bad in ("not json", "[]", '{"facts":"x"}', '{"facts":[1,"a",{"subject":1,"predicate":"p","object":"o"}]}',
                '{"facts":[{"subject":"a","predicate":"p","object":"a"}]}', '{"facts":[{"subject":"","predicate":"p","object":"o"}]}'):
        assert parse_llm_output(bad) == []
    many = json.dumps({"facts": [{"subject": f"s{i}", "predicate": "p", "object": f"o{i}"} for i in range(100)]})
    assert len(parse_llm_output(many)) == 20
    long = json.dumps({"facts": [{"subject": "x" * 500, "predicate": "p", "object": "y"}]})
    assert len(parse_llm_output(long)[0].subject) == 120
    inj = json.dumps({"facts": [{"subject": "x'}) DETACH DELETE (n) //", "predicate": "p", "object": "o", "exclusive": "true"}]})
    assert parse_llm_output(inj)[0].exclusive is False          # only a real boolean true counts


async def test_llm_extractor_against_fake_server_and_failure_keeps_episode(gm):
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"], seen["body"] = req.headers.get("authorization"), json.loads(req.content)
        if "boom" in seen["body"]["messages"][1]["content"]:
            return httpx.Response(500, json={"error": "down"})
        content = json.dumps({"facts": [{"subject": "Eve", "predicate": "owns", "object": "the repo"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    llm = LLMExtractor("http://fake/v1", "m", "k", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    g2 = GraphMem(gm.db, extractor=llm)
    t = tid(gm)
    await g2.grant("tt-a", t)
    m = g2.open("tt-a", t)
    r = await m.ingest("s", "user", "Eve is the one who set this up")
    assert r["facts"][0]["object"] == "the repo" and seen["auth"] == "Bearer k"
    assert seen["body"]["messages"][0]["role"] == "system" and seen["body"]["temperature"] == 0
    bad = await m.ingest("s", "user", "boom")
    assert bad["facts"] == [] and "HTTPStatusError" in bad["extraction_error"]
    assert len(await m.history("s")) == 2                       # message stored despite extractor failure
