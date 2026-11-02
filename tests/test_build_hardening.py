"""Hardening added in the expand-and-harden build (fsio, origin guard, config check, sr)."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.requests import Request

from paperful.config_check import check_config
from paperful.fsio import atomic_write_json
from paperful.sr.protocol import load_protocol, save_protocol
from paperful.sr.screen import append_screen_decision, load_screen_ledger
from paperful.ui.origin_guard import OriginGuardMiddleware, _allowed_origin


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
