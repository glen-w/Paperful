"""Synthesize report layouts: bundled prompts, sidecar current-ness, CLI flag."""

from __future__ import annotations

import hashlib

import pytest

from paperful.config import Config, _from_dict, parse_synthesize_layout
from paperful.synthesis_layouts import (
    KNOWN_LAYOUTS,
    canonical_layout,
    load_layout_prompt,
    resolve_layout,
)
from paperful.synthesize import build_sidecar, report_is_current, write_report_files
from tests.test_llm_verbs import _two_sources


def test_canonical_and_config_layouts():
    assert canonical_layout(" Conflict ") == "conflict"
    assert parse_synthesize_layout("") == "default"
    cfg = Config()
    assert resolve_layout(cfg, None) == "default"
    cfg.synthesize_layout = "review"
    assert resolve_layout(cfg, None) == "review"
    assert resolve_layout(cfg, "conflict") == "conflict"


def test_nested_synthesize_layout_parses(tmp_path):
    cfg = _from_dict({"synthesize": {"layout": "conflict"}}, tmp_path / "config.toml")
    assert cfg.synthesize_layout == "conflict"


def test_prompt_file_wins_over_layout(tmp_path):
    path = tmp_path / "one.md"
    path.write_text("CUSTOM BRIEF", encoding="utf-8")
    cfg = Config()
    cfg.synthesize_layout = "conflict"
    cfg.synthesize_prompt_template = str(path)
    text, layout_id, label = load_layout_prompt(cfg)
    assert text == "CUSTOM BRIEF"
    assert layout_id == "custom"
    assert label == str(path)


def test_conflict_prompt_names_camps():
    cfg = Config()
    cfg.synthesize_layout = "conflict"
    text, layout_id, label = load_layout_prompt(cfg)
    assert layout_id == "conflict" == label
    assert "Camps" in text
    assert "Do not smooth" in text
    cfg.synthesize_layout = "review"
    review, rid, _ = load_layout_prompt(cfg)
    assert rid == "review"
    assert "Research question" in review
    assert set(KNOWN_LAYOUTS) == {"default", "conflict", "review"}


def test_report_is_current_respects_layout(cfg):
    cfg.llm_enabled = True
    loaded = _two_sources(cfg)
    html = "<h2>Themes</h2><p>ok</p>"
    text, _layout, _label = load_layout_prompt(cfg)
    sha = hashlib.sha256(text.encode()).hexdigest()[:8]
    sidecar = build_sidecar(
        cfg,
        scope="BBNJ",
        slug="bbnj",
        prompt_sha=sha,
        n_chunks=1,
        sources=loaded[0],
        missing=loaded[1],
        dest="disk",
        note_keys={},
    )
    write_report_files(cfg, "bbnj", html, sidecar)
    assert sidecar["layout"] == "default"
    assert report_is_current(cfg, "bbnj", loaded[0], dest="disk")
    cfg.synthesize_layout = "conflict"
    assert not report_is_current(cfg, "bbnj", loaded[0], dest="disk")


def test_unknown_layout_raises():
    with pytest.raises(ValueError, match="unknown synthesize layout"):
        canonical_layout("novelty")
