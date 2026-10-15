"""Vector retrieval (optional): needs `pip install fastembed` (downloads a small CPU model on first use)."""
import pytest

pytest.importorskip("fastembed")

from conftest import tid                      # noqa: E402
from graphmem import Db, GraphMem            # noqa: E402


@pytest.fixture
def emb_gm(monkeypatch):
    monkeypatch.setenv("GRAPHMEM_EMBEDDINGS", "1")
    import graphmem.embed as e
    monkeypatch.setattr(e, "_instance", None)
    db = Db()
    gm = GraphMem(db)
    gm._created = []
    return gm


async def test_paraphrase_found_by_vector_but_not_lexically(emb_gm, monkeypatch):
    gm = emb_gm
    t = tid(gm)
    await gm.grant("a", t)
    m = gm.open("a", t)
    await m.assert_fact("invoice", "due_date", "march 3")
    await m.assert_fact("carol", "works_in", "finance")
    q = "when must the bill be paid"                      # shares no content word with the stored fact
    with_vec = await m.recall(q)
    assert with_vec and with_vec[0]["subject"] == "invoice" and "vector match" in with_vec[0]["path"]
    monkeypatch.setenv("GRAPHMEM_EMBEDDINGS", "0")
    assert await m.recall(q) == []                        # lexical + graph alone cannot answer a paraphrase
    monkeypatch.setenv("GRAPHMEM_EMBEDDINGS", "1")
    r = await m.forget_fact(with_vec[0]["id"], "test")
    assert await m.recall(q) == [] or all(x["subject"] != "[forgotten]" for x in await m.recall(q))
    await gm.db.drop_tenant(t)
