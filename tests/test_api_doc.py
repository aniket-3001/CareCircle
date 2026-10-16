"""docs/API.md is written from the operation table by scripts/gen_api_doc.py; if it is out of date the reference has drifted from the code."""
import pathlib
import re

from graphmem import ops

DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "API.md"


def test_the_api_reference_lists_every_operation_with_its_scope():
    text = DOC.read_text(encoding="utf-8")
    listed = dict(re.findall(r"^\| `([a-z_]+)` \| (\w+) \|", text, re.M))
    table = {name: d["scope"] for name, d in ops.describe().items()}
    assert listed == table, "run: python scripts/gen_api_doc.py"
