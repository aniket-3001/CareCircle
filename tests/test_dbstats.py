import pytest

from graphmem.dbstats import redact


@pytest.mark.parametrize("raw,shown", [
    ('CYPHER `v`="my secret" `n`=5 CREATE (:P {v: $v})', 'CREATE (:P {v: $v})'),
    ('CYPHER `r`=["a, b","c \\" d"] `k`={x:"y"} UNWIND $r AS n MERGE (:Drug {name:n})', 'UNWIND $r AS n MERGE (:Drug {name:n})'),
    ('CYPHER `a`=1 `b`=true MATCH (n) RETURN n', 'MATCH (n) RETURN n'),
    ("MATCH (n:Person {name:\"Asha Rao\"}) RETURN n", 'MATCH (n:Person {name:"…"}) RETURN n'),     # a literal typed into the query itself
    ("MATCH (n)\n   RETURN   n", "MATCH (n) RETURN n"),
])
def test_redact_removes_values_and_header(raw, shown):
    assert redact(raw) == shown


def test_redact_cuts_long_text():
    out = redact("MATCH " + "x" * 1000)
    assert len(out) == 240 and out.endswith("…")
