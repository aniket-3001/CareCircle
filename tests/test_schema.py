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
