"""Index ingest, search, and batch Ask on the workbench."""

from __future__ import annotations

import time

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available
from paperful.ui import commands, jobs


def _ops(monkeypatch) -> None:
    import paperful.agent_ops as ops
    import paperful.ui.app as ui_app

    def payload(_cfg, probe=False):
        return [{"name": "x", "status": "green", "code": "", "detail": ""}]

    monkeypatch.setattr(ops, "doctor_payload", payload)
    monkeypatch.setattr(ui_app, "doctor_payload", payload)
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )
    monkeypatch.setattr(ui_app, "collections_tree", lambda _cfg: {"ok": True, "collections": []})


def _fresh_index(monkeypatch) -> None:
    monkeypatch.setattr(
        "paperful.rag.status.index_status",
        lambda _cfg, entries=None: {
            "exists": True,
            "items": 4,
            "items_pdf": 3,
            "chunks": 10,
            "problem": "",
        },
    )


def _wait_done(client, cmd_id: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        last = client.get(f"/v1/runs/{cmd_id}").json()
        if last.get("status") in {"done", "failed"}:
            return last
        time.sleep(0.02)
    return last


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_ingest_preview_enqueues(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    _ops(monkeypatch)
    _fresh_index(monkeypatch)
    seen: list[dict] = []

    def fake(cfg, cmd_id, **kw):
        seen.append(kw)
        return {"dry_run": kw["dry_run"], "scope": kw["collection"] or "library", "summary": {"pdf": 2, "ocr": 0, "abstract": 0, "unchanged": 1, "failed": 0, "chunks": 8}}

    jobs.rag_ingest_fn = fake
    try:
        client = TestClient(create_app(cfg))
        client.cookies.set("pf_collection", "ocean/BBNJ")
        page = client.get("/index")
        assert 'action="/index/ingest"' in page.text
        res = client.post(
            "/index/ingest",
            data={"dry_run": "1", "limit": "10"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        loc = res.headers.get("location") or ""
        assert "run=" in loc
        cmd_id = loc.split("run=")[1].split("&")[0]
        rec = _wait_done(client, cmd_id)
        assert rec.get("status") == "done"
        assert seen[0]["dry_run"] is True
        assert seen[0]["collection"] == "ocean/BBNJ"
        assert seen[0]["limit"] == 10
        done = client.get("/index")
        assert "Would index" in done.text
        assert "pdf 2" in done.text
    finally:
        jobs.rag_ingest_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_ingest_disabled_without_rag(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = False
    _ops(monkeypatch)
    client = TestClient(create_app(cfg))
    res = client.post("/index/ingest", data={"dry_run": "0"}, follow_redirects=False)
    assert res.status_code == 303
    assert "error=rag" in (res.headers.get("location") or "")
    assert commands.list_commands(cfg) == []


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_search_renders_hits(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    _ops(monkeypatch)
    _fresh_index(monkeypatch)

    class Hit:
        score = 0.91
        item_key = "ABCD1234"
        title = "Paper"
        pages = "p. 3"
        year = 2020
        text = "impact assessment thresholds"

    monkeypatch.setattr("paperful.rag.index.Index.open", lambda *a, **k: object())
    monkeypatch.setattr("paperful.rag.ledger.Ledger", lambda *a, **k: object())
    monkeypatch.setattr("paperful.rag.retrieve.scope_keys", lambda *a, **k: None)
    monkeypatch.setattr("paperful.rag.retrieve.search", lambda *a, **k: [Hit()])
    monkeypatch.setattr("paperful.llm.preflight.validate_embedder", lambda cfg: object())

    client = TestClient(create_app(cfg))
    res = client.post(
        "/index/search",
        data={"q": "impact assessment"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    loc = res.headers.get("location") or ""
    assert "q=" in loc
    page = client.get(loc)
    assert page.status_code == 200
    assert "ABCD1234" in page.text
    assert "impact assessment thresholds" in page.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_batch_ask_enqueues(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    _fresh_index(monkeypatch)
    seen: list[dict] = []

    def fake(cfg, cmd_id, **kw):
        seen.append(kw)
        stamp = "20260101T000000Z"
        folder = cfg.state_dir / "ask-batch" / stamp
        folder.mkdir(parents=True)
        (folder / "answers.md").write_text("# answers\n", encoding="utf-8")
        (folder / "pack.json").write_text(
            '{"questions": 2, "answered": 2, "failed": 0}', encoding="utf-8"
        )
        return {
            "stamp": stamp,
            "pack": str(folder),
            "questions": 2,
            "answered": 2,
            "skipped": 0,
            "failed": 0,
            "focus": kw.get("focus") or "default",
            "note": False,
        }

    jobs.ask_batch_fn = fake
    try:
        client = TestClient(create_app(cfg))
        client.cookies.set("pf_collection", "ocean/BBNJ")
        page = client.get("/index")
        assert 'action="/index/ask-batch"' in page.text
        res = client.post(
            "/index/ask-batch",
            data={"questions": "What is BBNJ?\nWhat is EIA?", "focus": "gaps"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        cmd_id = (res.headers.get("location") or "").split("run=")[1].split("&")[0]
        rec = _wait_done(client, cmd_id)
        assert rec.get("status") == "done"
        assert seen[0]["questions"] == ["What is BBNJ?", "What is EIA?"]
        assert seen[0]["focus"] == "gaps"
        pack = client.get("/index/batch/20260101T000000Z")
        assert pack.status_code == 200
        assert b"# answers" in pack.content
        assert client.get("/index/batch/../secrets").status_code == 404
    finally:
        jobs.ask_batch_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_batch_empty_and_disabled(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    client = TestClient(create_app(cfg))
    empty = client.post("/index/ask-batch", data={"questions": "  \n# hi"}, follow_redirects=False)
    assert empty.status_code == 303
    assert "error=questions" in (empty.headers.get("location") or "")
    cfg.llm_enabled = False
    off = client.post(
        "/index/ask-batch",
        data={"questions": "What is BBNJ?"},
        follow_redirects=False,
    )
    assert "error=disabled" in (off.headers.get("location") or "")
    assert commands.list_commands(cfg) == []
