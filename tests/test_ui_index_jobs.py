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
        assert 'action="/index/rag-questions"' in page.text
        assert 'action="/index/rag-answered"' in page.text
        assert "prompt_inline" in page.text
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


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_batch_force_and_prompt(tmp_path, monkeypatch):
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
        return {"stamp": "x", "questions": 1, "answered": 1, "skipped": 0, "failed": 0}

    jobs.ask_batch_fn = fake
    try:
        client = TestClient(create_app(cfg))
        res = client.post(
            "/index/ask-batch",
            data={
                "questions": "What is BBNJ?",
                "force": "1",
                "prompt_inline": "Custom batch prompt.",
            },
            follow_redirects=False,
        )
        assert res.status_code == 303
        cmd_id = (res.headers.get("location") or "").split("run=")[1].split("&")[0]
        rec = _wait_done(client, cmd_id)
        assert rec.get("status") == "done"
        assert seen[0]["force"] is True
        assert seen[0]["prompt_text"] == "Custom batch prompt."
    finally:
        jobs.ask_batch_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_rag_questions_scope_and_answered_pack(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    _fresh_index(monkeypatch)

    scope_bad = TestClient(create_app(cfg)).post(
        "/index/rag-questions",
        data={"dry_run": "1"},
        follow_redirects=False,
    )
    assert "error=scope" in (scope_bad.headers.get("location") or "")

    jobs.rag_questions_fn = lambda cfg, cmd_id, **kw: {"items": 2, "questions": 5, "dry_run": True}
    jobs.rag_answered_fn = lambda cfg, cmd_id, **kw: {
        "stamp": "20260101T000000Z",
        "answered": 1,
        "partial": 0,
        "not_found": 0,
        "failed": 0,
        "questions": 1,
    }
    try:
        client = TestClient(create_app(cfg))
        client.cookies.set("pf_collection", "ocean/BBNJ")
        ok = client.post(
            "/index/rag-questions",
            data={"dry_run": "1"},
            follow_redirects=False,
        )
        assert ok.status_code == 303
        stamp_dir = cfg.state_dir / "rq-answered" / "20260101T000000Z"
        stamp_dir.mkdir(parents=True)
        (stamp_dir / "pack.md").write_text("# report\n", encoding="utf-8")
        pack = client.get("/index/answered/20260101T000000Z")
        assert pack.status_code == 200
        assert b"# report" in pack.content
        assert client.get("/index/answered/../secrets").status_code == 404
    finally:
        jobs.rag_questions_fn = None
        jobs.rag_answered_fn = None


def test_ask_batch_job_forwards_prompt_path(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    seen: dict = {}

    class Pack:
        stamp = "20260101T000000Z"
        questions = 1
        answered = 1
        skipped = 0
        failed = 0
        focus = "default"
        model = "m"

    def fake_run_batch(cfg, questions, **kw):
        seen.update(kw)
        return Pack()

    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_ask", lambda cfg: None)
    monkeypatch.setattr("paperful.llm.preflight.validate_embedder", lambda cfg: object())
    monkeypatch.setattr("paperful.llm.get_client", lambda cfg: object())
    monkeypatch.setattr("paperful.rag.index.Index.open", lambda cfg: object())
    monkeypatch.setattr("paperful.rag.ledger.Ledger", lambda *a, **k: object())
    monkeypatch.setattr(
        "paperful.rag.retrieve.scope_keys", lambda *a, **k: {"ABCD1234"}
    )
    monkeypatch.setattr("paperful.rag.batch.run_batch", fake_run_batch)
    monkeypatch.setattr(
        "paperful.rag.batch.write_pack",
        lambda cfg, pack: cfg.state_dir / "ask-batch" / pack.stamp,
    )
    (cfg.state_dir / "ask-batch" / "20260101T000000Z").mkdir(parents=True)
    (cfg.state_dir / "ask-batch" / "20260101T000000Z" / "answers.md").write_text(
        "# a\n", encoding="utf-8"
    )
    from paperful.ui import commands

    cmd_id = "cmdaskbatch01"
    commands.write_command(
        cfg, {"id": cmd_id, "verb": "ask_batch", "status": "running"}
    )
    jobs.ask_batch(
        cfg,
        cmd_id,
        questions=["What is BBNJ?"],
        collection="ocean/BBNJ",
        year_from=None,
        year_to=None,
        focus="gaps",
        dest="disk",
        apply=False,
        prompt_path="/tmp/custom-prompt.md",
        force=True,
    )
    assert seen.get("prompt_path") == "/tmp/custom-prompt.md"
    assert seen.get("force") is True
    assert seen.get("focus") == "gaps"


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_rag_answered_enqueues_from_text(tmp_path, monkeypatch):
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
        stamp = "20260102T000000Z"
        folder = cfg.state_dir / "rq-answered" / stamp
        folder.mkdir(parents=True)
        (folder / "pack.md").write_text("# ok\n", encoding="utf-8")
        return {
            "stamp": stamp,
            "questions": 1,
            "answered": 1,
            "partial": 0,
            "not_found": 0,
            "failed": 0,
        }

    jobs.rag_answered_fn = fake
    try:
        client = TestClient(create_app(cfg))
        res = client.post(
            "/index/rag-answered",
            data={
                "question_mode": "text",
                "answered_questions": "Is EIA required?\n",
                "force": "1",
            },
            follow_redirects=False,
        )
        assert res.status_code == 303
        cmd_id = (res.headers.get("location") or "").split("run=")[1].split("&")[0]
        rec = _wait_done(client, cmd_id)
        assert rec.get("status") == "done"
        assert seen[0]["force"] is True
        assert seen[0]["questions"][0][0] == "Is EIA required?"
    finally:
        jobs.rag_answered_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_synthesize_enqueues(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    seen: list[bool] = []

    def fake(cfg, cmd_id, **kw):
        seen.append(kw["dry_run"])
        return {"dry_run": True, "slug": "lib", "sources_disk": 1, "sources_note": 0, "missing": 0, "chunks": 1}

    jobs.synthesize_fn = fake
    try:
        client = TestClient(create_app(cfg))
        page = client.get("/index")
        assert 'action="/index/synthesize"' in page.text
        res = client.post(
            "/index/synthesize",
            data={"dry_run": "1", "dest": "disk"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        cmd_id = (res.headers.get("location") or "").split("run=")[1].split("&")[0]
        rec = _wait_done(client, cmd_id)
        assert rec.get("status") == "done"
        assert seen == [True]
    finally:
        jobs.synthesize_fn = None
