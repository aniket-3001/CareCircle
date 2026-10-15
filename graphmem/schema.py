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
