import subprocess

import pytest

from conftest import tid
from graphmem.repo_loader import load_repo


def _git(root, *a):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Ann", "-c", "user.email=a@x", *a], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    files = {
        "pkg/__init__.py": "",
        "pkg/core.py": "def base():\n    return 1\n",
        "pkg/mid.py": "from .core import base\n\ndef middle():\n    return base()\n",
        "pkg/top.py": "from pkg.mid import middle\nimport pkg.core\n\ndef top():\n    return middle()\n",
        "pkg/lone.py": "def alone():\n    return 0\n",
    }
    _git(tmp_path, "init", "-q")
    for name, body in files.items():
        (tmp_path / name).write_text(body)
    _git(tmp_path, "add", "-A"); _git(tmp_path, "commit", "-qm", "initial")
    (tmp_path / "pkg/core.py").write_text("def base():\n    return 2\n")
    (tmp_path / "pkg/mid.py").write_text("from .core import base\n\ndef middle():\n    return base() + 1\n")
    _git(tmp_path, "commit", "-qam", "change core and mid together")
    return tmp_path


def test_loader_extracts_imports_calls_and_history(repo):
    d = load_repo(repo)
    deps = {(a, b) for a, b, _ in d["deps"]}
    assert ("pkg/mid.py", "pkg/core.py") in deps and ("pkg/top.py", "pkg/mid.py") in deps and ("pkg/top.py", "pkg/core.py") in deps
    assert ("pkg/mid.py::middle", "pkg/core.py::base") in {(a, b) for a, b, _ in d["calls"]}
    assert len(d["commits"]) == 2 and {"pkg/core.py", "pkg/mid.py"} <= set(d["commits"][0]["files"])


async def test_algorithm_tools_over_loaded_repo(gm, repo):
    t = tid(gm)
    await gm.grant("a", t)
    m = gm.open("a", t)
    stats = await m.code_load(**load_repo(repo))
    assert stats["depends_on_edges"] == 3 and stats["commits"] == 2
    br = await m.blast_radius("pkg/core.py")
    assert {r["file"]: r["hops"] for r in br["rows"]} == {"pkg/mid.py": 1, "pkg/top.py": 1}
    assert "DEPENDS_ON" in br["cypher"]
    assert (await m.dependencies_of("pkg/top.py"))["rows"].__len__() == 2
    assert (await m.criticality())["rows"][0]["file"] == "pkg/core.py"
    assert [d["size"] for d in (await m.failure_domains())["rows"]][0] == 3
    assert (await m.failover_capacity("pkg/top.py", "pkg/core.py"))["rows"] == 2.0     # direct edge + route via mid
    assert (await m.cheapest_route("pkg/top.py", "pkg/core.py"))["rows"][0]["route"] == ["pkg/top.py", "pkg/core.py"]
    assert (await m.co_changed("pkg/core.py"))["rows"][0] == {"file": "pkg/mid.py", "commits": 2}
    assert (await m.who_to_ask("pkg/core.py"))["rows"][0]["person"] == "Ann"
    ci = await m.change_impact(["pkg/core.py"])
    assert {r["file"] for r in ci["dependants"]["rows"]} == {"pkg/mid.py", "pkg/top.py"}
    with pytest.raises(KeyError):
        await m.blast_radius("nope.py")


async def test_algorithms_need_read_scope(gm, repo):
    from graphmem import PermissionDenied
    t = tid(gm)
    await gm.grant("w", t, ("write",))
    await gm.open("w", t).code_load(**load_repo(repo))
    with pytest.raises(PermissionDenied):
        await gm.open("w", t).criticality()
    with pytest.raises(PermissionDenied):
        await gm.open("stranger", t).code_load(files=[])
