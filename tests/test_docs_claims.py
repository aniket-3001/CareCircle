"""Claims in the docs that went out of date once and must not again: what is on in the live deployment, and what was run. These are checks on specific wording
that was wrong, not a proof that every sentence is right."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ["README.md", "docs/DETAILS.md", "docs/HAZARDS.md", "docs/TRACK02.md", "docs/BENCHMARKS.md"]


def text(f):
    return (ROOT / f).read_text(encoding="utf-8").lower()


def test_no_doc_says_cookie_sessions_are_off_on_the_live_site():
    """They are on in the live deployment (the compose default is off, which a self-hosted copy inherits)."""
    for f in DOCS:
        t = text(f)
        assert not re.search(r"cookie sessions? (are|is) off on the live", t), f
        assert "off by default on the live site" not in t, f


def test_mem0_is_described_as_run_in_b6_and_never_as_not_run():
    for f in DOCS:
        t = text(f)
        assert not re.search(r"mem0[^.\n]{0,80}\*{0,2}not\*{0,2} run", t), f
        assert not re.search(r"\*{0,2}not\*{0,2} run[^.\n]{0,80}mem0", t), f
    assert "mem0" in text("docs/BENCHMARKS.md") and "b6" in text("docs/BENCHMARKS.md")


def test_the_live_cookie_setting_is_what_the_docs_say():
    """The compose default is off and the live deployment turns it on; the docs say both, so a reader of the compose file is not surprised."""
    assert "${CC_COOKIE_SESSIONS:-0}" in (ROOT / "deploy/docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "on in the live deployment" in text("docs/DETAILS.md")


def test_no_doc_promises_a_crash_loses_only_the_last_second():
    """Production keeps snapshots only (no append-only file since 17 Oct): a hard crash can lose up to a minute. 'At most the last second' was the old setting."""
    for f in DOCS + ["deploy/RESTORE.md"]:
        t = text(f)
        assert "at most the last second" not in t and "loses at most the last second" not in t, f
