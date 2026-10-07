"""Workbench shell pages (wave 1)."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available


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
    for path in ("/wanted", "/discover", "/library", "/activity", "/system"):
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
    assert "Zotero offline" in wanted.text
    assert "Start Zotero" in wanted.text or "Pick a collection" in wanted.text
    assert 'formaction="/wanted/attach"' in wanted.text
    assert "/repair" not in wanted.text
    client.cookies.set("pf_advanced", "1")
    res = client.get("/wanted")
    assert "/repair" in res.text
    assert "/v1/ask" not in res.text
    assert client.get("/repair").status_code == 200
    assert client.get("/mirror").status_code == 200
    assert client.get("/index").status_code == 200
    assert client.get("/briefs").status_code == 200
    assert "/briefs" in res.text
    wanted_adv = client.get("/wanted")
    assert "Recover" in wanted_adv.text
    assert "Handoff" in wanted_adv.text
    discover_adv = client.get("/discover")
    assert "Refs gap" in discover_adv.text


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
    assert "Mini meta studies" in res.text
    assert "Coffee" in res.text
    assert "built-in method items" not in res.text
    assert ">267<" in res.text


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
    assert "<summary>Following (1)</summary>" in discover.text
    index = client.get("/index")
    assert index.status_code == 200
    assert "<summary>Recent reports (1)</summary>" in index.text


def test_dockerfile_includes_serve_extra():
    from pathlib import Path

    text = Path("Dockerfile").read_text(encoding="utf-8")
    assert "--extra serve" in text
