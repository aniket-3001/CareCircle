"""Turn a local Python git checkout into the payload for `TenantMemory.code_load`.

  files    every tracked .py file (id = repo-relative path with '/')       + one node per top-level function/method
  deps     file -> file when one imports the other (module resolution inside the repo only; cap = import statements)
  calls    function -> function, best effort: a call to a bare name defined in the same file or in a file it imports
  commits  from `git log --name-only` (merge commits skipped), restricted to files still in the tree

Static analysis only; dynamic imports, attribute calls and re-exports are not resolved. The loader never executes repo code.
"""
from __future__ import annotations

import ast
import subprocess
from collections import defaultdict
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def _module_of(path: str) -> str:
    p = path[:-3].replace("/", ".")
    return p[:-9] if p.endswith(".__init__") else p


def load_repo(root: str | Path, *, max_commits: int = 2000, max_files: int = 5000, since: str | None = None) -> dict:
    root = Path(root)
    tracked = [f for f in _git(root, "ls-files", "*.py").splitlines() if f.endswith(".py")][:max_files]
    mod_to_file = {_module_of(f): f for f in tracked}
    files = [dict(id=f, name=Path(f).name, path=f, kind="file") for f in tracked]
    deps: dict[tuple[str, str], int] = defaultdict(int)
    defs, funcs, func_names = [], [], defaultdict(dict)     # file -> {name: func_id}
    parsed: dict[str, ast.AST] = {}
    imports_of: dict[str, set[str]] = defaultdict(set)

    for f in tracked:
        try:
            tree = ast.parse((root / f).read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        parsed[f] = tree
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fid = f"{f}::{node.name}"
                if node.name not in func_names[f]:
                    func_names[f][node.name] = fid
                    funcs.append(dict(id=fid, name=node.name, path=f, kind="func"))
                    defs.append([f, fid])
        pkg = _module_of(f).split(".") if f.endswith("/__init__.py") else _module_of(f).split(".")[:-1]
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    up = pkg[:len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                    base = ".".join([*up, base]) if base else ".".join(up)
                targets = [base] + [f"{base}.{a.name}" if base else a.name for a in node.names]
            for t in targets:
                hit = mod_to_file.get(t)
                if hit and hit != f:
                    deps[(f, hit)] += 1
                    imports_of[f].add(hit)
                    break

    calls: set[tuple[str, str]] = set()
    for f, tree in parsed.items():
        visible = {**{n: i for g in imports_of[f] for n, i in func_names[g].items()}, **func_names[f]}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                caller = func_names[f].get(node.name)
                if not caller:
                    continue
                for c in ast.walk(node):
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name):
                        callee = visible.get(c.func.id)
                        if callee and callee != caller:
                            calls.add((caller, callee))

    commits = _commits(root, set(tracked), max_commits, since)
    return dict(files=files + funcs, deps=[[a, b, n] for (a, b), n in deps.items()], defs=defs,
                calls=[[a, b, 1] for a, b in sorted(calls)], commits=commits)


def _commits(root: Path, tracked: set[str], limit: int, since: str | None) -> list[dict]:
    args = ["log", "--no-merges", "--name-only", f"-n{limit}", "--format=@@%H|%at|%an|%s"]
    if since:
        args.append(f"--since={since}")
    out, commits, cur = _git(root, *args), [], None
    for line in out.splitlines():
        if line.startswith("@@"):
            sha, ts, author, msg = (line[2:].split("|", 3) + ["", "", ""])[:4]
            cur = dict(sha=sha, ts=int(ts) * 1000, author=author or "unknown", msg=msg[:200], files=[])
            commits.append(cur)
        elif line and cur is not None and line in tracked:
            cur["files"].append(line)
    return [c for c in commits if c["files"]]


def load_into(tm, root: str | Path, **kw) -> dict:
    """Convenience for scripts: `await tm.code_load(**load_repo(root))` (returns the coroutine)."""
    return tm.code_load(**load_repo(root, **kw))
