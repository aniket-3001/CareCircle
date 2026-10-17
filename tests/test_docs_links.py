"""Every relative link in the README and the technical write-up points at a file that exists, and every #anchor at a heading that exists."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "docs" / "DETAILS.md"]


def slug(heading: str) -> str:
    s = re.sub(r"[^\w\s-]", "", heading.lower())
    return re.sub(r"\s+", "-", s.strip())


def anchors(path: pathlib.Path) -> set[str]:
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.*)$", path.read_text(encoding="utf-8"), re.M)}


def test_relative_links_and_anchors_in_the_readme_and_details_resolve():
    bad = []
    for doc in DOCS:
        for target in re.findall(r"\]\(([^)\s]+)\)", doc.read_text(encoding="utf-8")):
            if re.match(r"(https?:|mailto:)", target):
                continue
            path, _, frag = target.partition("#")
            dest = doc if not path else (doc.parent / path).resolve()
            if not dest.exists():
                bad.append(f"{doc.name}: {target} (no such file)")
            elif frag and dest.suffix == ".md" and frag not in anchors(dest):
                bad.append(f"{doc.name}: {target} (no such heading)")
    assert not bad, bad


def test_the_readme_carries_no_hand_typed_test_count():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert not re.search(r"\b\d{2,4} (passing )?tests\b", text, re.I), "use `python scripts/counts.py`"
