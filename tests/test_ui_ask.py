"""Interactive Ask page (opt-in RAG + LLM)."""

from __future__ import annotations

import time

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available
from paperful.ui import commands, jobs
from paperful.rag.ask_turn import run_ask_turn
from paperful.rag.thread import Thread, save_thread


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
            "items_abstract": 1,
            "chunks": 10,
            "items_ocr_pending": 0,
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
def test_index_gate_requires_both_rag_and_llm(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = False
    _ops(monkeypatch)
    _fresh_index(monkeypatch)
    client = TestClient(create_app(cfg))
    res = client.get("/ask")
    assert res.status_code == 200
    assert 'action="/ask"' not in res.text
    assert 'action="/index/ask"' not in res.text
    assert "[llm]" in res.text


def test_run_ask_turn_rejects_empty_question(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    with pytest.raises(ValueError, match="question"):
        run_ask_turn(
            cfg,
            question="  ",
            thread_id=None,
            collection="",
            year_from=None,
            year_to=None,
            focus=None,
        )


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_ask_enqueues_and_writes_thread(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    _fresh_index(monkeypatch)

    def fake(cfg, cmd_id, **kw):
        tid = kw.get("thread_id") or "deadbeefcafe"
        save_thread(
            cfg.state_dir,
            Thread(
                thread_id=tid,
                turns=[
                    {"role": "user", "content": kw["question"]},
                    {"role": "assistant", "content": "Answer [S1]."},
                ],
                last_query=kw["question"],
            ),
        )
        return {
            "thread_id": tid,
            "question": kw["question"],
            "retrieve_as": kw["question"],
            "answer": "Answer [S1].",
            "cited": ["S1"],
            "sources": [
                {
                    "marker": "S1",
                    "itemKey": "ABCD1234",
                    "title": "Paper",
                    "pages": ["1"],
                    "citation": "Doe (2020)",
                }
            ],
            "focus": kw.get("focus") or "default",
        }

    jobs.ask_turn_fn = fake
    try:
        client = TestClient(create_app(cfg))
        client.cookies.set("pf_collection", "ocean/BBNJ")
        gated = client.get("/ask")
        assert 'action="/ask"' in gated.text
        res = client.post(
            "/ask",
            data={"question": "What is BBNJ?", "focus": "default"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        loc = res.headers.get("location") or ""
        assert loc.startswith("/ask")
        assert "thread=" in loc
        assert "run=" in loc
        cmd_id = loc.split("run=")[1].split("&")[0]
        thread_id = loc.split("thread=")[1].split("&")[0]
        rec = _wait_done(client, cmd_id)
        assert rec.get("status") == "done"
        assert rec.get("result", {}).get("thread_id") == thread_id
        thread_path = cfg.state_dir / "rag" / "threads" / f"{thread_id}.json"
        assert thread_path.is_file()
        page = client.get(f"/ask?thread={thread_id}")
        assert "Answer [S1]." in page.text
        assert "ABCD1234" in page.text
        assert "ocean/BBNJ" in page.text
        alias = client.get(f"/index?thread={thread_id}", follow_redirects=False)
        assert alias.status_code == 303
        assert f"thread={thread_id}" in (alias.headers.get("location") or "")
        legacy = client.post(
            "/index/ask",
            data={"question": "Follow-up?", "focus": "default"},
            follow_redirects=False,
        )
        assert legacy.status_code == 303
        legacy_loc = legacy.headers.get("location") or ""
        assert legacy_loc.startswith("/ask")
        legacy_cmd = legacy_loc.split("run=")[1].split("&")[0]
        assert _wait_done(client, legacy_cmd).get("status") == "done"
    finally:
        jobs.ask_turn_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_ask_shows_running_status(tmp_path, monkeypatch):
    import threading

    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    _fresh_index(monkeypatch)
    gate = threading.Event()

    def fake(cfg, cmd_id, **kw):
        gate.wait(timeout=2)
        return {"thread_id": kw.get("thread_id") or "", "answer": "later"}

    jobs.ask_turn_fn = fake
    try:
        client = TestClient(create_app(cfg))
        res = client.post(
            "/ask",
            data={"question": "What is BBNJ?", "focus": "default"},
            follow_redirects=False,
        )
        loc = res.headers.get("location") or ""
        page = client.get(loc)
        assert "Ask" in page.text
        assert "queued" in page.text or "running" in page.text
        assert "cmd-status" in page.text
        assert 'data-poll-run="' in page.text
        gate.set()
        cmd_id = loc.split("run=")[1].split("&")[0]
        assert _wait_done(client, cmd_id).get("status") == "done"
    finally:
        gate.set()
        jobs.ask_turn_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_ask_batch_shows_running_status(tmp_path, monkeypatch):
    import threading

    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    _fresh_index(monkeypatch)
    gate = threading.Event()

    def fake(cfg, cmd_id, **kw):
        gate.wait(timeout=2)
        return {"stamp": "batch01", "questions": 1, "answered": 1, "skipped": 0, "failed": 0}

    jobs.ask_batch_fn = fake
    try:
        client = TestClient(create_app(cfg))
        client.cookies.set("pf_advanced", "1")
        res = client.post(
            "/ask/batch",
            data={"questions": "What is BBNJ?", "focus": "default"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        loc = res.headers.get("location") or ""
        assert "run=" in loc
        page = client.get(loc)
        assert "Batch Ask" in page.text
        assert "queued" in page.text or "running" in page.text
        assert "cmd-status" in page.text
        assert 'data-poll-run="' in page.text
        gate.set()
        cmd_id = loc.split("run=")[1].split("&")[0]
        assert _wait_done(client, cmd_id).get("status") == "done"
    finally:
        gate.set()
        jobs.ask_batch_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_follow_up_uses_thread_id(tmp_path, monkeypatch):
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
        tid = kw.get("thread_id") or "aaaaaaaaaaaa"
        return {
            "thread_id": tid,
            "question": kw["question"],
            "retrieve_as": kw["question"],
            "answer": "ok",
            "cited": [],
            "sources": [],
            "focus": "default",
        }

    jobs.ask_turn_fn = fake
    try:
        client = TestClient(create_app(cfg))
        res = client.post(
            "/ask",
            data={"question": "first", "thread_id": "bbbbbbbbbbbb", "focus": "gaps"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        cmd_id = (res.headers.get("location") or "").split("run=")[1].split("&")[0]
        rec = _wait_done(client, cmd_id)
        assert rec.get("status") == "done"
        match = next((row for row in seen if row.get("question") == "first"), None)
        assert match is not None
        assert match["thread_id"] == "bbbbbbbbbbbb"
        assert match["focus"] == "gaps"
    finally:
        jobs.ask_turn_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_empty_question_redirects(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    client = TestClient(create_app(cfg))
    res = client.post("/ask", data={"question": "  "}, follow_redirects=False)
    assert res.status_code == 303
    assert "error=empty" in (res.headers.get("location") or "")
    assert commands.list_commands(cfg) == []


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_bad_focus_and_disabled_post(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    client = TestClient(create_app(cfg))
    bad = client.post(
        "/ask",
        data={"question": "hello", "focus": "not-a-focus"},
        follow_redirects=False,
    )
    assert bad.status_code == 303
    assert "error=focus" in (bad.headers.get("location") or "")
    assert commands.list_commands(cfg) == []

    cfg.llm_enabled = False
    off = client.post(
        "/ask",
        data={"question": "hello", "focus": "default"},
        follow_redirects=False,
    )
    assert off.status_code == 303
    assert "error=disabled" in (off.headers.get("location") or "")


def test_run_ask_turn_requires_rag(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.rag_enabled = False
    with pytest.raises(ValueError, match="rag.enabled"):
        run_ask_turn(
            cfg,
            question="What is BBNJ?",
            thread_id=None,
            collection="",
            year_from=None,
            year_to=None,
            focus=None,
        )


def test_list_threads_skips_corrupt(tmp_path):
    from paperful.ui.pages import list_threads
    from paperful.rag.thread import Thread, save_thread

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    save_thread(
        cfg.state_dir,
        Thread(
            thread_id="goodthread01",
            turns=[
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"},
            ],
        ),
    )
    bad = cfg.state_dir / "rag" / "threads" / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    rows = list_threads(cfg)
    ids = {r["id"] for r in rows}
    assert "goodthread01" in ids
    assert "broken" not in ids


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_ask_forwards_prompt_and_scope(tmp_path, monkeypatch):
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
        return {
            "thread_id": kw.get("thread_id") or "t",
            "question": kw["question"],
            "retrieve_as": kw["question"],
            "answer": "ok",
            "cited": [],
            "sources": [],
            "focus": "default",
        }

    jobs.ask_turn_fn = fake
    try:
        client = TestClient(create_app(cfg))
        client.cookies.set("pf_collection", "ocean/BBNJ")
        res = client.post(
            "/ask",
            data={
                "question": "What is BBNJ?",
                "prompt_inline": "Be terse.",
                "item_keys": "ABCD1234",
                "top_k": "5",
            },
            follow_redirects=False,
        )
        assert res.status_code == 303
        cmd_id = (res.headers.get("location") or "").split("run=")[1].split("&")[0]
        rec = _wait_done(client, cmd_id)
        assert rec.get("status") == "done"
        assert seen[0]["prompt_text"] == "Be terse."
        assert seen[0]["item_keys"] == ["ABCD1234"]
        assert seen[0]["top_k"] == 5
    finally:
        jobs.ask_turn_fn = None


def test_ask_page_flags_need_both_and_index_rows(tmp_path, monkeypatch):
    from paperful.ui.pages import ask_page_flags

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    monkeypatch.setattr(
        "paperful.rag.status.index_status",
        lambda _cfg, entries=None: {"exists": False, "items": 0, "problem": ""},
    )
    flags = ask_page_flags(cfg)
    assert flags["ready"] is True
    assert flags["can_ask"] is False
    assert flags["can_ingest"] is True
    assert flags["can_search"] is False
    cfg.llm_enabled = False
    flags = ask_page_flags(cfg)
    assert flags["ready"] is False
    assert flags["can_ask"] is False
    assert flags["can_ingest"] is True


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_ask_batch_is_advanced_only(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    _fresh_index(monkeypatch)
    client = TestClient(create_app(cfg))
    simple = client.get("/ask")
    assert simple.status_code == 200
    assert 'action="/ask"' in simple.text
    assert 'action="/ask/batch"' not in simple.text
    assert "Batch Ask" not in simple.text
    client.cookies.set("pf_advanced", "1")
    advanced = client.get("/ask")
    assert 'action="/ask/batch"' in advanced.text
    assert "Batch Ask" in advanced.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_ask_empty_index_offers_ingest_and_index_has_no_ask_form(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = True
    cfg.llm_enabled = True
    _ops(monkeypatch)
    monkeypatch.setattr(
        "paperful.rag.status.index_status",
        lambda _cfg, entries=None: {"exists": False, "items": 0, "problem": ""},
    )
    client = TestClient(create_app(cfg))
    ask = client.get("/ask")
    assert ask.status_code == 200
    assert "Ingest first" in ask.text
    assert 'name="next" value="ask"' in ask.text
    assert 'action="/ask"' not in ask.text
    jobs.rag_ingest_fn = lambda *a, **kw: {"dry_run": True, "summary": {}}
    try:
        ingest = client.post(
            "/index/ingest",
            data={"dry_run": "1", "next": "ask"},
            follow_redirects=False,
        )
    finally:
        jobs.rag_ingest_fn = None
    assert ingest.status_code == 303
    loc = ingest.headers.get("location") or ""
    assert loc.startswith("/ask")
    assert "run=" in loc
    index = client.get("/index")
    assert index.status_code == 200
    assert 'action="/ask"' not in index.text
    assert 'action="/index/ask"' not in index.text
    assert "Batch Ask" not in index.text
