"""Sphinx guide corpus: git Markdown under docs/ is the single source of truth."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.md"

_SKIP_STEMS = frozenset({"index"})


def _toctree_stems(text: str) -> set[str]:
    stems: set[str] = set()
    for block in re.findall(r"```\{toctree\}.*?```", text, flags=re.DOTALL):
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith(":") or line.startswith("```"):
                continue
            stems.add(line.split("#", 1)[0].strip())
    return stems


def _toctree_entries(text: str) -> list[str]:
    entries: list[str] = []
    for block in re.findall(r"```\{toctree\}.*?```", text, flags=re.DOTALL):
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith(":") or line.startswith("```"):
                continue
            entries.append(line.split("#", 1)[0].strip())
    return entries


def _guide_markdown_stems() -> set[str]:
    return {p.stem for p in DOCS.glob("*.md") if p.stem not in _SKIP_STEMS}


def test_every_guide_page_is_in_toctree():
    index_text = INDEX.read_text(encoding="utf-8")
    in_tree = _toctree_stems(index_text)
    on_disk = _guide_markdown_stems()

    missing = sorted(on_disk - in_tree)
    assert not missing, (
        "docs/*.md must appear in a toctree in docs/index.md "
        f"(missing: {', '.join(missing)})"
    )

    orphans = sorted(in_tree - on_disk)
    assert not orphans, (
        "docs/index.md toctree lists files that do not exist "
        f"(orphans: {', '.join(orphans)})"
    )


def test_toctree_has_no_duplicate_entries():
    entries = _toctree_entries(INDEX.read_text(encoding="utf-8"))
    seen: set[str] = set()
    dupes: list[str] = []
    for entry in entries:
        if entry in seen:
            dupes.append(entry)
        seen.add(entry)
    assert not dupes, f"duplicate toctree entries in docs/index.md: {', '.join(sorted(set(dupes)))}"


def test_gui_md_documents_discover_and_wanted_routes():
    """Keep gui.md route table aligned with the workbench thicken wave."""
    text = (DOCS / "gui.md").read_text(encoding="utf-8")
    required = (
        "/discover/topic",
        "/discover/follow",
        "/discover/keep",
        "/discover/check-again",
        "/discover/aw/import",
        "/discover/aw/briefing",
        "/wanted/preview",
        "/wanted/grab",
        "/wanted/attach",
        "/briefs/summarize",
        "/index/ask",
        "Briefs",
    )
    missing = [path for path in required if path not in text]
    assert not missing, f"docs/gui.md missing workbench routes/surfaces: {', '.join(missing)}"
