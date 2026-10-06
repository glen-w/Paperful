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
        assert b"summary" in html.content
    finally:
        jobs.summarize_fn = None


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
    finally:
        jobs.synthesize_fn = None
