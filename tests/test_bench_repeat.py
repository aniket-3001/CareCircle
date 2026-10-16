"""bench/repeat.py: reading a load-test run, and the rule that exact results must not differ between runs."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bench"))
import repeat  # noqa: E402

RUN = """A write storm (30 agents -> 1 session): 900 requests in 2.4s = 372 req/s
  add_episode    n=600    p50=  72.7 ms  p95= 124.2 ms  p99= 242.2 ms  max= 256.4 ms
  audit: 600/600 events stored: PASS
E batch writes (30 agents, 800 events each way)
  one request per event :     311 events/s (800 requests, 2.6s)
  batches of 20         :    5549 events/s (40 requests, 0.1s)  17.8x faster
request errors: 0   result: ALL PASS
"""


def test_parse_stress_reads_rates_latencies_and_verdict():
    r = repeat.parse_stress(RUN)
    assert r["passed"] is True
    assert r["metrics"]["A write storm (30 agents -> 1 session) / req/s"] == 372
    assert r["metrics"]["A write storm (30 agents -> 1 session) / add_episode / p95_ms"] == 124.2
    assert r["metrics"]["E batch writes / batches of 20 / events/s"] == 5549


def test_failed_run_is_not_passed():
    assert repeat.parse_stress(RUN.replace("ALL PASS", "FAILED A,C"))["passed"] is False
    assert repeat.parse_stress("crashed")["passed"] is None


def test_summary_reports_median_min_max_and_flags_any_failed_run():
    runs = [repeat.parse_stress(RUN), repeat.parse_stress(RUN.replace("372 req/s", "400 req/s")), repeat.parse_stress(RUN.replace("372 req/s", "100 req/s"))]
    rows, ok = repeat.summarise_stress(runs)
    row = next(r for r in rows if r[0].endswith("/ req/s") and r[0].startswith("A "))
    assert row[1:] == ["372", "100", "400", "3"] and ok
    runs[1] = repeat.parse_stress(RUN.replace("ALL PASS", "FAILED B"))
    assert repeat.summarise_stress(runs)[1] is False


def test_care_exact_results_that_differ_fail_the_summary():
    a = {"B2.circles": (40, "exact"), "B5.p50_ms": (10.0, "lower")}
    b = {"B2.circles": (41, "exact"), "B5.p50_ms": (12.0, "lower")}
    rows, ok = repeat.summarise_care([a, b])
    assert not ok and any("DIFFERS" in r[1] for r in rows)
    rows, ok = repeat.summarise_care([a, dict(a, **{"B5.p50_ms": (14.0, "lower")})])
    assert ok and next(r for r in rows if r[0] == "B5.p50_ms")[1:4] == ["12", "10", "14"]
