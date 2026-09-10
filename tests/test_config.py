from pathlib import Path

import pytest

from paperful.config import DEFAULT_MIRRORS, DEFAULT_SOURCES, Config, load_config


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("paperful.config._candidate_paths", lambda explicit: [tmp_path / "nope.toml"])
    cfg = load_config()
    assert cfg.sources == DEFAULT_SOURCES and cfg.scihub_mirrors == DEFAULT_MIRRORS
    assert "scihub" not in cfg.sources
    assert cfg.attach is True and cfg.concurrency_oa == 4


def test_load_explicit_file_resolves_relative_paths(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        """
email = "me@example.org"
out_dir = "pdfs"
state_dir = "~/.scihub-state"
sources = ["unpaywall", "scihub"]
scihub_mirrors = ["a.test"]
delay_scihub_s = [1, 2]
concurrency_oa = 0
min_pdf_bytes = 5
crossref_min_score = 0.8
attach = false
app_name = "custom"
mirror_failures_before_skip = 7
"""
    )
    cfg = load_config(p)
    assert cfg.email == "me@example.org"
    assert cfg.out_dir == (tmp_path / "pdfs").resolve()
    assert cfg.state_dir == Path("~/.scihub-state").expanduser()
    assert cfg.sources == ["unpaywall", "scihub"] and cfg.scihub_mirrors == ["a.test"]
    assert cfg.delay_scihub_s == (1.0, 2.0)
    assert cfg.concurrency_oa == 1  # clamped to >= 1
    assert cfg.attach is False and cfg.app_name == "custom" and cfg.mirror_failures_before_skip == 7
    assert cfg.manifest_path == cfg.state_dir / "manifest.jsonl"
    assert cfg.local_key_path.parent == cfg.state_dir


def test_missing_explicit_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.toml")


def test_load_routing_and_scholar_cookie_paths(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        """
email = "me@example.org"
source_routing = false
circuit_breaker_threshold = 5
scholar_cookies = "cookies/scholar.txt"
state_dir = "state"
"""
    )
    cfg = load_config(p)
    assert cfg.source_routing is False
    assert cfg.circuit_breaker_threshold == 5
    assert cfg.scholar_cookies == (tmp_path / "cookies" / "scholar.txt").resolve()


def test_example_config_toml_parses_and_omits_scihub_by_default():
    repo_cfg = Path(__file__).resolve().parent.parent / "config.example.toml"
    cfg = load_config(repo_cfg)
    assert cfg.email == "you@example.org"
    assert "scihub" not in cfg.sources
    assert cfg.sources[-1] == "htmlpdf"
    assert "htmlpdf" in cfg.sources
    assert cfg.out_dir == (repo_cfg.parent / "out").resolve()
    assert cfg.state_dir == (repo_cfg.parent / "state").resolve()
    assert isinstance(cfg, Config)
