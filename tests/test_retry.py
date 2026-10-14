import pytest

from graphmem.db import Overloaded, RetryingGraph


class Flaky:
    def __init__(self, fail_times, exc):
        self.calls, self.fail_times, self.exc = 0, fail_times, exc
        self.name = "g"

    async def query(self, q, params=None, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return "ok"


async def test_retries_queue_full_then_succeeds():
    g = Flaky(3, Exception("Max pending queries exceeded"))
    assert await RetryingGraph(g).query("RETURN 1") == "ok" and g.calls == 4


async def test_gives_up_with_overloaded():
    g = Flaky(99, Exception("Max pending queries exceeded"))
    with pytest.raises(Overloaded):
        await RetryingGraph(g).query("RETURN 1")
    assert g.calls == RetryingGraph.ATTEMPTS


async def test_other_errors_are_not_retried():
    g = Flaky(99, ValueError("syntax error"))
    with pytest.raises(ValueError):
        await RetryingGraph(g).query("BAD")
    assert g.calls == 1
    assert RetryingGraph(g).name == "g"            # attribute passthrough
