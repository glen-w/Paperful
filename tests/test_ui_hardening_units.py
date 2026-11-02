"""Unit tests for the GUI hardening wave helpers (no server, no browser)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from paperful.config import Config
from paperful.store import Manifest
from paperful.ui import commands, jobs
from paperful.ui.config_patch import (
    ConfigPatchError,
    apply_patches,
    patch_assignment,
    toml_literal,
)
from paperful.ui.discover_rows import snowball_run_label
from paperful.ui.errors import same_host_path
from paperful.ui.prefs import cookie_name, prefs_from_request
from paperful.ui.snowball_form import _multi, parse_discover_topic

tomllib = __import__("tomllib" if sys.version_info >= (3, 11) else "tomli")


# --- config_patch -----------------------------------------------------------


def test_toml_literal_escapes_quotes_and_backslashes():
    assert toml_literal('C:\\papers\\"mine"') == '"C:\\\\papers\\\\\\"mine\\""'
    assert toml_literal(True) == "true"
    assert toml_literal(3) == "3"
    quoted = toml_literal('a"b')
    assert tomllib.loads(f"x = {quoted}")["x"] == 'a"b'


def test_patch_assignment_root_key_stays_in_root_table():
    text = '[twenty]\nemail = "crm@x.org"\n'
    out = patch_assignment(text, "", "email", "me@x.org")
    data = tomllib.loads(out)
    assert data["email"] == "me@x.org"
    assert data["twenty"]["email"] == "crm@x.org"


def test_patch_assignment_replaces_existing_and_appends_missing_section():
    text = 'email = "a@b.c"\n\n[ui]\nweb_search = "on"\n'
    out = patch_assignment(text, "ui", "web_search", "off")
    out = patch_assignment(out, "ui", "attach_mode", "auto")
    out = patch_assignment(out, "zotero", "host", "host.docker.internal")
    data = tomllib.loads(out)
    assert data["ui"] == {"web_search": "off", "attach_mode": "auto"}
    assert data["zotero"]["host"] == "host.docker.internal"
    assert out.count("[ui]") == 1


def test_apply_patches_refuses_missing_file_and_keeps_comments(tmp_path: Path):
    path = tmp_path / "config.toml"
    with pytest.raises(ConfigPatchError):
        apply_patches(path, {("", "email"): "x@y.z"})
    path.write_text('# keep me\nemail = "a@b.c"\n', encoding="utf-8")
    apply_patches(path, {("", "email"): "x@y.z", ("ui", "web_search"): "off"})
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# keep me")
    assert tomllib.loads(text)["ui"]["web_search"] == "off"
    assert not list(tmp_path.glob("*.part")), "atomic write leaves no temp file"


# --- errors.same_host_path --------------------------------------------------


@pytest.mark.parametrize(
    "url,host,expected",
    [
        ("http://127.0.0.1:8765/wanted?tab=held", "127.0.0.1:8765", "/wanted?tab=held"),
        ("http://evil.example/x", "127.0.0.1:8765", ""),
        ("/library", "127.0.0.1:8765", "/library"),
        ("//evil.example/x", "127.0.0.1:8765", ""),
        ("", "127.0.0.1:8765", ""),
        ("http://127.0.0.1:8765", "127.0.0.1:8765", "/"),
    ],
)
def test_same_host_path(url, host, expected):
    assert same_host_path(url, host) == expected


# --- prefs: port-scoped cookie names ----------------------------------------


class _Req:
    def __init__(self, port, cookies=None, host=None):
        class U:
            pass

        self.url = U()
        self.url.port = port
        self.cookies = cookies or {}
        self.headers = {"host": host} if host else {}


def test_cookie_name_default_port_and_other_ports():
    assert cookie_name(_Req(8765), "pf_collection") == "pf_collection"
    assert cookie_name(_Req(None), "pf_collection") == "pf_collection"
    assert cookie_name(_Req(8799), "pf_collection") == "pf_collection_8799"
    assert (
        cookie_name(_Req(None, host="127.0.0.1:9000"), "pf_advanced")
        == "pf_advanced_9000"
    )


def test_prefs_read_only_their_own_port():
    req = _Req(8799, cookies={"pf_collection": "wrong", "pf_collection_8799": "ocean"})
    assert prefs_from_request(req).collection == "ocean"
    req = _Req(8765, cookies={"pf_collection_8799": "ocean", "pf_preset": "bogus"})
    prefs = prefs_from_request(req)
    assert prefs.collection == ""
    assert prefs.preset == "oa"


# --- snowball_form._multi / checkbox chips ----------------------------------


class _Form(dict):
    def __init__(self, items):
        super().__init__()
        self._items = items
        for k, v in items:
            self[k] = v

    def getlist(self, key):
        return [v for k, v in self._items if k == key]


def test_multi_joins_repeated_fields_and_plain_dicts():
    form = _Form([("backends", "openalex"), ("backends", "crossref"), ("q", "x")])
    assert _multi(form, "backends") == "openalex,crossref"
    assert (
        _multi({"backends": "openalex, crossref"}, "backends") == "openalex, crossref"
    )
    assert _multi({}, "backends") == ""


def test_parse_discover_topic_accepts_chip_checkboxes():
    form = _Form(
        [
            ("kind", "search"),
            ("query", "ocean"),
            ("study_designs", "meta-analysis"),
            ("study_designs", "rct"),
            ("listed_in", "doaj"),
            ("backends", "openalex"),
            ("backends", "crossref"),
        ]
    )
    payload = parse_discover_topic(form, advanced=True)
    assert set(payload.study_designs) == {
        "meta-analysis",
        "randomized-controlled-trial",
    }
    assert payload.listed_in == ("doaj",)
    assert payload.backends == ("openalex", "crossref")
    simple = parse_discover_topic(form, advanced=False)
    assert simple.study_designs is None and simple.backends is None


# --- commands: finish hooks + scope cache -----------------------------------


def test_finish_hook_runs_after_job_and_scope_cache_invalidates(tmp_path: Path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    seen: list[str] = []
    commands.register_finish_hook(lambda rec: seen.append(rec["status"]))
    loads = {"n": 0}

    class Item:
        key = "K1"

    def fake_load(_cfg, _col):
        loads["n"] += 1
        return [Item()], Manifest(cfg.manifest_path)

    original = jobs._load_scope_items
    jobs._load_scope_items = fake_load  # type: ignore[assignment]
    try:
        jobs.invalidate_scope_cache()
        jobs.load_scope_items_cached(cfg, "ocean")
        jobs.load_scope_items_cached(cfg, "ocean")
        assert loads["n"] == 1, "second render is served from cache"
        cmd_id = commands.enqueue(cfg, "noop", lambda _id: None)
        deadline = time.time() + 5
        while time.time() < deadline and "done" not in seen:
            time.sleep(0.01)
        assert "done" in seen
        jobs.load_scope_items_cached(cfg, "ocean")
        assert loads["n"] == 2, "a finished job drops the scope cache"
        rec = commands.read_command(cfg, cmd_id)
        assert rec["started"] <= rec["finished"]
    finally:
        jobs._load_scope_items = original  # type: ignore[assignment]
        jobs.invalidate_scope_cache()


def test_scope_cache_never_caches_empty_scope(tmp_path: Path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    calls = {"n": 0}

    def fake_load(_cfg, _col):
        calls["n"] += 1
        return [], Manifest(cfg.manifest_path)

    original = jobs._load_scope_items
    jobs._load_scope_items = fake_load  # type: ignore[assignment]
    try:
        jobs.invalidate_scope_cache()
        jobs.load_scope_items_cached(cfg, "empty")
        jobs.load_scope_items_cached(cfg, "empty")
        assert calls["n"] == 2, "an empty (library down?) scope is retried"
        assert jobs.load_scope_items_cached(cfg, "")[0] == []
    finally:
        jobs._load_scope_items = original  # type: ignore[assignment]


# --- discover_rows.snowball_run_label --------------------------------------


def test_snowball_run_label_reads_summary_and_stamp(tmp_path: Path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    run = cfg.state_dir / "snowball" / "20261030T211722Z"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(
        json.dumps({"query": "high seas", "target_collection": "ocean"}),
        encoding="utf-8",
    )
    label = snowball_run_label(cfg, run.name)
    assert label == {
        "run_id": run.name,
        "query": "high seas",
        "collection": "ocean",
        "when": "2026-10-30 21:17 UTC",
    }
    assert snowball_run_label(cfg, "")["query"] == ""
    assert snowball_run_label(cfg, "no-such-run")["when"] == ""


# --- shell_routes helpers ---------------------------------------------------


def test_page_for_verb_and_result_summary():
    from paperful.ui.shell_routes import _result_summary, page_for_verb

    assert page_for_verb("snowball_search") == "/discover?tab=queue"
    assert page_for_verb("summarize_item") == "/wanted"
    assert page_for_verb("summarize") == "/index"
    assert page_for_verb("search_watch") == "/discover?tab=web"
    assert page_for_verb("repair_lint") == "/repair"
    assert page_for_verb("mystery") == ""
    summary = _result_summary(
        {
            "result": {
                "would_fetch": 3,
                "markdown": "x" * 500,
                "rows": [1, 2],
                "slug": "s" * 60,
            }
        }
    )
    assert "would_fetch 3" in summary and "rows 2" in summary and "…" in summary
    assert "x" * 50 not in summary
    assert _result_summary({"result": "not a dict"}) == ""


def test_picker_title_clips_long_titles_and_falls_back_to_key():
    from paperful.ui.page_common import picker_title

    assert picker_title("Short", "K1") == "Short"
    assert picker_title("  spaced   out  ", "K1") == "spaced out"
    assert picker_title(None, "K1") == "K1"
    long = "word " * 60
    clipped = picker_title(long, "K1")
    assert len(clipped) <= 90 and clipped.endswith("…")
