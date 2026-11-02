"""Hardening added in the expand-and-harden build (fsio, origin guard, config check, sr)."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.requests import Request

from paperful.config_check import check_config
from paperful.fsio import atomic_write_json
from paperful.sr.protocol import load_protocol, save_protocol
from paperful.sr.screen import append_screen_decision, load_screen_ledger
from paperful.ui.origin_guard import _allowed_origin


def test_atomic_write_json_roundtrip(tmp_path: Path):
    path = tmp_path / "nested" / "x.json"
    atomic_write_json(path, {"a": 1})
    from paperful.store import load_json

    assert load_json(path) == {"a": 1}


def test_config_check_unknown_section(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[typo_llm]\nenabled = true\n", encoding="utf-8")
    issues = check_config(cfg_path)
    assert any("typo_llm" in line for line in issues)


def test_config_check_accepts_example_config_and_documented_sections(tmp_path: Path):
    repo_example = Path(__file__).resolve().parents[1] / "config.example.toml"
    assert check_config(repo_example) == []
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        'email = "a@example.org"\n'
        "[summarize]\n"
        'style = "ste"\n'
        "[gaps]\n"
        "list_missing = true\n"
        "[[exclude]]\n"
        'key = "ABCD1234"\n',
        encoding="utf-8",
    )
    assert check_config(cfg_path) == []


def test_atomic_write_concurrent_same_target(tmp_path: Path):
    """Two writers on one path must not race on a shared temp name."""
    import threading

    path = tmp_path / "shared.json"
    errors: list[BaseException] = []

    def work(n: int) -> None:
        try:
            for i in range(50):
                atomic_write_json(path, {"n": n, "i": i})
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert path.is_file()
    assert not list(tmp_path.glob("*.part"))


def test_sr_protocol_and_screen(tmp_path: Path):
    state = tmp_path / "state"
    save_protocol(state, "demo", {"title": "T", "question": "Q?"})
    proto = load_protocol(state, "demo")
    assert proto["title"] == "T"
    append_screen_decision(
        state,
        "demo",
        identity="https://openalex.org/W1",
        decision="include",
        reason="on_topic",
        reviewer="r1",
    )
    rows = load_screen_ledger(state, "demo")
    assert len(rows) == 1
    assert rows[0]["decision"] == "include"


def test_origin_guard_blocks_cross_site():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/settings",
        "headers": [
            (b"origin", b"https://evil.example"),
            (b"host", b"127.0.0.1:8765"),
            (b"sec-fetch-site", b"cross-site"),
        ],
    }
    request = Request(scope)
    assert _allowed_origin(request) is False


def test_origin_guard_allows_same_origin_post():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/wanted/grab",
        "headers": [
            (b"origin", b"http://127.0.0.1:8765"),
            (b"host", b"127.0.0.1:8765"),
            (b"sec-fetch-site", b"same-origin"),
        ],
    }
    request = Request(scope)
    assert _allowed_origin(request) is True


def test_config_check_cli(tmp_path: Path):
    from typer.testing import CliRunner

    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[bad_section]\nenabled = true\n", encoding="utf-8")
    runner = CliRunner()
    res = runner.invoke(app, ["config", "check", "--config", str(cfg_path)])
    assert res.exit_code == 1
    assert "bad_section" in res.stdout


def test_sr_cli_init_and_status(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from paperful.cli import app
    from paperful.config import Config

    state = tmp_path / "state"
    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=state)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('email = "t@example.org"\n', encoding="utf-8")
    cfg.config_path = cfg_path

    import paperful.cli_runtime as cli_mod

    monkeypatch.setattr(cli_mod, "_cfg", lambda _path=None: cfg)
    runner = CliRunner()
    res = runner.invoke(
        app,
        ["sr", "init", "--slug", "demo", "--title", "T", "--question", "Q?"],
    )
    assert res.exit_code == 0, res.stdout
    res2 = runner.invoke(app, ["sr", "status", "--slug", "demo"])
    assert res2.exit_code == 0
    assert "demo" in res2.stdout


def test_enqueue_rejects_when_queue_full(cfg, monkeypatch):
    from paperful.ui import commands

    monkeypatch.setattr(commands, "MAX_QUEUED_JOBS", 1)
    monkeypatch.setattr(commands, "_ensure_worker", lambda: None)
    commands._queue.clear()
    commands._queue.append(("x", lambda: None))
    with pytest.raises(RuntimeError, match="too many queued"):
        commands.enqueue(cfg, "test", lambda _id: None)


@pytest.mark.enable_socket
def test_grey_live_marker_still_allows_socket():
    """Live tests opt in with enable_socket; default suite stays offline."""
    assert True


def _gui_client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from paperful.config import Config
    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    return cfg, TestClient(create_app(cfg))


def test_security_headers_on_html_and_static(tmp_path, monkeypatch):
    _cfg, client = _gui_client(tmp_path, monkeypatch)
    page = client.get("/activity")
    assert page.status_code == 200
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["referrer-policy"] == "same-origin"
    assert page.headers["cache-control"] == "no-store"
    # No inline handlers or inline scripts anywhere in the rendered shell.
    assert "onclick=" not in page.text
    assert "onchange=" not in page.text
    assert "onsubmit=" not in page.text
    assert "<script>" not in page.text
    # No third-party font hosts.
    assert "fonts.googleapis.com" not in page.text
    assert "fonts.gstatic.com" not in page.text
    hashed = client.get("/static/workbench.css?v=abc123")
    assert hashed.headers["cache-control"].startswith("public, max-age=31536000")
    plain = client.get("/static/workbench.css")
    assert plain.headers["cache-control"] == "public, max-age=300"


def test_templates_have_no_inline_handlers():
    templates = Path(__file__).resolve().parents[1] / "paperful" / "ui" / "templates"
    offenders = []
    for path in templates.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        for needle in ("onclick=", "onchange=", "onsubmit=", "oninput=", "<script>"):
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert offenders == []


def test_reconcile_marks_stale_running_failed(tmp_path, monkeypatch):
    import json
    import time

    from paperful.config import Config
    from paperful.ui import commands

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cmd_dir = cfg.state_dir / "gui" / "commands"
    cmd_dir.mkdir(parents=True)
    old = time.time() - 3600
    for cmd_id, status in (("aaa111", "queued"), ("bbb222", "running")):
        (cmd_dir / f"{cmd_id}.json").write_text(
            json.dumps(
                {
                    "id": cmd_id,
                    "verb": "synthesize",
                    "status": status,
                    "created": old,
                }
            )
        )
    (cmd_dir / "ccc333.json").write_text(
        json.dumps({"id": "ccc333", "verb": "ask", "status": "done", "created": old})
    )
    assert commands.reconcile_orphans(cfg) == 2
    for cmd_id in ("aaa111", "bbb222"):
        rec = commands.read_command(cfg, cmd_id)
        assert rec["status"] == "failed"
        assert rec["error"] == commands.ORPHAN_ERROR
        assert rec["finished"] > old
    assert commands.read_command(cfg, "ccc333")["status"] == "done"
    # mount_ui runs the reconciliation, so a fresh app shows them as failed.
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    (cmd_dir / "ddd444.json").write_text(
        json.dumps({"id": "ddd444", "verb": "ask", "status": "running", "created": old})
    )
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from paperful.serve import create_app

    client = TestClient(create_app(cfg))
    body = client.get("/v1/runs/ddd444").json()
    assert body["status"] == "failed"
    page = client.get("/activity")
    assert 'data-run-status="failed"' in page.text
    assert commands.ORPHAN_ERROR in page.text
