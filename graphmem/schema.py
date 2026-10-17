"""Versioned schema for every circle graph. A circle's graph is created once and then lives for years, while the code that writes to it keeps changing,
so each graph carries its own version (one (:Schema {v}) node) and is brought up to date by an ordered list of migrations when it is opened.

A migration is a version number, a description and a list of steps: ("index", Label, prop) or ("cypher", text). Steps must be safe to run twice, and a
migration only ever adds (an index, a property with a default): nothing here deletes a person's records. To change the shape of the graph, append a new
migration; never edit an old one, because graphs that already ran it will not run it again."""
from __future__ import annotations

MIGRATIONS: list[tuple[int, str, list[tuple]]] = [
    (1, "baseline: Care Circle labels", [("index", "Dose", "id"), ("index", "Give", "key"), ("index", "Person", "id")]),
    (2, "readings over time", [("index", "Measurement", "id"), ("index", "Measurement", "kind")]),
    (3, "appointments, conditions and allergies", [("index", "Appointment", "id"), ("index", "Condition", "id"), ("index", "Allergy", "id")]),
    (4, "follow-up checklist", [("index", "Followup", "id"), ("index", "Followup", "person")]),
    (5, "products: a tablet is a node, its entries point at it, and the schedule lives on it", [
        ("index", "Product", "key"),
        # one (:Product) per person and tablet: a brand as printed (kind 'product') or the medicine itself (kind 'medicine')
        ("cypher", """MATCH (x:Dose)-[:FOR]->(p:Person) WHERE NOT (x)-[:VIA]->(:Product)
                      WITH x, p, CASE WHEN coalesce(x.product, '') <> '' THEN 'product' ELSE 'medicine' END AS kind,
                           CASE WHEN coalesce(x.product, '') <> '' THEN x.product ELSE x.drug END AS nm
                      MERGE (pr:Product {key: p.id + '|' + kind + '|' + nm})
                        ON CREATE SET pr.name = nm, pr.kind = kind, pr.person = p.id, pr.combo = CASE WHEN kind = 'product' THEN nm ELSE '' END
                      MERGE (x)-[:VIA]->(pr)"""),
        # the times, the course end and who confirmed them: from the latest CURRENT entry (an older entry's times were replaced)
        ("cypher", """MATCH (x:Dose {cur: true})-[:VIA]->(pr:Product) WHERE x.slots IS NOT NULL AND pr.slots IS NULL
                      WITH pr, x ORDER BY x.valid_from DESC
                      WITH pr, collect(x)[0] AS l
                      SET pr.slots = l.slots, pr.as_needed = coalesce(l.as_needed, false), pr.ends_on = coalesce(l.ends_on, ''), pr.sched_by = l.sched_by, pr.sched_at = l.sched_at"""),
        # when times were FIRST confirmed (the earliest of its entries), and the printed strength of a combination
        ("cypher", """MATCH (x:Dose)-[:VIA]->(pr:Product) WHERE x.sched_first IS NOT NULL AND pr.sched_first IS NULL
                      WITH pr, min(x.sched_first) AS f SET pr.sched_first = f"""),
        ("cypher", """MATCH (x:Dose)-[:VIA]->(pr:Product) WHERE coalesce(x.pstrength, '') <> '' AND pr.strength IS NULL
                      WITH pr, x ORDER BY x.valid_from DESC
                      WITH pr, collect(x)[0] AS l SET pr.strength = l.pstrength"""),
    ]),
]
CURRENT = MIGRATIONS[-1][0]


async def migrate(g, create_index) -> dict:
    """Bring graph `g` to CURRENT. `create_index(label, prop)` is idempotent. Returns {from, to, applied}."""
    rows = (await g.query("MATCH (s:Schema) RETURN s.v")).result_set
    have = rows[0][0] if rows else 0
    applied = []
    for v, text, steps in MIGRATIONS:
        if v <= have:
            continue
        for step in steps:
            if step[0] == "index":
                await create_index(step[1], step[2])
            elif step[0] == "cypher":
                await g.query(step[1])
            else:
                raise ValueError(f"unknown migration step {step[0]!r}")
        await g.query("MERGE (s:Schema) SET s.v = $v, s.note = $n", {"v": v, "n": text})
        applied.append(v)
    return {"from": have, "to": max(have, CURRENT), "applied": applied}
