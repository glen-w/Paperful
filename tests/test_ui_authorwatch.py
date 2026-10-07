"""Authorwatch Discover routes."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_aw_save_creates_list(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    client = TestClient(create_app(cfg))
    res = client.post(
        "/discover/aw/save",
        data={"name": "lab-list"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert (cfg.state_dir / "authorwatch" / "lab-list" / "watch.json").is_file()


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_import_requires_file(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    client = TestClient(create_app(cfg))
    res = client.post("/discover/aw/import", data={"list_name": "lab-list"})
    assert res.status_code == 400


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_apply_consumes_token_once(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.authorwatch import save_list
    from paperful.ui import jobs

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    save_list(cfg, "lab-list")
    (cfg.state_dir / "authorwatch" / "lab-list" / "inbox.jsonl").write_text(
        "", encoding="utf-8"
    )
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    applied: list[str] = []
    jobs.authorwatch_apply_fn = lambda cfg, list_name="", collection="": applied.append(
        list_name
    )
    try:
        client = TestClient(create_app(cfg))
        client.cookies.set("pf_collection", "ocean")
        preview = client.post(
            "/discover/apply-preview",
            data={"kind": "authorwatch", "list_name": "lab-list"},
            follow_redirects=False,
        )
        assert preview.status_code == 303
        deadline = time.time() + 2
        token = ""
        while time.time() < deadline:
            cmds = __import__("paperful.ui.commands", fromlist=["list_commands"]).list_commands(cfg)
            for rec in cmds:
                if rec.get("review_token"):
                    token = rec["review_token"]
                    break
            if token:
                break
            time.sleep(0.02)
        assert token
        first = client.post(
            "/discover/apply",
            data={
                "kind": "authorwatch",
                "list_name": "lab-list",
                "review_token": token,
            },
            follow_redirects=False,
        )
        assert first.status_code == 303
        assert applied == ["lab-list"]
        second = client.post(
            "/discover/apply",
            data={
                "kind": "authorwatch",
                "list_name": "lab-list",
                "review_token": token,
            },
            follow_redirects=False,
        )
        assert second.status_code == 409
        assert applied == ["lab-list"]
    finally:
        jobs.authorwatch_apply_fn = None


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_aw_suggest_enqueues(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.authorwatch import save_list
    from paperful.ui import jobs

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    save_list(cfg, "lab-list")
    seen: list[dict] = []

    def suggest_fn(cfg, list_name="", collection="", method="", limit=15):
        seen.append(
            {
                "list": list_name,
                "collection": collection,
                "method": method,
                "limit": limit,
            }
        )

    monkeypatch.setattr(jobs, "authorwatch_suggest", suggest_fn)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_collection", "ocean")
    res = client.post(
        "/discover/aw/suggest",
        data={"list_name": "lab-list", "method": "mix", "limit": "10"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    deadline = time.time() + 2
    while time.time() < deadline and not seen:
        time.sleep(0.02)
    assert seen
    assert seen[0]["method"] == "mix"
    assert seen[0]["limit"] == 10


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_aw_delete_list(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.authorwatch import save_list

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    save_list(cfg, "gone")
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    client = TestClient(create_app(cfg))
    res = client.post(
        "/discover/aw/delete",
        data={"list_name": "gone"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert not (cfg.state_dir / "authorwatch" / "gone").is_dir()


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_aw_accept_enqueues(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.authorwatch import append_suggestions, save_list
    from paperful.authorwatch_suggest import Suggestion
    from paperful.ui import jobs

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    save_list(cfg, "lab-list")
    append_suggestions(
        cfg,
        "lab-list",
        [
            Suggestion(
                id="sug_test1",
                display_name="Jane Researcher",
                orcid="0000-0002-1825-0097",
                pollable=True,
            )
        ],
    )
    accepted: list[list[str]] = []

    def accept_fn(cfg, list_name="", suggestion_ids=None, seed_from=None):
        accepted.append(list(suggestion_ids or []))

    monkeypatch.setattr(jobs, "authorwatch_accept", accept_fn)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    client = TestClient(create_app(cfg))
    client.post(
        "/discover/aw/accept",
        data={"list_name": "lab-list", "suggestion_id": "sug_test1"},
        follow_redirects=False,
    )
    deadline = time.time() + 2
    while time.time() < deadline and not accepted:
        time.sleep(0.02)
    assert accepted == [["sug_test1"]]


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_report_route_404(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_advanced", "1")
    assert client.get("/index/report/no-such-slug").status_code == 404
