"""Repair and Mirror routes: verb/scope guards and form → job wiring (jobs stubbed)."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available
from paperful.ui import commands, jobs

pytestmark = pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")

FORM = {"Content-Type": "application/x-www-form-urlencoded"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _cfg: {"ok": True, "collections": []}
    )
    queued: list[tuple[str, object]] = []

    def fake_enqueue(_cfg, verb, fn, *, args=None):
        queued.append((verb, fn))
        return f"cmd{len(queued)}"

    monkeypatch.setattr(commands, "enqueue", fake_enqueue)
    client = TestClient(create_app(cfg))

    class Env:
        pass

    e = Env()
    e.cfg, e.client, e.queued = cfg, client, queued
    return e


def _post(env, path, data=""):
    return env.client.post(path, content=data.encode(), headers=FORM, follow_redirects=False)


def test_repair_and_mirror_pages_render(env):
    assert env.client.get("/repair").status_code == 200
    assert env.client.get("/mirror").status_code == 200
    assert env.client.get("/repair?error=verb").status_code == 200
    assert env.client.get("/mirror?run=missing&error=collection").status_code == 200


def test_repair_preview_rejects_unknown_verb_and_missing_collection(env):
    env.client.cookies.set("pf_collection", "ocean")
    assert _post(env, "/repair/preview", "verb=rm-rf").headers["location"] == "/repair?error=verb"
    env.client.cookies.clear()
    res = _post(env, "/repair/preview", "verb=dedupe")
    assert res.headers["location"] == "/repair?error=collection"
    assert env.queued == []


def test_repair_preview_forwards_flags_to_job(env, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(jobs, "repair_preview", lambda cfg, cmd_id, **kw: seen.update(kw))
    env.client.cookies.set("pf_collection", "ocean")
    res = _post(
        env,
        "/repair/preview",
        "verb=attachments&overwrite=1&fix_broken=1&rename=1&force_retry=1",
    )
    assert res.headers["location"] == "/repair?run=cmd1"
    verb, fn = env.queued[0]
    assert verb == "repair_attachments"
    fn("cmd-x")
    assert seen["verb"] == "attachments" and seen["collection"] == "ocean"
    assert seen["overwrite"] is True and seen["apply_medium"] is False
    assert seen["surgery"] == {
        "fix_broken": True, "merge_files": False, "rename": True, "link": False,
        "attach": False, "force_retry": True, "auto_ignore_failures": False,
    }


def test_repair_preview_scope_error_marks_command_failed(env, monkeypatch):
    from paperful.ui.repair_mirror_jobs import GuiScopeError

    commands.write_command(
        env.cfg,
        {"id": "cmd-x", "verb": "repair_lint", "status": "running", "error": "",
         "report_path": "", "created": 1.0},
    )

    def boom(cfg, cmd_id, **kw):
        raise GuiScopeError("scope is too wide")

    monkeypatch.setattr(jobs, "repair_preview", boom)
    env.client.cookies.set("pf_collection", "ocean")
    _post(env, "/repair/preview", "verb=lint")
    _verb, fn = env.queued[0]
    with pytest.raises(GuiScopeError):
        fn("cmd-x")
    rec = commands.read_command(env.cfg, "cmd-x")
    assert rec["status"] == "failed" and rec["error"] == "scope is too wide"


def test_repair_apply_requires_token_and_reports_refusal(env, monkeypatch):
    missing = _post(env, "/repair/apply", "")
    assert missing.status_code == 409 and missing.json()["error"] == "missing review token"
    monkeypatch.setattr(jobs, "repair_apply", lambda cfg, *, token: (False, "library changed since preview"))
    refused = _post(env, "/repair/apply", "review_token=TOK")
    assert refused.status_code == 409
    assert refused.json() == {"ok": False, "error": "library changed since preview"}
    tokens: list[str] = []
    monkeypatch.setattr(jobs, "repair_apply", lambda cfg, *, token: (tokens.append(token) or True, ""))
    ok = _post(env, "/repair/apply", "review_token=TOK")
    assert ok.status_code == 303 and ok.headers["location"] == "/repair"
    assert tokens == ["TOK"]


def test_mirror_preview_guards(env):
    assert _post(env, "/mirror/preview", "verb=burn").headers["location"] == "/mirror?error=verb"
    for verb in ("snapshot", "restore"):
        res = _post(env, "/mirror/preview", f"verb={verb}")
        assert res.headers["location"] == "/mirror?error=collection"
    assert env.queued == []


def test_mirror_preview_unscoped_sync_and_scoped_snapshot(env, monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(jobs, "mirror_preview", lambda cfg, cmd_id, **kw: seen.append(kw))
    res = _post(env, "/mirror/preview", "verb=sync&accept_gone=1")
    assert res.headers["location"] == "/mirror?run=cmd1"
    env.queued[0][1]("c")
    assert seen[0]["verb"] == "sync" and seen[0]["accept_gone"] is True
    assert seen[0]["pdfs"] == "lazy"

    env.client.cookies.set("pf_collection", "ocean")
    _post(env, "/mirror/preview", "verb=snapshot&pdfs=all")
    verb, fn = env.queued[1]
    assert verb == "mirror_snapshot"
    fn("c")
    assert seen[1]["collection"] == "ocean" and seen[1]["pdfs"] == "all"


def test_mirror_apply_requires_token(env, monkeypatch):
    assert _post(env, "/mirror/apply", "verb=sync").status_code == 409
    monkeypatch.setattr(jobs, "mirror_apply", lambda cfg, *, token, collection: (False, "stale"))
    assert _post(env, "/mirror/apply", "review_token=T").json() == {"ok": False, "error": "stale"}
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        jobs, "mirror_apply",
        lambda cfg, *, token, collection: (calls.append((token, collection)) or True, ""),
    )
    env.client.cookies.set("pf_collection", "ocean")
    res = _post(env, "/mirror/apply", "review_token=T&verb=sync")
    assert res.status_code == 303 and res.headers["location"] == "/mirror"
    assert calls == [("T", "ocean")]
