"""Every circle graph carries a schema version and is migrated forward when opened; migrations are additive and idempotent."""
from graphmem import schema
from conftest import tid


async def test_new_and_old_graphs_reach_the_current_version(gm):
    t = tid(gm, "sc")
    await gm.create_tenant(t)
    g = await gm.db.tenant_graph(t)
    assert (await g.query("MATCH (s:Schema) RETURN s.v")).result_set == [[schema.CURRENT]]
    await g.query("MATCH (s:Schema) SET s.v = 1")                                     # pretend it was last opened by older code
    await g.query("CREATE (:Dose {id:'keep', drug:'x'})")
    async def mk(label, prop):
        try:
            await g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
        except Exception as e:
            assert "already" in str(e).lower()
    out = await schema.migrate(g, mk)
    assert out["from"] == 1 and out["applied"] == [v for v, *_ in schema.MIGRATIONS if v > 1]
    assert (await g.query("MATCH (d:Dose {id:'keep'}) RETURN count(d)")).result_set == [[1]]       # nothing was removed
    assert (await schema.migrate(g, mk))["applied"] == []                                          # idempotent


def test_migrations_are_ordered_and_additive():
    vs = [v for v, *_ in schema.MIGRATIONS]
    assert vs == sorted(set(vs)) and vs[0] == 1
    for _, _, steps in schema.MIGRATIONS:
        for step in steps:
            assert step[0] == "index" or (step[0] == "cypher" and "DELETE" not in step[1].upper())


async def test_migration_5_gives_every_old_entry_a_product_and_moves_the_schedule_onto_it(gm):
    """A circle written by the code before products were nodes: product is a string on each entry and the times sit on the entries."""
    from graphmem import schema
    from conftest import tid
    t = tid(gm, "mig5")
    await gm.grant("mg", t, ("read", "write", "admin"))
    m = gm.open("mg", t)
    await m.care_record("asha", "metformin", dose_text="500 mg", freq_text="twice daily", at=1_000)                       # makes the graph, with the new code
    g = await gm.db.tenant_graph(t)
    # rewrite the graph into the OLD shape: no Product nodes, no VIA edges, the string and the schedule on the entries
    await g.query("MATCH (p:Product) DETACH DELETE p")
    await g.query("MATCH (x:Dose) SET x.product = '', x.cur = true, x.slots = ['08:00', '20:00'], x.as_needed = false, x.ends_on = '', x.sched_by = 'mg', x.sched_at = 5, x.sched_first = 5")
    await g.query("""CREATE (x:Dose {id:'old-1', drug:'amlodipine', product:'telma-am', pstrength:'40/5 mg', dose_text:'', freq_text:'once daily', valid_from:100, cur:true, action:'set',
                     status:'confirmed', slots:['09:00'], as_needed:false, ends_on:'', sched_first:3, sched_by:'mg', sched_at:7})
                     WITH x MATCH (p:Person {id:'asha'}) CREATE (x)-[:FOR]->(p)""")
    await g.query("""CREATE (x:Dose {id:'old-2', drug:'telmisartan', product:'telma-am', pstrength:'40/5 mg', dose_text:'', freq_text:'once daily', valid_from:100, cur:true, action:'set',
                     status:'confirmed', slots:['09:00'], as_needed:false, ends_on:'', sched_first:2, sched_by:'mg', sched_at:7})
                     WITH x MATCH (p:Person {id:'asha'}) CREATE (x)-[:FOR]->(p)""")
    await g.query("MATCH (s:Schema) SET s.v = 4")

    async def mk(label, prop):
        try:
            await g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
        except Exception as e:
            assert "already" in str(e).lower()
    out = await schema.migrate(g, mk)
    assert out["from"] == 4 and out["applied"] == [5]
    rows = (await g.query("MATCH (x:Dose)-[:VIA]->(pr:Product) RETURN x.id, pr.key, pr.kind, pr.combo, pr.slots, pr.sched_first, pr.strength ORDER BY x.id")).result_set
    by = {r[0]: r for r in rows}
    assert len(rows) == 3 and (await g.query("MATCH (x:Dose) WHERE NOT (x)-[:VIA]->(:Product) RETURN count(x)")).result_set == [[0]]       # every entry has one product
    assert by["old-1"][1] == by["old-2"][1] == "asha|product|telma-am"                                                          # both ingredients share ONE product node
    assert by["old-1"][2:5] == ["product", "telma-am", ["09:00"]] and by["old-1"][5] == 2 and by["old-1"][6] == "40/5 mg"       # times, earliest first-confirmed, strength
    met = [r for r in rows if r[2] == "medicine"][0]
    assert met[1] == "asha|medicine|metformin" and met[3] == "" and met[4] == ["08:00", "20:00"]
    again = await schema.migrate(g, mk)
    assert again["applied"] == [] and (await g.query("MATCH (pr:Product) RETURN count(pr)")).result_set == [[2]]                     # idempotent
