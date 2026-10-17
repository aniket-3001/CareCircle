"""Print how many checks of each kind the repository holds right now, so no document has to carry a number that goes stale.

  python scripts/counts.py        (needs the project's Python environment; the web count needs `npm ci` in web/)
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def pytest_count() -> str:
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"], cwd=ROOT, capture_output=True, text=True).stdout
    m = re.search(r"(\d+) tests? collected", out) or re.search(r"^(\d+) tests", out, re.M)
    return m.group(1) if m else "?"


def scenarios() -> tuple[int, int]:
    api = len(re.findall(r'^@scenario\("', "".join(p.read_text(encoding="utf-8") for p in (ROOT / "scenarios").glob("s_*.py")), re.M))
    ui = len(re.findall(r'^@scenario\("', (ROOT / "scenarios" / "ui_scenarios.py").read_text(encoding="utf-8"), re.M))
    return api, ui


def vitest_count() -> str:
    n = 0
    for p in (ROOT / "web" / "src").rglob("*.test.ts*"):
        n += len(re.findall(r"^\s*(?:it|test)\(", p.read_text(encoding="utf-8"), re.M))
    return str(n)


if __name__ == "__main__":
    api, ui = scenarios()
    print(f"python tests (pytest):      {pytest_count()}")
    print(f"web tests (vitest):         {vitest_count()}")
    print(f"scenarios against the API:  {api}")
    print(f"scenarios in a browser:     {ui}")
