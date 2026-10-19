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

    cfg = _cfg(tmp_path)
    hello = handle_message(cfg, {"type": "hello"}, [])
    assert hello["ok"] is True
    assert hello["snapshot"] == "off"
    assert hello["collection"] == "Capture"
    assert handle_message(cfg, {"type": "nope"}, []) == {"ok": False, "reason": "unknown"}
    session = handle_message(cfg, {"type": "handoff.session"}, [])
    assert session["ok"] is True and session["items"] == []

    monkeypatch.setattr(
        "paperful.capture_host.host_manifest_dir", lambda: tmp_path / "hosts"
    )
    dest = install_host(cfg, tmp_path / "config.toml")
    manifest = json.loads(Path(dest).read_text(encoding="utf-8"))
    assert manifest["name"] == "paperful"
    assert manifest["type"] == "stdio"
    assert manifest["allowed_extensions"] == ["addon@paperful.local"]
    script = (cfg.state_dir / "capture" / "paperful-host").read_text(encoding="utf-8")
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
