"""Run the scenarios against a running server.   SCENARIO_URL=http://localhost:8099 python scenarios/run.py [prefix]"""
import sys

sys.path.insert(0, __file__.rsplit("run.py", 1)[0].rstrip("/\\") or ".")
import harness  # noqa: E402
import s_accounts  # noqa: E402,F401

for name in ("s_medicines", "s_watch", "s_extras", "s_helper"):
    try:
        __import__(name)
    except ModuleNotFoundError as e:
        if e.name != name:
            raise

sys.exit(1 if harness.run_all(sys.argv[1] if len(sys.argv) > 1 else None) else 0)
