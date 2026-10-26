"""House glossary fuzzy acronym checks. No network."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from paperful.critique import build_critique
from paperful.critique_checks import _glossary_acronyms
from paperful.critique_extract import ExtractedDoc
from paperful.glossary import (
    SCHEMA,
    GlossaryEntry,
    load_glossary,
    normalize_phrase,
    phrase_similarity,
    scan_glossary,
    vale_swap_yaml,
)

runner = CliRunner()

BBNJ = GlossaryEntry(
    token="BBNJ",
    expansion="Areas Beyond National Jurisdiction",
    aliases=(
        "Maritime Area beyond national jurisdictions",
        "marine areas beyond national jurisdiction",
    ),
)


def _write_glossary(cfg, entries: list[dict]) -> Path:
    root = cfg.state_dir / "glossary"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "library.json"
    path.write_text(
        json.dumps({"schema": SCHEMA, "scope": "library", "entries": entries}) + "\n",
        encoding="utf-8",
    )
    return path


def test_bbnj_window_is_similar_enough():
    assert (
        phrase_similarity(
            "Area beyond national jurisdictions",
            "Areas Beyond National Jurisdiction",
        )
        >= 0.88
    )
    assert normalize_phrase(
        "the Areas Beyond National Jurisdiction"
    ) == normalize_phrase("Areas Beyond National Jurisdiction")


def test_scan_expansion_and_bare_phrase():
    expansion_body = (
        "The Maritime Areas beyond national jurisdiction (BBNJ) agreement "
        "governs biodiversity."
    )
    hits = scan_glossary(expansion_body, (BBNJ,))
    assert {h.code for h in hits} == {"acronym_expansion_mismatch"}
    assert hits[0].token == "BBNJ"
    assert "Areas Beyond National Jurisdiction" in hits[0].detail

    phrase_body = (
        "Governance in Maritime Area beyond national jurisdictions remains contested."
    )
    hits = scan_glossary(phrase_body, (BBNJ,))
    assert {h.code for h in hits} == {"acronym_phrase_mismatch"}
    assert "Maritime Area" in hits[0].quote
    assert hits[0].suggested == "Areas Beyond National Jurisdiction"


def test_canonical_phrase_and_expansion_are_silent():
    body = (
        "The Areas Beyond National Jurisdiction (BBNJ) treaty covers "
        "Areas Beyond National Jurisdiction as a legal space."
    )
    assert scan_glossary(body, (BBNJ,)) == []


def test_empty_glossary_is_silent(cfg):
    doc = ExtractedDoc(
        text="Maritime Area beyond national jurisdictions (BBNJ) is cited.",
        format="md",
    )
    assert _glossary_acronyms(cfg, doc) == []


def test_quotes_are_skipped(cfg):
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
    doc = ExtractedDoc(
        text=(
            'Smith wrote "Maritime Area beyond national jurisdictions" in 2018. '
            "Later work is careful."
        ),
        format="md",
    )
    assert _glossary_acronyms(cfg, doc) == []


def test_disabled_glossary_skips_files(cfg):
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
    cfg.critique_glossary = False
    doc = ExtractedDoc(
        text="Maritime Area beyond national jurisdictions is the usual phrase.",
        format="md",
    )
    assert _glossary_acronyms(cfg, doc) == []


def test_pack_includes_glossary_codes(cfg, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
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
        "Abstract\n"
        "Maritime Area beyond national jurisdictions (BBNJ) is defined here.\n"
        "Introduction\n"
        "Methods and results follow. Limitations are noted.\n"
        "Related work is thin.\n",
        encoding="utf-8",
    )
    pack = build_critique(cfg, file_path=src, offline=True, dry_run=True)
    codes = {f["code"] for f in pack["findings"]}
    assert "acronym_expansion_mismatch" in codes
    row = next(f for f in pack["findings"] if f["code"] == "acronym_expansion_mismatch")
    assert row["lane"] == "checked"
    assert row["source"] == "glossary"
    assert row["suggested"] == "Areas Beyond National Jurisdiction"


def test_load_and_vale_export(cfg):
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
    entries, issues = load_glossary(cfg)
    assert not [row for row in issues if row.level == "error"]
    assert len(entries) == 1
    yaml_text = vale_swap_yaml(entries)
    assert "extends: substitution" in yaml_text
    assert "Maritime Area beyond national jurisdictions" in yaml_text
    assert "Areas Beyond National Jurisdiction" in yaml_text


def test_cli_validate_and_export(cfg, tmp_path: Path, monkeypatch):
    from paperful.cli import app

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
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    ok = runner.invoke(app, ["glossary", "validate", "--config", str(cfg_path)])
    assert ok.exit_code == 0, ok.output
    assert "BBNJ" in ok.output
    dest = tmp_path / "BBNJ.yml"
    exported = runner.invoke(
        app,
        ["glossary", "export-vale", "--out", str(dest), "--config", str(cfg_path)],
    )
    assert exported.exit_code == 0, exported.output
    text = dest.read_text(encoding="utf-8")
    assert "swap:" in text
    assert "Maritime Area beyond national jurisdictions" in text
