"""Production, CI and local development must run the same FalkorDB. `latest` moved between builds (4.22.1 on the server, 6.0.2 on a laptop) and three bugs
hid in the gap, so every compose file and the CI workflow name one image by digest, and the database a test run talks to must be that version."""
import os
import pathlib
import re

import pytest

from graphmem import Db

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = ["docker-compose.yml", "deploy/docker-compose.prod.yml", ".github/workflows/tests.yml"]
PINNED_VERSION = 42201                     # FalkorDB 4.22.1; change it together with the digest in those three files, after running the suite on the new one


def images():
    out = {}
    for f in FILES:
        found = re.findall(r"image:\s*(falkordb/falkordb\S*)", (ROOT / f).read_text(encoding="utf-8"))
        out[f] = found
    return out


def test_every_file_names_the_same_database_image_by_digest():
    found = images()
    assert all(len(v) == 1 for v in found.values()), found
    refs = {v[0] for v in found.values()}
    assert len(refs) == 1, found
    assert re.fullmatch(r"falkordb/falkordb@sha256:[0-9a-f]{64}", next(iter(refs))), refs      # a digest, never a moving tag like latest


async def test_the_database_under_test_is_the_pinned_version():
    mods = await Db().client.execute_command("MODULE", "LIST")
    ver = next(m["ver"] for m in mods if m["name"] == "graph")
    expected = int(os.getenv("CC_EXPECT_DB_VERSION", PINNED_VERSION))          # only .github/workflows/compat.yml sets this: the suite on the next engine
    assert ver == expected, (f"this database is graph module {ver}, the project is pinned to {PINNED_VERSION}: "
                                   f"start the pinned image (see docker-compose.yml) instead of whatever `latest` is today")


def test_every_way_of_running_it_persists_by_snapshots_only_and_the_docs_say_so():
    """Production dropped the append-only file (FalkorDB 4.22.1 crashes replaying one); the README's quick start, the persistence check and the docs must not describe the old way."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    for f in ("docker-compose.yml", "deploy/docker-compose.prod.yml", "scripts/check_persistence.py"):
        text = (root / f).read_text(encoding="utf-8")
        assert "--appendonly no" in text and "--appendonly yes" not in text, f
    for f in ("docs/TRACK02.md", "docs/DETAILS.md", "README.md"):
        text = (root / f).read_text(encoding="utf-8").lower()
        assert "synced every second" not in text and "fsync everysec" not in text and "append-only persistence" not in text, f
