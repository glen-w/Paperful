"""Summarize / synthesize GUI paths."""

from __future__ import annotations

import time

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available
from paperful.ui import commands, jobs
from paperful.ui.pages import safe_child


def test_safe_child_rejects_traversal(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.summaries_dir.mkdir(parents=True)
    assert safe_child(cfg.summaries_dir, "../evil.html") is None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_item_summary_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.summaries_dir.mkdir(parents=True)
    (cfg.summaries_dir / "K1.html").write_text("<p>hi</p>", encoding="utf-8")
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    client = TestClient(create_app(cfg))
    res = client.get("/item/K1/summary")
    assert res.status_code == 200
    assert "hi" in res.text
    assert client.get("/item/../x/summary").status_code == 404


def test_summarize_item_passes_keys(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    seen: list[list[str] | None] = []

    def fake_summarize(cfg, cmd_id, **kwargs):
        seen.append(kwargs.get("item_keys"))

    jobs.summarize_fn = fake_summarize
    commands.enqueue(
        cfg,
        "summarize_item",
        lambda cid: jobs.summarize(
            cfg,
            cid,
            collection="ocean",
            year_from=None,
            year_to=None,
            limit=None,
            max_new=None,
            dest="disk",
            order="library",
            force=False,
            item_keys=["K9"],
        ),
    )
    import time

    deadline = time.time() + 2
    while time.time() < deadline:
        if seen:
            break
        time.sleep(0.02)
    assert seen == [["K9"]]
    jobs.summarize_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_briefs_summarize_enqueues(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    import paperful.ui.app as ui_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.llm_enabled = True
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ui_app, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    monkeypatch.setattr(ui_app, "collections_tree", lambda _c: {"ok": True, "collections": []})
    seen: list[dict] = []

    def fake(cfg, cmd_id, **kw):
        seen.append(kw)
        cfg.summaries_dir.mkdir(parents=True, exist_ok=True)
        (cfg.summaries_dir / "ITEMKEY1.html").write_text("<p>summary</p>", encoding="utf-8")
        return {
            "summarized": 1,
            "failed": 0,
            "skipped": 0,
            "not_reached": 0,
            "dest": kw["dest"],
            "scope": kw["collection"] or "library",
            "queued": 1,
        }

    jobs.summarize_fn = fake
    try:
        client = TestClient(create_app(cfg))
        client.cookies.set("pf_advanced", "1")
        client.cookies.set("pf_collection", "ocean/BBNJ")
        page = client.get("/briefs")
        assert page.status_code == 200
        assert 'action="/briefs/summarize"' in page.text
        res = client.post(
            "/briefs/summarize",
            data={"dest": "disk", "order": "newest", "limit": "5"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        cmd_id = (res.headers.get("location") or "").split("run=")[1].split("&")[0]
        rec: dict = {}
        deadline = time.time() + 3
        while time.time() < deadline:
            rec = client.get(f"/v1/runs/{cmd_id}").json()
            if rec.get("status") in {"done", "failed"}:
                break
            time.sleep(0.02)
        assert rec.get("status") == "done"
        assert seen[0]["order"] == "newest"
        assert seen[0]["limit"] == 5
        done = client.get("/briefs")
        assert "1 summarized" in done.text
        html = client.get("/briefs/summary/ITEMKEY1")
        assert html.status_code == 200
        assert 'src="/item/ITEMKEY1/summary"' in html.text
        assert 'target="_blank"' not in html.text
        assert "wb-nav" in html.text
    finally:
        jobs.summarize_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_briefs_lists_cite_and_opens_in_gui(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    import paperful.ui.app as ui_app
    from paperful.mirror import forget_index
    from paperful.notehtml import wrap
    from paperful.store import record_path, write_json

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.summaries_dir.mkdir(parents=True)
    cfg.llm_enabled = True
    (cfg.summaries_dir / "KEY1.html").write_text(
        wrap("<p>body</p>", note_type="summary", verb="summarize", model="qwen2.5"),
        encoding="utf-8",
    )
    folder = cfg.out_dir / "BBNJ" / "Smith - 2021 - Area-based -- KEY1"
    folder.mkdir(parents=True)
    write_json(
        record_path(folder),
        {
            "item_key": "KEY1",
            "title": "Area-based management",
            "year": 2021,
            "creators": [{"creatorType": "author", "lastName": "Smith"}],
        },
    )
    forget_index(cfg.out_dir)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ui_app, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    monkeypatch.setattr(ui_app, "collections_tree", lambda _c: {"ok": True, "collections": []})
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_advanced", "1")
    page = client.get("/briefs")
    assert page.status_code == 200
    assert "Smith (2021)" in page.text
    assert "qwen2.5" in page.text
    assert 'href="/briefs/summary/KEY1"' in page.text
    assert 'target="_blank"' not in page.text
    assert "<details>" in page.text
    assert "Recent summaries (1)" in page.text
    assert "<summary>" in page.text
    view = client.get("/briefs/summary/KEY1")
    assert view.status_code == 200
    assert "wb-nav" in view.text
    assert 'src="/item/KEY1/summary"' in view.text
    assert "qwen2.5" in view.text
    raw = client.get("/item/KEY1/summary")
    assert raw.status_code == 200
    assert "body" in raw.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_briefs_requires_llm(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    import paperful.ui.app as ui_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.llm_enabled = False
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ui_app, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    client = TestClient(create_app(cfg))
    page = client.get("/briefs")
    assert 'action="/briefs/summarize"' not in page.text
    assert "[llm]" in page.text
    off = client.post("/briefs/summarize", data={"dest": "disk"}, follow_redirects=False)
    assert off.status_code == 303
    assert "error=llm" in (off.headers.get("location") or "")
    assert commands.list_commands(cfg) == []


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_briefs_synthesize_dry_run(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    import paperful.ui.app as ui_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.llm_enabled = True
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ui_app, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    seen: list[bool] = []

    def fake(cfg, cmd_id, **kw):
        seen.append(kw["dry_run"])
        return {
            "dry_run": True,
            "slug": "ocean-bbnj",
            "sources_disk": 2,
            "sources_note": 0,
            "missing": 1,
            "chunks": 1,
        }

    jobs.synthesize_fn = fake
    try:
        client = TestClient(create_app(cfg))
        res = client.post(
            "/briefs/synthesize",
            data={"dry_run": "1", "dest": "disk"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        cmd_id = (res.headers.get("location") or "").split("run=")[1].split("&")[0]
        deadline = time.time() + 3
        while time.time() < deadline:
            rec = client.get(f"/v1/runs/{cmd_id}").json()
            if rec.get("status") in {"done", "failed"}:
                break
            time.sleep(0.02)
        assert rec.get("status") == "done"
        assert seen == [True]
        page = client.get("/briefs")
        assert "ocean-bbnj" in page.text
        assert "Dry-run" in page.text
    finally:
        jobs.synthesize_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_briefs_write_report_defaults_to_disk_without_collection(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    import paperful.ui.app as ui_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.llm_enabled = True
    cfg.synthesize_dest = "both"
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ui_app, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    monkeypatch.setattr(ui_app, "collections_tree", lambda _c: {"ok": True, "collections": []})
    seen: list[dict] = []

    def fake(cfg, cmd_id, **kw):
        seen.append(kw)
        return {
            "dry_run": False,
            "slug": "library",
            "sources_disk": 3,
            "sources_note": 0,
            "missing": 0,
            "chunks": 2,
        }

    jobs.synthesize_fn = fake
    try:
        client = TestClient(create_app(cfg))
        blank = client.get("/briefs")
        assert blank.status_code == 200
        assert 'option value="disk" selected' in blank.text or 'value="disk" selected' in blank.text
        res = client.post(
            "/briefs/synthesize",
            data={"dry_run": "0", "limit": "40", "year_from": "2020", "year_to": "2026"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        loc = res.headers.get("location") or ""
        assert "run=" in loc
        assert "error=" not in loc
        cmd_id = loc.split("run=")[1].split("&")[0]
        deadline = time.time() + 3
        rec: dict = {}
        while time.time() < deadline:
            rec = client.get(f"/v1/runs/{cmd_id}").json()
            if rec.get("status") in {"done", "failed"}:
                break
            time.sleep(0.02)
        assert rec.get("status") == "done"
        assert seen[0]["dry_run"] is False
        assert seen[0]["dest"] == "disk"
        assert seen[0]["limit"] == 40
        done = client.get("/briefs")
        assert 'href="/briefs/report/library"' in done.text
        assert 'value="40"' in done.text
        assert 'value="2020"' in done.text
        assert 'value="2026"' in done.text
    finally:
        jobs.synthesize_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_briefs_write_report_keeps_fields_when_collection_required(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    import paperful.ui.app as ui_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.llm_enabled = True
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ui_app, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    monkeypatch.setattr(ui_app, "collections_tree", lambda _c: {"ok": True, "collections": []})
    client = TestClient(create_app(cfg))
    res = client.post(
        "/briefs/synthesize",
        data={
            "dry_run": "0",
            "dest": "both",
            "limit": "40",
            "year_from": "2020",
            "year_to": "2026",
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    loc = res.headers.get("location") or ""
    assert "error=collection" in loc
    page = client.get(loc)
    assert page.status_code == 200
    assert "Pick a collection in the chip, or set destination to disk." in page.text
    assert page.text.count("Pick a collection in the chip, or set destination to disk.") >= 2
    assert 'value="40"' in page.text
    assert 'value="2020"' in page.text
    assert 'value="2026"' in page.text
    assert 'option value="both" selected' in page.text or 'value="both" selected' in page.text
    assert commands.list_commands(cfg) == []


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_briefs_write_report_shows_running_status(tmp_path, monkeypatch):
    import threading

    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    import paperful.ui.app as ui_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.llm_enabled = True
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ui_app, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    monkeypatch.setattr(ui_app, "collections_tree", lambda _c: {"ok": True, "collections": []})
    gate = threading.Event()

    def fake(cfg, cmd_id, **kw):
        gate.wait(timeout=2)
        return {"dry_run": False, "slug": "library", "sources_disk": 1, "sources_note": 0, "missing": 0, "chunks": 1}

    jobs.synthesize_fn = fake
    try:
        client = TestClient(create_app(cfg))
        res = client.post(
            "/briefs/synthesize",
            data={"dry_run": "0", "dest": "disk"},
            follow_redirects=False,
        )
        loc = res.headers.get("location") or ""
        page = client.get(loc)
        assert page.status_code == 200
        assert "Write report" in page.text
        assert "queued" in page.text or "running" in page.text
        assert "cmd-status" in page.text
        gate.set()
        cmd_id = loc.split("run=")[1].split("&")[0]
        deadline = time.time() + 3
        while time.time() < deadline:
            rec = client.get(f"/v1/runs/{cmd_id}").json()
            if rec.get("status") in {"done", "failed"}:
                break
            time.sleep(0.02)
        assert rec.get("status") == "done"
    finally:
        gate.set()
        jobs.synthesize_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_briefs_write_report_explains_missing_summaries(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    import paperful.ui.app as ui_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.llm_enabled = True
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ui_app, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    monkeypatch.setattr(ui_app, "collections_tree", lambda _c: {"ok": True, "collections": []})

    def fake(cfg, cmd_id, **kw):
        return {
            "dry_run": False,
            "slug": "library",
            "sources_disk": 0,
            "sources_note": 0,
            "missing": 4,
            "skipped": "no_summaries",
        }

    jobs.synthesize_fn = fake
    try:
        client = TestClient(create_app(cfg))
        res = client.post(
            "/briefs/synthesize",
            data={"dry_run": "0", "dest": "disk"},
            follow_redirects=False,
        )
        cmd_id = (res.headers.get("location") or "").split("run=")[1].split("&")[0]
        deadline = time.time() + 3
        while time.time() < deadline:
            rec = client.get(f"/v1/runs/{cmd_id}").json()
            if rec.get("status") in {"done", "failed"}:
                break
            time.sleep(0.02)
        page = client.get("/briefs")
        assert "No summaries in this scope. Summarize first, then write the report." in page.text
    finally:
        jobs.synthesize_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_drawer_shows_iframe_when_file(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.store import Manifest, Record, STATUS_OK

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.summaries_dir.mkdir(parents=True)
    (cfg.summaries_dir / "K1.html").write_text("<p>drawer</p>", encoding="utf-8")
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )

    class _Item:
        key = "K1"
        title = "Paper"
        doi = "10.1/a"
        has_pdf = True
        year = 2024
        arxiv_id = None
        url = ""

    manifest = Manifest(cfg.manifest_path)
    manifest.write(
        Record(
            itemKey="K1",
            status=STATUS_OK,
            doi="10.1/a",
            pdf_doi="10.1/a",
            source="unpaywall",
            path="k1.pdf",
        )
    )
    monkeypatch.setattr(
        jobs, "_load_scope_items", lambda _c, _col: ([_Item()], manifest)
    )
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_collection", "ocean")
    page = client.get("/wanted?tab=have")
    assert page.status_code == 200
    assert 'data-src="/item/K1/summary"' in page.text
    assert ' src="/item/K1/summary"' not in page.text
    assert "summary-frame" in page.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_wanted_summarize_enqueues_item(tmp_path, monkeypatch):
    import threading

    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.llm_enabled = True
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    seen: list[list[str] | None] = []
    gate = threading.Event()

    def fake(cfg, cmd_id, **kw):
        gate.wait(timeout=2)
        seen.append(kw.get("item_keys"))
        return {"summarized": 1}

    jobs.summarize_fn = fake
    try:
        client = TestClient(create_app(cfg))
        res = client.post(
            "/wanted/summarize",
            data={"key": "K1", "dest": "disk"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        loc = res.headers.get("location") or ""
        assert "run=" in loc
        page = client.get(loc)
        assert "queued" in page.text or "running" in page.text
        assert "cmd-status" in page.text
        assert 'data-poll-run="' in page.text
        gate.set()
        cmd_id = loc.split("run=")[1].split("&")[0]
        deadline = time.time() + 3
        rec: dict = {}
        while time.time() < deadline:
            rec = client.get(f"/v1/runs/{cmd_id}").json()
            if rec.get("status") in {"done", "failed"}:
                break
            time.sleep(0.02)
        assert rec.get("status") == "done"
        assert seen == [["K1"]]
    finally:
        gate.set()
        jobs.summarize_fn = None
