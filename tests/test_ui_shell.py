"""Workbench shell pages (wave 1)."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available


@pytest.mark.smoke
@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_root_redirect_and_pages_render(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    doctor = lambda _cfg, probe=False: [
        {"name": "Zotero", "status": "red", "code": "zotero_down", "detail": "down"}
    ]
    monkeypatch.setattr(ops, "doctor_payload", doctor)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", doctor)
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": False, "error": "Zotero is not reachable", "collections": []},
    )
    client = TestClient(create_app(cfg))
    assert client.get("/", follow_redirects=False).status_code == 302
    assert client.get("/", follow_redirects=False).headers["location"] == "/wanted"
    for path in ("/wanted", "/discover", "/ask", "/library", "/activity", "/system"):
        res = client.get(path)
        assert res.status_code == 200
        assert "Paperful" in res.text
        assert 'class="brand-logo"' in res.text
        assert 'class="brand-mark"' in res.text
        assert 'src="/static/icon.png"' in res.text
        assert "Source+Sans+3" in res.text
    logo = client.get("/static/icon.png")
    assert logo.status_code == 200
    assert logo.headers["content-type"].startswith("image/")
    wanted = client.get("/wanted")
    assert wanted.status_code == 200
    nav = wanted.text
    assert nav.index('href="/wanted"') < nav.index('href="/discover"')
    assert nav.index('href="/discover"') < nav.index('href="/ask"')
    assert nav.index('href="/ask"') < nav.index('href="/library"')
    assert "Zotero offline" in wanted.text
    assert "Start Zotero" in wanted.text or "Pick a collection" in wanted.text
    assert 'formaction="/wanted/attach"' in wanted.text
    assert "/repair" not in wanted.text
    assert "/critique" not in wanted.text
    assert 'href="/index"' not in wanted.text
    client.cookies.set("pf_advanced", "1")
    res = client.get("/wanted")
    assert "/repair" in res.text
    assert "/critique" in res.text
    assert "/v1/ask" not in res.text
    assert client.get("/repair").status_code == 200
    critique = client.get("/critique")
    assert critique.status_code == 200
    assert "drop-zone" in critique.text
    assert 'name="item_key"' in critique.text
    assert 'name="file"' in critique.text
    assert 'name="ai_model"' in critique.text
    assert client.get("/mirror").status_code == 200
    assert client.get("/index").status_code == 200
    assert client.get("/briefs").status_code == 200
    assert "/briefs" in res.text
    wanted_adv = client.get("/wanted")
    assert "Recover" in wanted_adv.text
    assert "Handoff" in wanted_adv.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_discover_grow_shows_refs_gap(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr(ops, "doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_advanced", "1")
    grow = client.get("/discover?tab=grow")
    assert grow.status_code == 200
    assert "Refs gap" in grow.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_html_pages_do_not_block_on_doctor(tmp_path, monkeypatch):
    """Health chip must not run full doctor on ordinary HTML routes (GUI hang)."""
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    calls = {"n": 0}

    def counting_doctor(_cfg, probe=False):
        calls["n"] += 1
        return [
            {"name": "Zotero", "status": "red", "code": "zotero_down", "detail": "down"}
        ]

    # mount_ui binds doctor_payload at import time — patch the UI module name.
    monkeypatch.setattr("paperful.ui.app.doctor_payload", counting_doctor)
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )
    client = TestClient(create_app(cfg))

    wanted = client.get("/wanted")
    assert wanted.status_code == 200
    assert "health-amber" in wanted.text
    assert calls["n"] == 0

    settings = client.get("/settings")
    assert settings.status_code == 200
    assert calls["n"] == 0

    system = client.get("/system")
    assert system.status_code == 200
    assert calls["n"] == 1
    assert "health-red" in system.text

    wanted2 = client.get("/wanted")
    assert wanted2.status_code == 200
    assert "health-red" in wanted2.text
    assert 'aria-label="System health: red · Zotero offline' in wanted2.text
    assert calls["n"] == 1


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_wanted_miss_surface_icon(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from paperful.store import Manifest
    from paperful.ui import jobs

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )

    class _Item:
        key = "M1"
        title = "No identifier"
        doi = None
        has_pdf = False
        year = None
        arxiv_id = None
        url = ""

    monkeypatch.setattr(
        jobs,
        "_load_scope_items",
        lambda _c, _col: ([_Item()], Manifest(cfg.manifest_path)),
    )
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_collection", "ocean")
    page = client.get("/wanted?tab=missing")
    assert page.status_code == 200
    assert 'class="miss-status miss-status--no_doi"' in page.text
    assert 'aria-label="No DOI or identifier to search"' in page.text
    assert "No DOI or identifier to search" in page.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_wanted_verification_icon_on_held(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from paperful.store import Manifest, Record, STATUS_OK
    from paperful.ui import jobs

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )

    class _Item:
        key = "H1"
        title = "Mismatch"
        doi = "10.1/a"
        has_pdf = True
        year = 2024
        arxiv_id = None
        url = ""

    manifest = Manifest(cfg.manifest_path)
    manifest.write(
        Record(
            itemKey="H1",
            status=STATUS_OK,
            doi="10.1/a",
            pdf_doi="10.9/b",
            source="unpaywall",
            path="h.pdf",
        )
    )
    monkeypatch.setattr(
        jobs,
        "_load_scope_items",
        lambda _c, _col: ([_Item()], manifest),
    )
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_collection", "ocean")
    page = client.get("/wanted?tab=held")
    assert page.status_code == 200
    assert 'class="miss-status miss-status--doi_mismatch"' in page.text
    assert "DOI does not match" in page.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_wanted_ghost_pdf_on_missing_tab(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from paperful.store import Manifest
    from paperful.ui import jobs

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )

    class _Item:
        key = "G1"
        title = "Ghost"
        doi = "10.1/g"
        has_pdf = True
        year = 2024
        arxiv_id = None
        url = ""

    monkeypatch.setattr(
        jobs,
        "_load_scope_items",
        lambda _c, _col: ([_Item()], Manifest(cfg.manifest_path)),
    )
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_collection", "ocean")
    page = client.get("/wanted")
    assert page.status_code == 200
    assert 'href="/wanted?tab=missing"' in page.text
    assert 'class="miss-status miss-status--missing"' in page.text
    assert "No PDF file on disk" in page.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_wanted_items_are_paginated(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from paperful.store import Manifest
    from paperful.ui import jobs

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )

    class _Item:
        def __init__(self, n: int):
            self.key = f"K{n:02d}"
            self.title = f"Paper {n:02d}"
            self.doi = None
            self.has_pdf = False
            self.year = 2000 + n
            self.arxiv_id = None
            self.url = ""

    items = [_Item(n) for n in range(30)]
    monkeypatch.setattr(
        jobs,
        "_load_scope_items",
        lambda _c, _col: (items, Manifest(cfg.manifest_path)),
    )
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_collection", "ocean")
    page = client.get("/wanted?tab=missing&per_page=25")
    assert page.status_code == 200
    assert "Order by" in page.text
    assert "Per page" in page.text
    assert "Filter" in page.text
    assert "1–25" in page.text
    assert "of 30" in page.text
    assert "Paper 00" in page.text
    assert "Paper 24" in page.text
    assert "Paper 25" not in page.text
    assert 'href="/wanted?tab=missing&amp;per_page=25&amp;page=2"' in page.text
    next_page = client.get("/wanted?tab=missing&per_page=25&page=2")
    assert next_page.status_code == 200
    assert "Paper 25" in next_page.text
    assert "Paper 00" not in next_page.text
    newest = client.get("/wanted?tab=missing&per_page=25&order=year_new")
    assert newest.status_code == 200
    body = newest.text
    assert body.index("Paper 29") < body.index("Paper 28")


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_library_nests_collections(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree",
        lambda _cfg: {
            "ok": True,
            "collections": [
                {"path": "AO", "name": "AO", "key": "1", "items": 267, "missing_pdf": 10},
                {
                    "path": "AO/Mini meta studies",
                    "name": "Mini meta studies",
                    "key": "2",
                    "items": 0,
                    "missing_pdf": 0,
                },
                {
                    "path": "AO/Mini meta studies/Coffee",
                    "name": "Coffee",
                    "key": "3",
                    "items": 0,
                    "missing_pdf": 0,
                },
            ],
        },
    )
    client = TestClient(create_app(cfg))
    res = client.get("/library")
    assert res.status_code == 200
    assert "<details" in res.text
    assert 'class="coll-toggle"' in res.text
    assert "<summary" in res.text
    assert 'summary class="coll-head"' not in res.text
    assert "Mini meta studies" in res.text
    assert "Coffee" in res.text
    assert "built-in method items" not in res.text
    assert ">267<" in res.text
    assert 'class="icon-btn"' in res.text
    assert 'aria-label="Set scope"' in res.text
    assert ">Set scope</button>" not in res.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_archive_lists_use_details(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.llm_enabled = True
    cfg.rag_enabled = True
    cfg.reports_dir.mkdir(parents=True)
    (cfg.reports_dir / "ocean-bbnj.html").write_text("<p>r</p>", encoding="utf-8")
    runs = cfg.state_dir / "runs"
    runs.mkdir(parents=True)
    (runs / "20260101T000000Z-lint.json").write_text("{}", encoding="utf-8")
    watch = cfg.state_dir / "snowball" / "watches" / "topic-watch"
    watch.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_advanced", "1")
    briefs = client.get("/briefs")
    assert briefs.status_code == 200
    assert "<summary>Recent reports (1)</summary>" in briefs.text
    repair = client.get("/repair")
    assert repair.status_code == 200
    assert "<summary>Queued files (1)</summary>" in repair.text
    assert "20260101T000000Z-lint.json" in repair.text
    discover = client.get("/discover")
    assert discover.status_code == 200
    assert "<h2>Following</h2>" in discover.text
    assert "topic-watch" in discover.text
    index = client.get("/index")
    assert index.status_code == 200
    assert "<summary>Recent reports (1)</summary>" in index.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_pages_include_beginner_help(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.llm_enabled = True
    cfg.rag_enabled = True
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )
    client = TestClient(create_app(cfg))

    wanted = client.get("/wanted")
    assert wanted.status_code == 200
    assert 'class="page-lede"' in wanted.text
    assert "Missing</strong> means no file yet" in wanted.text
    assert 'class="help-tip"' in wanted.text
    assert "class=\"help-tip-bubble\"" in wanted.text
    assert "Zotero collection currently in scope" in wanted.text
    assert "Leave this off until you know what a control does" in wanted.text

    library = client.get("/library")
    assert library.status_code == 200
    assert "target icon sets the collection chip" in library.text

    discover = client.get("/discover")
    assert discover.status_code == 200
    assert "Nothing is added to Zotero until you Preview apply" in discover.text
    assert "Treat query words as OR" not in discover.text

    activity = client.get("/activity")
    assert "Jobs this workbench has started" in activity.text

    system = client.get("/system")
    assert "Health checks for Zotero" in system.text

    client.cookies.set("pf_advanced", "1")
    wanted_adv = client.get("/wanted")
    assert "Try again on items that already came back empty" in wanted_adv.text
    assert "The file may be a different paper" in wanted_adv.text

    discover_adv = client.get("/discover")
    assert "Treat query words as OR instead of AND" in discover_adv.text

    mirror = client.get("/mirror")
    assert mirror.status_code == 200
    assert "Accept gone (dangerous)" in mirror.text
    assert "different library" in mirror.text
    assert "help-tip--danger" in mirror.text
    assert "lazy: copy a PDF into the mirror" in mirror.text

    index = client.get("/index")
    assert index.status_code == 200
    assert "LLM extract lane" in index.text
    assert "Costs tokens" in index.text
    assert "Ignore cached answered-check rows" in index.text

    ask = client.get("/ask")
    assert ask.status_code == 200
    assert 'class="page-lede"' in ask.text
    assert "Ignore cached answers" in ask.text

    briefs = client.get("/briefs")
    assert "Regenerate even when a summary already exists" in briefs.text

    repair = client.get("/repair")
    assert "Always Preview first" in repair.text
    assert "Title+year merges are off unless you opt in" in repair.text

    settings = client.get("/settings")
    assert "Unpaywall needs a real email" in settings.text


def test_dockerfile_includes_serve_extra():
    from pathlib import Path

    text = Path("Dockerfile").read_text(encoding="utf-8")
    assert "--extra serve" in text
