"""Firefox capture: mirror writes, live Zotero identity, no library create."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
import typer

from paperful.capture import apply_page, plan_page, read_session
from paperful.config import Config
from paperful.handoff import HINT_OPENABLE, MissingPdf, open_tabs
from paperful.store import write_json


class _Resp:
    def __init__(self, rows):
        self._rows = rows

    def json(self):
        return self._rows


class FakeLibrary:
    def __init__(self, rows):
        self.rows = rows
        self.gets = 0

    def ping(self):
        return {"ok": True}

    def get(self, path, **params):
        self.gets += 1
        if path != "/items":
            raise FileNotFoundError(path)
        return _Resp(self.rows)

    def collections(self):
        return {}


def _cfg(tmp_path: Path, **overrides) -> Config:
    cfg = Config(
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        extension_snapshot="off",
        extension_drop=str(tmp_path / "drop"),
        min_pdf_bytes=8,
        sources=["unpaywall"],
    )
    cfg.out_dir.mkdir()
    cfg.state_dir.mkdir()
    Path(cfg.extension_drop).mkdir()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _quiet(*_args, **_kwargs):
    return None


def _row(key, doi, title="Example", url="https://publisher.example/a", year=2020):
    return {
        "key": key,
        "data": {
            "key": key,
            "itemType": "journalArticle",
            "title": title,
            "DOI": doi,
            "url": url,
            "date": str(year),
            "creators": [{"creatorType": "author", "lastName": "Smith"}],
            "collections": [],
        },
    }


def _mirror(cfg: Config, key: str, **record) -> Path:
    folder = cfg.out_dir / "Capture" / f"Smith - 2020 - A paper -- {key}"
    folder.mkdir(parents=True)
    body = {
        "item_key": key,
        "title": record.pop("title", "A paper"),
        "year": 2020,
        "doi": record.pop("doi", "10.1000/example"),
        **record,
    }
    write_json(folder / "record.json", body)
    return folder


def _down(_cfg):
    return None


def test_doi_in_zotero_missing_from_mirror_is_update(tmp_path):
    cfg = _cfg(tmp_path)
    live = FakeLibrary([_row("ABCD1234", "10.1000/example")])
    result = plan_page(
        cfg,
        doi="10.1000/example",
        opener=lambda _c: live,
        run_sync_fn=_quiet,
    )
    assert result["action"] == "update"
    assert result["key"] == "ABCD1234"
    assert not result["key"].startswith("pf")


def test_stale_mirror_does_not_create(tmp_path):
    cfg = _cfg(tmp_path)
    live = FakeLibrary([_row("ABCD1234", "10.1000/example")])
    calls = []

    def snap(*args, **kwargs):
        calls.append((args, kwargs))

    result = apply_page(
        cfg,
        {"doi": "10.1000/example", "apply": True},
        opener=lambda _c: live,
        run_sync_fn=_quiet,
        snapshot_item_fn=snap,
    )
    assert len(calls) == 1
    assert result["ok"] is False
    assert not any(path.name.startswith("pf") for path in cfg.out_dir.rglob("*"))
    assert not list(cfg.out_dir.rglob("record.json"))


def test_snapshot_auto_calls_run_sync(tmp_path):
    cfg = _cfg(tmp_path, extension_snapshot="auto", mirror_refresh="manual")
    live = FakeLibrary([])
    calls = []

    def sync(*args, **kwargs):
        calls.append(args)

    plan_page(
        cfg,
        doi="10.1000/new",
        opener=lambda _c: live,
        run_sync_fn=sync,
    )
    assert len(calls) == 1


def test_snapshot_off_skips_run_sync(tmp_path):
    cfg = _cfg(tmp_path, extension_snapshot="off")
    live = FakeLibrary([_row("ABCD1234", "10.1000/example")])
    calls = []

    def sync(*args, **kwargs):
        calls.append(args)

    plan_page(
        cfg,
        doi="10.1000/example",
        opener=lambda _c: live,
        run_sync_fn=sync,
    )
    assert calls == []
    assert live.gets >= 1


def test_zotero_down_blocks_create(tmp_path):
    cfg = _cfg(tmp_path)
    blocked = plan_page(cfg, doi="10.1000/missing", opener=_down, run_sync_fn=_quiet)
    assert blocked["action"] == "blocked"
    assert blocked["reason"] == "zotero_unread"
    refused = apply_page(
        cfg,
        {"doi": "10.1000/missing", "apply": True},
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert refused["ok"] is False
    assert list(cfg.out_dir.rglob("record.json")) == []
    created = apply_page(
        cfg,
        {"doi": "10.1000/missing", "title": "New", "apply": True, "allow_unread": True},
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert created["ok"] is True
    assert created["key"].startswith("pf")
    records = list(cfg.out_dir.rglob("record.json"))
    assert len(records) == 1


def test_mirror_doi_updates_without_zotero(tmp_path):
    cfg = _cfg(tmp_path)
    _mirror(cfg, "ABCD1234", doi="10.1000/example", title="Kept")
    result = plan_page(
        cfg, doi="10.1000/example", opener=_down, run_sync_fn=_quiet
    )
    assert result["action"] == "update"
    assert result["key"] == "ABCD1234"
    assert result["reason"] != "zotero_unread"


def test_blank_fields_only(tmp_path):
    cfg = _cfg(tmp_path)
    folder = _mirror(
        cfg,
        "ABCD1234",
        doi="10.1000/example",
        title="Kept title",
        abstract="",
    )
    result = apply_page(
        cfg,
        {
            "doi": "10.1000/example",
            "apply": True,
            "page": {"abstract": "Filled in", "title": "Different title"},
        },
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert result["ok"] is True
    saved = json.loads((folder / "record.json").read_text())
    assert saved["title"] == "Kept title"
    assert saved["abstract"] == "Filled in"


def test_existing_pdf_kept(tmp_path):
    cfg = _cfg(tmp_path)
    folder = _mirror(cfg, "ABCD1234", doi="10.1000/example", pdf=True)
    original = folder / "Smith - 2020 - A paper.pdf"
    original.write_bytes(b"%PDF-1.4\nkept\n")
    before = original.read_bytes()
    incoming = Path(cfg.extension_drop) / "other.pdf"
    incoming.write_bytes(b"%PDF-1.4\nother\n")
    result = apply_page(
        cfg,
        {"doi": "10.1000/example", "apply": True, "pdf_path": str(incoming)},
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert result["pdf"] == "kept"
    assert original.read_bytes() == before
    assert not (folder / "other.pdf").exists()


def test_pdf_outside_drop_dir_refused(tmp_path):
    cfg = _cfg(tmp_path)
    folder = _mirror(cfg, "ABCD1234", doi="10.1000/example", pdf=False)
    result = apply_page(
        cfg,
        {"doi": "10.1000/example", "apply": True, "pdf_path": "/tmp/evil.pdf"},
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert result["pdf"] == "refused"
    assert list(folder.glob("*.pdf")) == []


def test_refused_host(tmp_path):
    cfg = _cfg(tmp_path)
    result = plan_page(
        cfg,
        url="https://sci-hub.se/10.1000/example",
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert result["action"] == "blocked"
    assert result["reason"] == "refused_host"
    applied = apply_page(
        cfg,
        {"url": "https://sci-hub.se/10.1000/example", "apply": True, "allow_unread": True},
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert applied["ok"] is False
    assert list(cfg.out_dir.rglob("record.json")) == []


def test_ambiguous_needs_confirm_key(tmp_path):
    cfg = _cfg(tmp_path)
    live = FakeLibrary(
        [
            _row("ABCD1234", "10.1000/example"),
            _row("EFGH5678", "10.1000/example"),
        ]
    )
    planned = plan_page(
        cfg,
        doi="10.1000/example",
        opener=lambda _c: live,
        run_sync_fn=_quiet,
    )
    assert planned["action"] == "ambiguous"
    applied = apply_page(
        cfg,
        {"doi": "10.1000/example", "apply": True},
        opener=lambda _c: live,
        run_sync_fn=_quiet,
        snapshot_item_fn=lambda *a, **k: None,
    )
    assert applied["ok"] is False
    assert list(cfg.out_dir.rglob("record.json")) == []


def test_title_match_is_not_update(tmp_path):
    cfg = _cfg(tmp_path)
    _mirror(cfg, "ABCD1234", doi="10.9999/other", title="Same Title", year=2020)
    live = FakeLibrary([])
    result = plan_page(
        cfg,
        title="Same Title",
        year=2020,
        opener=lambda _c: live,
        run_sync_fn=_quiet,
    )
    assert result["action"] == "create"
    assert result["maybe"]
    assert result["key"] != "ABCD1234"


def test_lanes_force_mirror_only(tmp_path):
    cfg = _cfg(tmp_path)
    _mirror(cfg, "ABCD1234", doi="10.1000/example", pdf=False)
    seen = {}

    def spy(cfg_arg, key, **kwargs):
        seen["key"] = key
        seen.update(kwargs)

    result = apply_page(
        cfg,
        {"doi": "10.1000/example", "apply": True, "lanes": True},
        opener=_down,
        run_sync_fn=_quiet,
        run_fetch_fn=spy,
    )
    assert result["ok"] is True
    assert seen["key"] == "ABCD1234"
    assert seen["force_mirror_only"] is True
    assert seen["no_attach"] is True


def test_session_roundtrip(tmp_path):
    cfg = _cfg(tmp_path)
    row = MissingPdf(
        key="ABCD1234",
        title="Example",
        doi="10.1000/example",
        url="https://publisher.example/paper.pdf",
        hint=HINT_OPENABLE,
        attempts=[],
    )
    opened = []
    assert (
        open_tabs(
            [row],
            opener=lambda url: opened.append(url) or True,
            cfg=cfg,
        )
        == 1
    )
    session = read_session(cfg)
    assert session["items"][0]["key"] == "ABCD1234"
    assert session["items"][0]["url"] == opened[0]


def test_force_mirror_only_skips_open_library(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    opened = []

    def refuse(*_args, **_kwargs):
        opened.append(1)
        return None, "should not be called"

    monkeypatch.setattr("paperful.cli_runtime._open_library", refuse)

    def stop(*_args, **_kwargs):
        raise typer.Exit(0)

    monkeypatch.setattr("paperful.run_cmd.run_dry_run_table_and_payload", stop)
    from paperful.run_cmd import run_fetch
    from rich.console import Console

    with pytest.raises(typer.Exit):
        run_fetch(
            Console(file=io.StringIO()),
            cfg,
            collection=[],
            library=True,
            dry_run=True,
            year_from=None,
            year_to=None,
            item_type=[],
            limit=None,
            no_attach=True,
            retry_failed=False,
            try_all=False,
            sources=None,
            preset=None,
            scihub=False,
            relogin=False,
            browser_agent=False,
            upgrade_linked=False,
            want_snapshot_upgrade=False,
            strict_pdf_doi=False,
            handoff=None,
            include_doi_tabs=False,
            downloads_dir=None,
            re_request=False,
            json_out=True,
            item_keys=["ABCD1234"],
            force_mirror_only=True,
        )
    assert opened == []


def test_extension_source_is_secure():
    root = Path(__file__).resolve().parents[1] / "extension" / "firefox"
    forbidden = (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        "wrappedJSObject",
        "exportFunction",
        "cloneInto",
        "unsafe-eval",
        "unsafe-inline",
        "content_security_policy",
        "web_accessible_resources",
        "externally_connectable",
        "content_scripts",
        "https://",
        "http://",
    )
    files = [
        path
        for path in root.rglob("*")
        if path.suffix in {".js", ".html", ".json"} and path.name != "package.json"
    ]
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} contains {token}"
    for name in ("popup.html", "options.html"):
        html = (root / name).read_text(encoding="utf-8")
        assert 'src="' in html
        for tag in html.lower().split("<script"):
            if tag.startswith(">"):
                raise AssertionError(f"{name} has an inline script")
        assert not re.search(r"\son[a-z]+\s*=", html, re.I), name


def test_html_snapshot_saved_when_no_pdf(tmp_path):
    cfg = _cfg(tmp_path)
    folder = _mirror(cfg, "ABCD1234", doi="10.1000/example", pdf=False)
    page = Path(cfg.extension_drop) / "page.html"
    page.write_text(
        "<!DOCTYPE html><html><body><script>alert(1)</script>"
        '<p onclick="hack">Hi</p></body></html>',
        encoding="utf-8",
    )
    result = apply_page(
        cfg,
        {"doi": "10.1000/example", "apply": True, "html_path": str(page)},
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert result["pdf"] == "none"
    assert result["snapshot"] == "saved"
    assert result["reason"] == ""
    saved = (folder / "snapshot.html").read_text(encoding="utf-8")
    assert "Hi" in saved
    assert "<script" not in saved.lower()
    assert "onclick" not in saved.lower()
    record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    names = [row.get("filename") for row in record["attachments"]]
    assert "snapshot.html" in names
    assert record["fetch"]["snapshot"] == "extension"


def test_html_snapshot_skipped_when_pdf_exists(tmp_path):
    cfg = _cfg(tmp_path)
    folder = _mirror(cfg, "ABCD1234", doi="10.1000/example")
    (folder / "Smith - 2020 - A paper.pdf").write_bytes(b"%PDF-1.4\nkept\n")
    page = Path(cfg.extension_drop) / "page.html"
    page.write_text("<!DOCTYPE html><html><body>Hi</body></html>", encoding="utf-8")
    result = apply_page(
        cfg,
        {"doi": "10.1000/example", "apply": True, "html_path": str(page)},
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert result["pdf"] == "kept"
    assert result["snapshot"] == "none"
    assert not (folder / "snapshot.html").exists()


def test_html_outside_drop_dir_refused(tmp_path):
    cfg = _cfg(tmp_path)
    folder = _mirror(cfg, "ABCD1234", doi="10.1000/example", pdf=False)
    result = apply_page(
        cfg,
        {"doi": "10.1000/example", "apply": True, "html_path": "/tmp/evil.html"},
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert result["snapshot"] == "refused"
    assert not (folder / "snapshot.html").exists()


def test_host_hello_unknown_and_install(tmp_path, monkeypatch):
    from paperful.capture_host import handle_message, install_host

    monkeypatch.setattr("paperful.capture_host._open_live", lambda _cfg: None)
    cfg = _cfg(tmp_path)
    hello = handle_message(cfg, {"type": "hello"}, [])
    assert hello["ok"] is True
    assert hello["snapshot"] == "off"
    assert hello["collection"] == "Capture"
    assert hello["tags"] == []
    assert handle_message(cfg, {"type": "nope"}, []) == {"ok": False, "reason": "unknown"}
    session = handle_message(cfg, {"type": "handoff.session"}, [])
    assert session["ok"] is True and session["items"] == []

    monkeypatch.setattr(
        "paperful.capture_host.host_manifest_dir", lambda: tmp_path / "hosts"
    )
    monkeypatch.setattr(
        "paperful.capture_host.host_launcher_path",
        lambda _cfg: tmp_path / "capture" / "paperful-host",
    )
    dest = install_host(cfg, tmp_path / "config.toml")
    manifest = json.loads(Path(dest).read_text(encoding="utf-8"))
    assert manifest["name"] == "paperful"
    assert manifest["type"] == "stdio"
    assert manifest["allowed_extensions"] == ["addon@paperful.local"]
    script = (tmp_path / "capture" / "paperful-host").read_text(encoding="utf-8")
    assert script.startswith("#!/bin/sh\nexec ")
    assert "--stdio" in script
    assert "shell" not in script

    monkeypatch.setattr("paperful.capture_host.host_manifest_dir", lambda: None)
    assert install_host(cfg) == "not installed"


def test_walk_writes_handoff_session(tmp_path):
    from paperful.handoff import walk_missing

    cfg = _cfg(tmp_path)
    row = MissingPdf(
        key="ABCD1234",
        title="Example",
        doi="10.1000/example",
        url="https://publisher.example/paper.pdf",
        hint=HINT_OPENABLE,
        attempts=[],
    )

    def prompt(_text: str) -> str:
        raise AssertionError("prompt")

    walk_missing(
        cfg,
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        {},
        [row],
        downloads_dir=tmp_path,
        prompt=prompt,
        opener=lambda _url: True,
    )
    session = read_session(cfg)
    assert session["schema"] == "paperful.handoff.session.v1"
    assert session["items"][0]["key"] == "ABCD1234"
    assert session["items"][0]["url"].endswith("paper.pdf")


def test_capture_does_not_call_zotero_writes():
    source = (Path(__file__).resolve().parents[1] / "paperful" / "capture.py").read_text()
    assert "create_items" not in source
    assert "attach_pdf_file" not in source


def test_create_fills_authors_year_journal(tmp_path):
    cfg = _cfg(tmp_path)
    result = apply_page(
        cfg,
        {
            "apply": True,
            "allow_unread": True,
            "doi": "10.1000/new",
            "title": "New paper",
            "year": 2021,
            "collection": "Inbox/Capture",
            "page": {
                "authors": ["Ada Lovelace", "Alan Turing"],
                "abstract": "A note.",
                "publication_title": "Example Journal",
                "year": 2021,
            },
        },
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert result["ok"] is True
    assert result["action"] == "create"
    assert result["collection"] == "Inbox/Capture"
    rec = json.loads(next(cfg.out_dir.rglob("record.json")).read_text())
    assert rec["year"] == 2021
    assert rec["publication_title"] == "Example Journal"
    assert rec["abstract"] == "A note."
    assert rec["creators"][0]["lastName"] == "Ada Lovelace"


def test_blank_year_and_note(tmp_path):
    cfg = _cfg(tmp_path)
    folder = _mirror(cfg, "ABCD1234", doi="10.1000/example")
    rec_path = folder / "record.json"
    body = json.loads(rec_path.read_text())
    body["year"] = None
    rec_path.write_text(json.dumps(body))
    result = apply_page(
        cfg,
        {
            "doi": "10.1000/example",
            "apply": True,
            "year": 2019,
            "note": "Keep this copy.",
        },
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert result["note"] == "saved"
    saved = json.loads(rec_path.read_text())
    assert saved["year"] == 2019
    note = (folder / "notes" / "paperful-capture.html").read_text()
    assert "Keep this copy." in note
    assert "paperful.note.v1" in note
    assert "capture" in note


def test_collection_path_rejects_escape(tmp_path):
    cfg = _cfg(tmp_path)
    result = apply_page(
        cfg,
        {
            "apply": True,
            "allow_unread": True,
            "url": "https://example.org/page",
            "title": "Page",
            "collection": "../etc",
        },
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert result["ok"] is True
    assert result["collection"] == "Capture"
    assert (cfg.out_dir / "Capture").is_dir()


def test_stage_copies_from_allowed_parent(tmp_path, monkeypatch):
    from paperful.capture import stage_incoming

    cfg = _cfg(tmp_path)
    incoming_dir = tmp_path / "Downloads"
    incoming_dir.mkdir()
    src = incoming_dir / "paper.pdf"
    src.write_bytes(b"%PDF-1.4\nstaged\n")
    monkeypatch.setattr(
        "paperful.capture.stage_parents", lambda _cfg: [incoming_dir]
    )
    staged = stage_incoming(cfg, str(src))
    assert staged["ok"] is True
    assert staged["staged"] is True
    dest = Path(staged["path"])
    assert dest.parent == Path(cfg.extension_drop).resolve()
    assert dest.read_bytes().startswith(b"%PDF-1.4")


def test_stage_rejects_outside_allowed(tmp_path):
    from paperful.capture import stage_incoming

    cfg = _cfg(tmp_path)
    evil = tmp_path / "secret.pdf"
    evil.write_bytes(b"%PDF-1.4\nevil\n")
    staged = stage_incoming(cfg, str(evil))
    assert staged["ok"] is False
    assert staged["reason"] == "outside_drop"


def test_host_echoes_id_and_stages(tmp_path, monkeypatch):
    from paperful.capture_host import handle_message

    monkeypatch.setattr("paperful.capture_host._open_live", lambda _cfg: None)
    cfg = _cfg(tmp_path)
    hello = handle_message(cfg, {"type": "hello", "id": 7}, [])
    assert hello["id"] == 7
    assert hello["workbench"]
    assert "Capture" in hello["collections"]
    assert hello["tags"] == []
    reply = handle_message(cfg, {"type": "handoff.mark", "id": 8, "keys": ["ABCD"]}, [])
    assert reply["ok"] is True and reply["id"] == 8 and reply["marked"] == 0

    opened = []
    monkeypatch.setattr("paperful.capture._reveal", lambda path: opened.append(path))
    opened_reply = handle_message(
        cfg, {"type": "capture.open", "target": "drop", "id": 9}, []
    )
    assert opened_reply["ok"] is True
    assert opened


def test_mark_session_saved(tmp_path):
    from paperful.capture import mark_session_saved
    from paperful.store import write_json

    cfg = _cfg(tmp_path)
    session = cfg.state_dir / "handoff" / "session.json"
    session.parent.mkdir(parents=True)
    write_json(
        session,
        {
            "schema": "paperful.handoff.session.v1",
            "items": [
                {"key": "ABCD1234", "doi": "10.1000/example", "url": "https://x.example/a"},
                {"key": "KEEPME01", "doi": "10.1000/other", "url": "https://x.example/b"},
            ],
        },
    )
    result = mark_session_saved(cfg, ["ABCD1234"])
    assert result["marked"] == 1
    rows = json.loads(session.read_text())["items"]
    assert rows[0]["saved_at"]
    assert "saved_at" not in rows[1]


def test_windows_install_writes_bat(tmp_path, monkeypatch):
    from paperful import capture_host

    monkeypatch.setattr(capture_host.sys, "platform", "win32")
    monkeypatch.setitem(capture_host.os.environ, "APPDATA", str(tmp_path / "app"))
    monkeypatch.setitem(capture_host.os.environ, "LOCALAPPDATA", str(tmp_path / "local"))
    cfg = _cfg(tmp_path)
    dest = capture_host.install_host(cfg, tmp_path / "config.toml")
    assert dest.endswith("paperful.json")
    script = (tmp_path / "local" / "Paperful" / "capture" / "paperful-host.bat").read_text()
    assert script.startswith("@echo off")
    assert "--stdio" in script
    assert "-u" in script


def test_extension_uses_workbench_tokens():
    root = Path(__file__).resolve().parents[1] / "extension" / "firefox"
    css = (root / "popup.css").read_text(encoding="utf-8")
    assert "--paper: #f7f1e8;" in css
    assert "--accent: #c46a2a;" in css
    assert "[hidden]" in css
    assert "display: none !important" in css
    popup = (root / "popup.html").read_text(encoding="utf-8")
    options = (root / "options.html").read_text(encoding="utf-8")
    assert 'class="brand-word"' in popup and 'class="brand-word"' in options
    assert 'id="review-tabs"' in popup
    assert 'id="open-wanted"' in popup
    assert 'id="tag-input"' in popup
    assert 'list="collection-list"' in popup
    assert "Test connection" in options


def test_list_collection_paths_from_mirror(tmp_path):
    from paperful.capture import list_collection_paths

    cfg = _cfg(tmp_path)
    _mirror(cfg, "ABCD1234")
    (cfg.out_dir / "Inbox").mkdir()
    (cfg.out_dir / "_hidden").mkdir()
    paths = list_collection_paths(cfg)
    assert paths[0] == "Capture"
    assert "Inbox" in paths
    assert all(not name.startswith("_") for name in paths)

    class Coll:
        path = "BBNJ/EIA"

    class Live:
        def collections(self):
            return {"K": Coll()}

    live_paths = list_collection_paths(cfg, live=Live())
    assert "BBNJ/EIA" in live_paths


def test_open_target_item_out_and_invalid(tmp_path):
    from paperful.capture import open_target

    cfg = _cfg(tmp_path)
    folder = _mirror(cfg, "ABCD1234")
    opened: list[Path] = []
    item = open_target(cfg, "item", "ABCD1234", opener=opened.append)
    assert item["ok"] is True
    assert Path(item["path"]) == folder.resolve()
    assert opened[-1] == folder.resolve()
    out = open_target(cfg, "out", opener=opened.append)
    assert Path(out["path"]) == cfg.out_dir.resolve()
    assert open_target(cfg, "item", "NOPEKEY1", opener=opened.append)["reason"] == "missing_item"
    assert open_target(cfg, "wanted", opener=opened.append)["reason"] == "invalid"


def test_host_plan_reads_page_year_and_clips_authors(tmp_path):
    from paperful.capture import prepare
    from paperful.capture_host import handle_message

    cfg = _cfg(tmp_path)
    _mirror(cfg, "ABCD1234", doi="10.1000/example", year=None)
    rec_path = next(cfg.out_dir.rglob("record.json"))
    body = json.loads(rec_path.read_text())
    body["year"] = None
    body["creators"] = []
    rec_path.write_text(json.dumps(body))
    index = [prepare(cfg, opener=_down, run_sync_fn=_quiet)]
    planned = handle_message(
        cfg,
        {
            "type": "capture.plan",
            "id": 11,
            "page": {
                "doi": "10.1000/example",
                "title": "A paper",
                "year": "2018",
            },
        },
        index,
    )
    assert planned["id"] == 11
    assert planned["action"] == "update"
    long = "A" * 500
    extra = [f"Author {i}" for i in range(24)]
    applied = handle_message(
        cfg,
        {
            "type": "capture.apply",
            "id": 12,
            "apply": True,
            "doi": "10.1000/example",
            "year": "2018",
            "page": {"authors": [long, *extra], "year": "2018"},
        },
        index,
    )
    assert applied["ok"] is True and applied["id"] == 12
    saved = json.loads(rec_path.read_text())
    assert saved["year"] == 2018
    assert len(saved["creators"]) == 20
    assert saved["creators"][0]["lastName"] == "A" * 200


def test_stage_already_in_drop_and_html(tmp_path, monkeypatch):
    from paperful.capture import stage_incoming

    cfg = _cfg(tmp_path)
    drop_pdf = Path(cfg.extension_drop) / "kept.pdf"
    drop_pdf.write_bytes(b"%PDF-1.4\nkept\n")
    same = stage_incoming(cfg, str(drop_pdf))
    assert same["ok"] is True and same["staged"] is False
    incoming = tmp_path / "Downloads"
    incoming.mkdir()
    html = incoming / "page.html"
    html.write_text("<html><body>ok</body></html>", encoding="utf-8")
    monkeypatch.setattr("paperful.capture.stage_parents", lambda _cfg: [incoming])
    staged = stage_incoming(cfg, str(html))
    assert staged["ok"] is True and staged["staged"] is True
    assert Path(staged["path"]).parent == Path(cfg.extension_drop).resolve()
    junk = incoming / "notes.txt"
    junk.write_text("nope", encoding="utf-8")
    refused = stage_incoming(cfg, str(junk))
    assert refused["ok"] is False and refused["reason"] == "refused"


def test_id_echo_rejects_bool_and_out_of_range(tmp_path, monkeypatch):
    from paperful.capture_host import handle_message

    monkeypatch.setattr("paperful.capture_host._open_live", lambda _cfg: None)
    cfg = _cfg(tmp_path)
    for req_id in (True, 0, 1_000_000_000, "7"):
        reply = handle_message(cfg, {"type": "hello", "id": req_id}, [])
        assert "id" not in reply


def test_clip_tags_and_hello_suggestions(tmp_path, monkeypatch):
    from paperful.capture import clip_tags, list_tag_names
    from paperful.capture_host import handle_message

    assert clip_tags("BBNJ, bbnj; ocean\nlaw") == ["BBNJ", "ocean", "law"]
    assert clip_tags([{"tag": "keep"}, "keep", ""]) == ["keep"]
    assert len(clip_tags([f"t{i}" for i in range(30)])) == 20

    cfg = _cfg(tmp_path)
    rec_path = _mirror(cfg, "ABCD1234") / "record.json"
    body = json.loads(rec_path.read_text())
    body["tags"] = [{"tag": "mirror-tag"}]
    rec_path.write_text(json.dumps(body))
    assert "mirror-tag" in list_tag_names(cfg)

    class Live:
        def get(self, path, **params):
            assert path == "/tags"
            return _Resp([{"tag": "live-tag"}, {"tag": "mirror-tag"}])

        def collections(self):
            return {}

    names = list_tag_names(cfg, live=Live())
    assert names == ["live-tag", "mirror-tag"]
    monkeypatch.setattr("paperful.capture_host._open_live", lambda _cfg: Live())
    hello = handle_message(cfg, {"type": "hello"}, [])
    assert "live-tag" in hello["tags"]
    assert "mirror-tag" in hello["tags"]


def test_suggest_tags_uses_openalex(tmp_path, monkeypatch):
    from paperful.capture import suggest_tag_names

    cfg = _cfg(tmp_path)
    cfg.email = "test@example.org"

    class Client:
        def work_by_doi(self, doi):
            assert doi == "10.1000/example"
            return {
                "keywords": [
                    {"display_name": "Marine Policy", "score": 0.9, "id": "https://openalex.org/keywords/marine-policy"},
                    {"display_name": "Law of the Sea", "score": 0.5, "id": "https://openalex.org/keywords/law-of-the-sea"},
                ],
                "study_designs": [
                    {"id": "https://openalex.org/study-designs/literature-review", "display_name": "Literature review"},
                ],
            }

        def search_keywords(self, query, limit=5):
            assert query == "ocean"
            return [{"display_name": "Ocean governance", "id": "https://openalex.org/keywords/ocean-governance"}]

    monkeypatch.setattr("paperful.capture._openalex_client_for_capture", lambda _cfg: Client())
    hints = suggest_tag_names(cfg, doi="10.1000/example")
    assert "Marine Policy" in hints
    assert any("literature" in row.lower() for row in hints)
    typed = suggest_tag_names(cfg, query="ocean", doi="10.1000/example")
    assert "Ocean governance" in typed

    from paperful.capture_host import handle_message

    monkeypatch.setattr("paperful.capture_host._open_live", lambda _cfg: None)
    reply = handle_message(
        cfg,
        {"type": "capture.tag_suggest", "id": 3, "query": "ocean", "doi": "10.1000/example"},
        [],
    )
    assert reply["id"] == 3
    assert "Ocean governance" in reply["tags"]


def test_apply_merges_tags(tmp_path):
    cfg = _cfg(tmp_path)
    created = apply_page(
        cfg,
        {
            "apply": True,
            "allow_unread": True,
            "doi": "10.1000/tagged",
            "title": "Tagged",
            "tags": ["BBNJ", "bbnj", "ocean"],
        },
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert created["ok"] is True
    assert created["tags"] == ["BBNJ", "ocean"]
    rec_path = next(cfg.out_dir.rglob("record.json"))
    rec = json.loads(rec_path.read_text())
    assert rec["tags"] == [{"tag": "BBNJ"}, {"tag": "ocean"}]
    updated = apply_page(
        cfg,
        {"apply": True, "doi": "10.1000/tagged", "tags": ["law", "BBNJ"]},
        opener=_down,
        run_sync_fn=_quiet,
    )
    assert updated["ok"] is True
    saved = json.loads(rec_path.read_text())
    assert saved["tags"] == [{"tag": "BBNJ"}, {"tag": "ocean"}, {"tag": "law"}]


def test_mark_session_saved_skips_empty_write(tmp_path):
    from paperful.capture import mark_session_saved

    cfg = _cfg(tmp_path)
    session = cfg.state_dir / "handoff" / "session.json"
    result = mark_session_saved(cfg, [])
    assert result["marked"] == 0
    assert not session.exists()
