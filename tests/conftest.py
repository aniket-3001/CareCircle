import uuid

import pytest
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


@pytest.fixture(autouse=True)
def _no_model_calls(monkeypatch):
    """Tests never reach Bedrock unless they inject a generator themselves."""
    monkeypatch.setenv("CC_LLM", "0")
    monkeypatch.setenv("CC_EXTERNAL", "0")          # no network in tests; test_external.py fakes the services


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
    try:                                    # accounts made by a test (email @tt.test): their circles, sessions, agents and keys
        rows = (await ctl.query("MATCH (a:Account) WHERE a.email ENDS WITH '@tt.test' OPTIONAL MATCH (a)-[:MEMBER]->(t:Tenant) RETURN a.agent, t.id")).result_set
        for _, circle in rows:
            if circle:
                await db.drop_tenant(circle)
        agents = sorted({r[0] for r in rows})
        circles = sorted({r[1] for r in rows if r[1]})
        if agents:
            await ctl.query("MATCH (t:Tenant) WHERE t.id IN $c DETACH DELETE t", {"c": circles})
            await ctl.query("MATCH (a:Account) WHERE a.agent IN $a OPTIONAL MATCH (a)<-[:OF]-(s:Session) DETACH DELETE s, a", {"a": agents})
            await ctl.query("MATCH (g:Agent) WHERE g.id IN $a OPTIONAL MATCH (g)-[:HAS_KEY]->(k) DETACH DELETE k, g", {"a": agents})
        await ctl.query("MATCH (n:Throttle) DETACH DELETE n")
        await ctl.query("MATCH (i:Invite) DETACH DELETE i")
    except Exception:
        pass
    new = sorted(await _ctl_ids(db) - before)
    try:
        if new:
            await ctl.query("MATCH (n) WHERE (n:Agent OR n:Tenant OR n:Space) AND n.id IN $ids DETACH DELETE n", {"ids": new})
        await ctl.query("MATCH (k:ApiKey) WHERE NOT ()-[:HAS_KEY]->(k) DELETE k")
        await ctl.query("MATCH (c:TgChat) WHERE c.circle STARTS WITH 'tt-' DELETE c")
    except Exception:
        pass


def tid(gm, label="a"):
    t = f"tt-{label}-{uuid.uuid4().hex[:6]}"
    gm._created.append(t)
    return t


def day(offset: int = 0) -> str:
    """A date (UTC) relative to the day the test runs, so a dose slot is always inside the time its medicine has been on record. Nothing here ages."""
    import datetime as _dt
    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=offset)).strftime("%Y-%m-%d")
