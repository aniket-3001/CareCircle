"""A care circle's graph gets only the indexes the care operations use; the generic memory engine's indexes and unique constraints appear the first time it is used."""
import re
import pathlib

from conftest import tid
from graphmem import db as dbmod

ROOT = pathlib.Path(__file__).resolve().parents[1]


async def indexed(gm, t):
    g = gm.db.client.select_graph(gm.db.graph_name(t))
    return {(r[0], tuple(r[1])) for r in (await g.query("CALL db.indexes() YIELD label, properties RETURN label, properties")).result_set}


async def test_a_care_circle_has_no_engine_indexes_until_the_engine_is_used(gm):
    t = tid(gm, "lz")
    await gm.grant("a", t, ("read", "write"))
    m = gm.open("a", t)
    await m.care_record("asha", "metformin", dose_text="500 mg")
    labels = {l for l, _ in await indexed(gm, t)}
    assert {"Dose", "Person", "Give"} <= labels
    assert labels.isdisjoint({"Session", "Episode", "Entity", "Fact", "Task", "Plan"}), labels
    await m.add_episode("s1", "user", "hello")                                  # the generic memory engine is used: its indexes and constraints arrive now
    after = {l for l, _ in await indexed(gm, t)}
    assert {"Session", "Episode", "Entity", "Fact", "Task", "Plan"} <= after
    g = gm.db.client.select_graph(gm.db.graph_name(t))
    assert any("Session" in str(r) for r in (await g.query("CALL db.constraints()")).result_set)       # the unique constraint is there too, before the engine writes again
    await m.add_episode("s1", "user", "again")                                  # and nothing is created twice


def test_the_care_code_never_names_an_engine_label_so_it_never_triggers_the_engine_setup():
    bad = []
    # the care operations are the code that queries a circle's own graph (accounts and the pharmacist link query the separate control graph, where Agent and Session mean something else)
    for f in (ROOT / "graphmem").glob("care*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = line.split("#")[0]
            if '"' in s or "'" in s:                                        # only inside Cypher strings
                for m in dbmod.ENGINE_LABELS.finditer(s):
                    if re.search(r"\((\w*)" + re.escape(m.group(0)), s) or "MATCH" in s or "MERGE" in s or "CREATE" in s:
                        bad.append(f"{f.name}:{n}: {m.group(0)}")
    assert not bad, bad
