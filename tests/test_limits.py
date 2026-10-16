"""The database's own time and memory caps, and what the app does when a query hits one."""
import pytest

from graphmem import Db, QueryLimit
from graphmem.db import QUERY_LIMITS, RetryingGraph


class Stops:
    def __init__(self, msg):
        self.calls, self.msg, self.name = 0, msg, "g"

    async def query(self, q, params=None, **kw):
        self.calls += 1
        raise Exception(self.msg)


@pytest.mark.parametrize("msg", ["Query timed out", "Query's mem consumption exceeded capacity"])
async def test_a_capped_query_is_a_clean_error_and_is_not_retried(msg):
    g = Stops(msg)
    with pytest.raises(QueryLimit):
        await RetryingGraph(g).query("MATCH (n) RETURN n")
    assert g.calls == 1


async def test_caps_are_set_once_and_left_alone_when_the_server_already_has_one():
    db = Db()
    try:
        before = {k: int((await db.client.execute_command("GRAPH.CONFIG", "GET", k))[1]) for k, _, _ in QUERY_LIMITS}
        await db.graph("mem__tt-limits")
        for key, _, default in QUERY_LIMITS:
            now = int((await db.client.execute_command("GRAPH.CONFIG", "GET", key))[1])
            assert now == (before[key] or default), key                     # set when there was none, never changed when there was
        assert await db.apply_limits() == {}                                # a second call does nothing
    finally:
        await db.client.select_graph("mem__tt-limits").delete()
        await db.close()


async def test_a_query_over_its_time_is_stopped_and_a_write_is_rolled_back(gm):
    g = await gm.db.graph("mem__tt-limit-run")                              # this also puts the server's caps in place
    cmd = gm.db.client.execute_command
    old = (await cmd("GRAPH.CONFIG", "GET", "TIMEOUT_DEFAULT"))[1]
    try:
        await cmd("GRAPH.CONFIG", "SET", "TIMEOUT_DEFAULT", 50)             # a tiny cap for this test only
        with pytest.raises(QueryLimit):
            await g.query("UNWIND range(1, 5000000) AS x CREATE (:Big {i: x})")
    finally:
        await cmd("GRAPH.CONFIG", "SET", "TIMEOUT_DEFAULT", old)
        try:
            assert (await g.query("MATCH (n:Big) RETURN count(n)")).result_set[0][0] == 0      # nothing half-written
            assert (await g.query("RETURN 1")).result_set[0][0] == 1                           # and the graph still answers
        finally:
            await cmd("GRAPH.DELETE", "mem__tt-limit-run")
