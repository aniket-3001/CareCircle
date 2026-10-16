import copy
import importlib.util
import json
import pathlib

import pytest

BENCH = pathlib.Path(__file__).resolve().parents[1] / "bench"
spec = importlib.util.spec_from_file_location("bench_gate", BENCH / "gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def run(**over):
    doc = {"bench": "b", "schema": 1, "meta": {"seed": 7, "params": {"n": 40}, "host": "h1", "falkordb": "8", "git": "a"},
           "metrics": {"X.pairs": {"value": 38, "kind": "exact"}, "X.right": {"value": 40, "kind": "higher"},
                       "X.p50_ms": {"value": 10.0, "kind": "lower"}, "X.note": {"value": 4, "kind": "info"}}}
    for k, v in over.items():
        doc[k] = v
    return doc


def candidate(edit):
    c = copy.deepcopy(run())
    edit(c)
    return c


def test_identical_runs_pass():
    code, lines = gate.compare(run(), run())
    assert code == 0 and lines[-1].startswith("OK") and sum(l.startswith("PASS") for l in lines) == 3


@pytest.mark.parametrize("edit", [
    lambda c: c["metrics"]["X.pairs"].update(value=39),                 # an exact count moved, even upwards
    lambda c: c["metrics"]["X.pairs"].update(value=37),
    lambda c: c["metrics"]["X.right"].update(value=39),                 # one thing fewer done right
    lambda c: c["metrics"]["X.p50_ms"].update(value=20.0),              # twice as slow
])
def test_a_regression_fails(edit):
    code, lines = gate.compare(run(), candidate(edit))
    assert code == 1 and sum(l.startswith("FAIL") for l in lines) == 1 and lines[-1].startswith("REGRESSION")


def test_getting_better_is_not_a_failure():
    code, _ = gate.compare(run(), candidate(lambda c: (c["metrics"]["X.right"].update(value=41), c["metrics"]["X.p50_ms"].update(value=5.0))))
    assert code == 0


def test_latency_has_a_tolerance_and_a_noise_floor():
    assert gate.compare(run(), candidate(lambda c: c["metrics"]["X.p50_ms"].update(value=14.4)))[0] == 0     # 10 * 1.25 + 2 = 14.5
    assert gate.compare(run(), candidate(lambda c: c["metrics"]["X.p50_ms"].update(value=14.6)))[0] == 1
    tiny = run(); tiny["metrics"]["X.p50_ms"]["value"] = 1.0
    worse = copy.deepcopy(tiny); worse["metrics"]["X.p50_ms"]["value"] = 3.0                                  # three times slower, but only 2 ms
    assert gate.compare(tiny, worse)[0] == 0
    assert gate.compare(run(), candidate(lambda c: c["metrics"]["X.p50_ms"].update(value=14.6)), tolerance=0.5)[0] == 0


def test_latency_is_not_judged_across_machines_but_counts_still_are():
    def other(c):
        c["meta"]["host"] = "h2"
        c["metrics"]["X.p50_ms"]["value"] = 500.0
    code, lines = gate.compare(run(), candidate(other))
    assert code == 0 and any(l.startswith("SKIP") and "different machine" in l for l in lines)
    code, _ = gate.compare(run(), candidate(lambda c: (other(c), c["metrics"]["X.pairs"].update(value=1))))
    assert code == 1


@pytest.mark.parametrize("edit,why", [
    (lambda c: c["meta"].update(seed=8), "seed"),
    (lambda c: c["meta"].update(params={"n": 41}), "params"),
    (lambda c: c.update(bench="other"), "different benchmarks"),
    (lambda c: c["metrics"].pop("X.pairs"), "missing from the candidate"),
    (lambda c: c["metrics"].update({"X.new": {"value": 1, "kind": "exact"}}), "missing from the baseline"),
    (lambda c: c["metrics"]["X.pairs"].update(kind="info"), "judged differently"),
    (lambda c: c.update(schema=2), "schema"),
])
def test_unlike_runs_are_refused_not_judged(edit, why):
    code, lines = gate.compare(run(), candidate(edit))
    assert code == 2 and lines[0].startswith("REFUSED") and why in lines[0] and not any(l.startswith(("PASS", "FAIL")) for l in lines)


def test_a_file_that_is_not_a_result_is_refused():
    assert gate.compare(run(), {"hello": 1})[0] == 2
    assert gate.compare({"bench": "b"}, run())[0] == 2


def test_skip_lists_what_was_not_judged():
    code, lines = gate.compare(run(), candidate(lambda c: c["metrics"]["X.pairs"].update(value=1)), skip=("X.pairs", ""))
    assert code == 0 and any(l.startswith("SKIP") and "X.pairs" in l for l in lines)


def test_command_line(tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(run()))
    b.write_text(json.dumps(run()))
    assert gate.main([str(a), str(b)]) == 0
    b.write_text("{not json")
    assert gate.main([str(a), str(b)]) == 2
    assert gate.main([str(a), str(tmp_path / "missing.json")]) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_the_committed_baseline_is_a_valid_result_and_agrees_with_itself():
    path = BENCH / "baselines" / "care_bench.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert gate.compare(doc, doc)[0] == 0
    assert doc["bench"] == "care_bench" and doc["meta"]["seed"] == 7
    assert {m["kind"] for m in doc["metrics"].values()} <= {"exact", "higher", "lower", "info"}
