"""Wanted POST routes: form → job wiring, flag parsing, and refusals (no real jobs)."""

from __future__ import annotations

from urllib.parse import unquote_plus

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available
from paperful.ui import commands, jobs, wanted_jobs

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
    client.cookies.set("pf_collection", "ocean/BBNJ")

    class Env:
        pass

    e = Env()
    e.cfg, e.client, e.queued = cfg, client, queued
    return e


def _post(env, path, data=""):
    return env.client.post(path, content=data.encode(), headers=FORM, follow_redirects=False)


def _run_last(env):
    verb, fn = env.queued[-1]
    fn("cmd-test")
    return verb


def test_root_redirects_to_wanted(env):
    res = env.client.get("/", follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"] == "/wanted"


def test_preview_passes_keys_and_ignores_flags_without_advanced(env, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(jobs, "preview_run", lambda cfg, cmd_id, **kw: seen.update(kw, cmd=cmd_id))
    res = _post(env, "/wanted/preview", "keys=K1&keys=K2&year_from=2020&limit=5")
    assert res.status_code == 303 and res.headers["location"] == "/wanted?poll=cmd1"
    assert _run_last(env) == "preview_run"
    assert seen["keys"] == ["K1", "K2"]
    assert seen["flags"] == {}  # Advanced is off, so the form flags are dropped
    assert seen["collection"] == "ocean/BBNJ" and seen["preset"] == "oa"


def test_preview_parses_advanced_flags(env, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(jobs, "preview_run", lambda cfg, cmd_id, **kw: seen.update(kw))
    env.client.cookies.set("pf_advanced", "1")
    _post(
        env,
        "/wanted/preview",
        "year_from=2019&year_to=2024&item_type=journalArticle,book&limit=7"
        "&retry_failed=1&try_all=1&upgrade_linked=1&browser_agent=1&htmlpdf=1",
    )
    _run_last(env)
    flags = seen["flags"]
    assert (flags["year_from"], flags["year_to"], flags["limit"]) == (2019, 2024, 7)
    assert flags["item_type"] == ["journalArticle", "book"]
    assert all(flags[k] for k in ("retry_failed", "try_all", "upgrade_linked", "browser_agent", "htmlpdf"))
    assert seen["keys"] is None


@pytest.mark.parametrize("path", ["/wanted/preview", "/wanted/grab"])
def test_non_numeric_year_is_a_redirect_with_error(env, path):
    env.client.cookies.set("pf_advanced", "1")
    res = _post(env, path, "year_from=abc")
    assert res.status_code == 303
    assert "whole numbers" in unquote_plus(res.headers["location"])
    assert env.queued == []


def test_recover_preview_bad_limit_redirects(env):
    res = _post(env, "/wanted/recover/preview", "limit=lots")
    assert res.status_code == 303 and "whole numbers" in unquote_plus(res.headers["location"])
    assert env.queued == []


def test_grab_without_matching_preview_redirects_with_reason(env, monkeypatch):
    monkeypatch.setattr(jobs, "matching_preview", lambda cfg, **kw: (None, "Preview first."))
    res = _post(env, "/wanted/grab", "keys=K1")
    assert res.status_code == 303
    assert "Preview first." in unquote_plus(res.headers["location"])


def test_grab_runs_with_matching_preview_and_reports_failure(env, monkeypatch):
    monkeypatch.setattr(jobs, "matching_preview", lambda cfg, **kw: ({"token": "TOK"}, ""))
    calls: list[str] = []
    monkeypatch.setattr(jobs, "grab_run", lambda cfg, *, token: (calls.append(token) or True, ""))
    assert _post(env, "/wanted/grab", "keys=K1").headers["location"] == "/wanted"
    assert calls == ["TOK"]
    monkeypatch.setattr(jobs, "grab_run", lambda cfg, *, token: (False, "fetch exploded"))
    res = _post(env, "/wanted/grab")
    assert res.status_code == 303 and "fetch exploded" in unquote_plus(res.headers["location"])


def test_attach_preview_forwards_override_flags(env, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(wanted_jobs, "attach_preview", lambda cfg, cmd_id, **kw: seen.update(kw))
    res = _post(env, "/wanted/attach/preview", "keys=K9&allow_mismatch=1")
    assert res.headers["location"] == "/wanted?run=cmd1"
    assert _run_last(env) == "attach"
    assert seen == {
        "collection": "ocean/BBNJ",
        "keys": ["K9"],
        "allow_mismatch": True,
        "allow_short": False,
    }


def test_attach_with_valid_review_token_uses_apply(env, monkeypatch):
    token = commands.create_review_token(
        env.cfg, verb="attach", collection="ocean/BBNJ", preset="oa",
        keys=["K1"], fingerprint="fp", command_id="none",
    )
    monkeypatch.setattr(wanted_jobs, "attach_apply", lambda cfg, *, token: (True, ""))
    res = _post(env, "/wanted/attach", f"review_token={token}")
    assert res.status_code == 303 and res.headers["location"] == "/wanted"


def test_attach_with_wrong_verb_token_falls_back_to_plain_attach(env, monkeypatch):
    token = commands.create_review_token(
        env.cfg, verb="grab", collection="C", preset="oa",
        keys=["K1"], fingerprint="fp", command_id="none",
    )
    applied: list[object] = []
    monkeypatch.setattr(wanted_jobs, "attach_apply", lambda cfg, *, token: applied.append(1) or (True, ""))
    monkeypatch.setattr(jobs, "attach_run", lambda cfg, *, keys, collection: (False, "no attachable PDFs", 0))
    res = _post(env, "/wanted/attach", f"review_token={token}&keys=K1")
    assert applied == [] and res.status_code == 409


def test_recover_preview_and_apply(env, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(wanted_jobs, "recover_preview", lambda cfg, cmd_id, **kw: seen.update(kw))
    _post(env, "/wanted/recover/preview", "keys=K1&from_last_run=1&limit=3")
    assert _run_last(env) == "recover"
    assert seen["keys"] == ["K1"] and seen["limit"] == 3
    assert seen["from_last_run"] is True and seen["from_last_run_mode"] == "browser_agent_miss"

    tokens: list[str] = []
    monkeypatch.setattr(
        wanted_jobs, "recover_apply", lambda cfg, *, token: (tokens.append(token) or True, "")
    )
    assert _post(env, "/wanted/recover", "review_token=ABC").status_code == 303
    assert tokens == ["ABC"]
    monkeypatch.setattr(wanted_jobs, "recover_apply", lambda cfg, *, token: (False, "stale"))
    res = _post(env, "/wanted/recover", "review_token=ABC")
    assert res.status_code == 409 and res.json() == {"ok": False, "error": "stale"}


def test_recover_apply_falls_back_to_latest_recover_token(env, monkeypatch):
    commands.write_command(
        env.cfg,
        {"id": "r1", "verb": "recover", "status": "done", "review_token": "LATEST",
         "created": 1.0, "error": "", "report_path": ""},
    )
    tokens: list[str] = []
    monkeypatch.setattr(
        wanted_jobs, "recover_apply", lambda cfg, *, token: (tokens.append(token) or True, "")
    )
    _post(env, "/wanted/recover")
    assert tokens == ["LATEST"]


@pytest.mark.parametrize(
    ("path", "body", "verb", "fn_name", "expect"),
    [
        (
            "/wanted/handoff",
            "keys=K1&mode=tabs&include_doi_tabs=1",
            "handoff",
            "handoff_run",
            {"keys": ["K1"], "mode": "tabs", "include_doi_tabs": True},
        ),
        ("/wanted/handoff", "", "handoff", "handoff_run",
         {"keys": None, "mode": "list", "include_doi_tabs": False}),
        ("/wanted/inbox/drain", "", "inbox_drain", "inbox_drain", {"collection": "ocean/BBNJ"}),
        (
            "/wanted/reachout",
            "keys=K1&non_oa_only=1&lookup=1&handoff_mode=list",
            "reachout",
            "reachout_run",
            {"keys": ["K1"], "non_oa_only": True, "lookup": True, "handoff_mode": "list"},
        ),
    ],
)
def test_simple_job_routes_enqueue_and_forward_form(env, monkeypatch, path, body, verb, fn_name, expect):
    seen: dict = {}
    monkeypatch.setattr(wanted_jobs, fn_name, lambda cfg, cmd_id, **kw: seen.update(kw))
    res = _post(env, path, body)
    assert res.status_code == 303 and res.headers["location"] == "/wanted?run=cmd1"
    assert _run_last(env) == verb
    for key, value in expect.items():
        assert seen[key] == value


def test_summarize_guards(env):
    # LLM off (default): bounce before queuing anything.
    res = _post(env, "/wanted/summarize", "key=K1")
    assert res.headers["location"] == "/wanted?error=llm"
    assert env.queued == []


def test_summarize_validates_key_and_dest_when_llm_enabled(env, monkeypatch):
    monkeypatch.setattr(Config, "llm_enabled", property(lambda self: True))
    assert _post(env, "/wanted/summarize", "key=").headers["location"] == "/wanted"
    bad = _post(env, "/wanted/summarize", "key=K1&dest=carrier-pigeon")
    assert bad.headers["location"] == "/wanted?error=dest"
    assert env.queued == []
    ok = _post(env, "/wanted/summarize", "key=K1&dest=disk")
    assert ok.headers["location"].startswith("/wanted?run=")
    assert env.queued[-1][0] == "summarize_item"


def test_item_summary_serves_only_existing_safe_files(env):
    env.cfg.summaries_dir.mkdir(parents=True, exist_ok=True)
    (env.cfg.summaries_dir / "K1.html").write_text("<p>sum</p>", encoding="utf-8")
    ok = env.client.get("/item/K1/summary")
    assert ok.status_code == 200 and "<p>sum</p>" in ok.text
    assert env.client.get("/item/NOPE/summary").status_code == 404
    assert env.client.get("/item/..%2fK1/summary").status_code == 404
