"""Post-edit glossary and cite checkers."""

from __future__ import annotations

import json

from paperful.glossary import SCHEMA
from paperful.rewrite import build_rewrite
from tests.test_rewrite import _finding, _pack


def _write_glossary(cfg, entries: list[dict]) -> None:
    root = cfg.state_dir / "glossary"
    root.mkdir(parents=True, exist_ok=True)
    (root / "library.json").write_text(
        json.dumps({"schema": SCHEMA, "scope": "library", "entries": entries}) + "\n",
        encoding="utf-8",
    )


def test_clean_glossary_swap_still_applies(cfg, tmp_path):
    _write_glossary(
        cfg,
        [
            {
                "token": "BBNJ",
                "expansion": "Areas Beyond National Jurisdiction",
                "aliases": ["Maritime Area beyond national jurisdictions"],
            }
        ],
    )
    src = tmp_path / "draft.md"
    src.write_text(
        "The BBNJ Agreement covers Maritime Area beyond national jurisdictions.\n",
        encoding="utf-8",
    )
    pack = _pack([_finding()], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits",),
        dry_run=True,
        llm_client=None,
    )
    edits = (result.get("plan") or {}).get("edits") or []
    assert edits
    assert edits[0]["kind"] == "replace"


def test_glossary_regression_is_broken_check(cfg, tmp_path):
    _write_glossary(
        cfg,
        [
            {
                "token": "BBNJ",
                "expansion": "Areas Beyond National Jurisdiction",
                "aliases": ["Maritime Area beyond national jurisdictions"],
            }
        ],
    )
    src = tmp_path / "draft.md"
    src.write_text("This protocol is unique in the treaty.\n", encoding="utf-8")
    finding = _finding(
        code="vale_swap",
        quote="This protocol is unique",
        extra={"suggested": "Maritime Area beyond national jurisdictions (BBNJ)"},
        loc="paragraph 1",
        source="vale",
    )
    pack = _pack([finding], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits",),
        dry_run=True,
        llm_client=None,
    )
    edits = (result.get("plan") or {}).get("edits") or []
    skips = (result.get("plan") or {}).get("skips") or []
    assert not edits
    assert any(s.get("reason") == "broken_check" for s in skips)


def test_cite_not_in_bibliography_is_broken_check(cfg, tmp_path):
    src = tmp_path / "draft.md"
    src.write_text("See the earlier review for context.\n", encoding="utf-8")
    finding = _finding(
        code="vale_swap",
        quote="the earlier review",
        extra={"suggested": "the earlier review \\cite{missing2024}"},
        loc="paragraph 1",
        source="vale",
    )
    pack = _pack([finding], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits",),
        dry_run=True,
        llm_client=None,
    )
    skips = (result.get("plan") or {}).get("skips") or []
    assert any(s.get("reason") == "broken_check" for s in skips)
    assert not ((result.get("plan") or {}).get("edits") or [])
