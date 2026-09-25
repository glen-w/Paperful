from pathlib import Path

import pytest

from paperful.config import DEFAULT_MIRRORS, DEFAULT_SOURCES, Config, load_config


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(
        "paperful.config._candidate_paths", lambda explicit: [tmp_path / "nope.toml"]
    )
    cfg = load_config()
    assert cfg.sources == DEFAULT_SOURCES and cfg.scihub_mirrors == DEFAULT_MIRRORS
    assert cfg.ezproxy_cookie_path == cfg.state_dir / "ezproxy-cookies.txt"
    assert cfg.scholar_cookie_path == cfg.state_dir / "scholar-cookies.txt"
    assert "scihub" not in cfg.sources
    assert cfg.attach is True and cfg.concurrency_oa == 4
    assert cfg.mirror_pdfs == "additional"


def test_load_explicit_file_resolves_relative_paths(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("""
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
""")
    cfg = load_config(p)
    assert cfg.email == "me@example.org"
    assert cfg.out_dir == (tmp_path / "pdfs").resolve()
    assert cfg.state_dir == Path("~/.scihub-state").expanduser()
    assert cfg.sources == ["unpaywall", "scihub"] and cfg.scihub_mirrors == ["a.test"]
    assert cfg.delay_scihub_s == (1.0, 2.0)
    assert cfg.concurrency_oa == 1  # clamped to >= 1
    assert (
        cfg.attach is False
        and cfg.app_name == "custom"
        and cfg.mirror_failures_before_skip == 7
    )
    assert cfg.manifest_path == cfg.state_dir / "manifest.jsonl"
    assert cfg.local_key_path.parent == cfg.state_dir


def test_missing_explicit_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.toml")


def test_load_routing_and_scholar_cookie_paths(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("""
email = "me@example.org"
source_routing = false
circuit_breaker_threshold = 5
scholar_cookies = "cookies/scholar.txt"
state_dir = "state"
""")
    cfg = load_config(p)
    assert cfg.source_routing is False
    assert cfg.circuit_breaker_threshold == 5
    assert cfg.scholar_cookies == (tmp_path / "cookies" / "scholar.txt").resolve()
    assert cfg.scholar_cookie_path == cfg.scholar_cookies
    assert cfg.ezproxy_cookie_path == cfg.state_dir / "ezproxy-cookies.txt"


def test_load_manager_and_verify_flags(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("""
email = "me@example.org"
manager = "Zotero"
verify_doi = false
doi_suspect_score = 0.5
core_api_key = "abc"
""")
    cfg = load_config(p)
    assert cfg.manager == "zotero"
    assert cfg.verify_doi is False
    assert cfg.doi_suspect_score == 0.5
    assert cfg.core_api_key == "abc"


def test_load_mendeley_and_endnote_sections(tmp_path):
    enl = tmp_path / "Lib.enl"
    enl.write_bytes(b"x")
    p = tmp_path / "config.toml"
    p.write_text(
        f"""
email = "me@example.org"
manager = "mendeley"
[mendeley]
client_id = "cid"
client_secret = "csec"
redirect_uri = "http://127.0.0.1:9999/cb"
[endnote]
library = "{enl}"
"""
    )
    cfg = load_config(p)
    assert cfg.manager == "mendeley"
    assert cfg.mendeley_client_id == "cid"
    assert cfg.mendeley_client_secret == "csec"
    assert cfg.mendeley_redirect_uri == "http://127.0.0.1:9999/cb"
    assert cfg.endnote_library == enl.resolve()


def test_attachments_flags_default_off(tmp_path):
    from paperful.config import Config

    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n[attachments]\n'
        "fix_broken = true\nmerge_files = true\nrename = true\nlink = true\n"
    )
    cfg = load_config(p)
    assert cfg.attachments_fix_broken is True
    assert cfg.attachments_merge_files is True
    assert cfg.attachments_rename is True
    assert cfg.attachments_link is True
    assert Config().attachments_link is False


def test_mirror_pdfs_mode(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('email = "me@example.org"\n\n[mirror]\npdfs = "all"\n')
    cfg = load_config(p)
    assert cfg.mirror_pdfs == "all"
    bad = tmp_path / "bad.toml"
    bad.write_text('email = "me@example.org"\n\n[mirror]\npdfs = "everything"\n')
    with pytest.raises(ValueError, match="pdfs"):
        load_config(bad)


def test_remarks_surface(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('email = "me@example.org"\n\n[remarks]\nsurface = "tag"\n')
    assert load_config(p).remarks_surface == "tag"
    p.write_text('email = "me@example.org"\n\n[remarks]\nsurface = "poster"\n')
    with pytest.raises(ValueError, match="surface"):
        load_config(p)


def test_example_config_toml_parses_and_omits_scihub_by_default():
    repo_cfg = Path(__file__).resolve().parent.parent / "config.example.toml"
    cfg = load_config(repo_cfg)
    assert cfg.email == "you@example.org"
    assert "scihub" not in cfg.sources
    assert "core" in cfg.sources
    assert cfg.manager == "zotero"
    assert cfg.sources[-1] == "htmlpdf"
    assert cfg.out_dir == (repo_cfg.parent / "out").resolve()
    assert cfg.state_dir == (repo_cfg.parent / "state").resolve()
    assert isinstance(cfg, Config)
