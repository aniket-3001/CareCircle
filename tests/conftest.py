import uuid

import pytest_asyncio

from graphmem import Db, GraphMem


async def _ctl_ids(db):
    g = db.client.select_graph("ctl")
    out = set()
    for label in ("Agent", "Tenant", "Space"):
        try:
            out |= {r[0] for r in (await g.query(f"MATCH (n:{label}) RETURN n.id")).result_set}
        except Exception:
            pass
    return out


@pytest_asyncio.fixture
async def gm():
    """Each test gets a GraphMem; on teardown everything it added to `ctl` (agents, tenants, spaces, orphaned keys)
    and every tenant graph it registered is removed, so repeated runs leave no residue."""
    db = Db()
    mem = GraphMem(db)
    created = []
    mem._created = created
    ctl = await mem._ctl()
    before = await _ctl_ids(db)
    yield mem
    for t in created:
        await db.drop_tenant(t)
    for g in await db.client.list_graphs():          # forks made by the test (graph + control node)
        if g.startswith("fork__tt-") or any(g.startswith(f"fork__{t}__") for t in created):
            try:
                await db.client.select_graph(g).delete()
            except Exception:
                pass
    try:
        await ctl.query("MATCH (f:Fork) WHERE f.tenant STARTS WITH 'tt-' OR f.tenant IN $ts DETACH DELETE f", {"ts": created})
    except Exception:
        pass
    new = sorted(await _ctl_ids(db) - before)
    try:
        if new:
            await ctl.query("MATCH (n) WHERE (n:Agent OR n:Tenant OR n:Space) AND n.id IN $ids DETACH DELETE n", {"ids": new})
        await ctl.query("MATCH (k:ApiKey) WHERE NOT ()-[:HAS_KEY]->(k) DELETE k")
    except Exception:
        pass


def tid(gm, label="a"):
    t = f"tt-{label}-{uuid.uuid4().hex[:6]}"
    gm._created.append(t)
    return t
