"""Local-trust hardening: bind gate, review-token paths, CDP origins."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperful.serve import REMOTE_BIND_HINT, is_loopback_bind_host, run_server
from paperful.ui import commands


def test_is_loopback_bind_host():
    assert is_loopback_bind_host("127.0.0.1")
    assert is_loopback_bind_host("::1")
    assert is_loopback_bind_host("localhost")
    assert not is_loopback_bind_host("0.0.0.0")
    assert not is_loopback_bind_host("192.168.1.10")
    assert not is_loopback_bind_host("example.com")


def test_run_server_refuses_non_loopback_without_flag(cfg, monkeypatch):
    monkeypatch.setattr(
        "paperful.serve.fastapi_available",
        lambda: True,
    )

    def boom(*_a, **_k):
        raise AssertionError("uvicorn should not start")

    monkeypatch.setattr("uvicorn.run", boom)
    with pytest.raises(RuntimeError, match="allow-remote-bind"):
        run_server(cfg, host="0.0.0.0", port=8765, allow_remote_bind=False)


def test_run_server_allows_remote_with_flag(cfg, monkeypatch):
    monkeypatch.setattr("paperful.serve.fastapi_available", lambda: True)
    seen: dict[str, object] = {}

    def fake_run(app, *, host, port):
        seen["host"] = host
        seen["port"] = port

    monkeypatch.setattr("uvicorn.run", fake_run)
    run_server(cfg, host="0.0.0.0", port=8765, allow_remote_bind=True)
    assert seen == {"host": "0.0.0.0", "port": 8765}


def test_load_review_rejects_path_traversal(cfg):
    reviews = cfg.state_dir / "gui" / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    # Would escape if joined naively as reviews / f"{token}.json"
    assert commands.load_review(cfg, "../escape") is None
    assert commands.load_review(cfg, "..%2fescape") is None
    assert commands.load_review(cfg, "a/b") is None
    assert commands.load_review(cfg, "") is None


def test_load_review_accepts_urlsafe_token(cfg):
    token = commands.create_review_token(
        cfg,
        verb="grab",
        collection="C",
        preset="oa",
        keys=["K1"],
        fingerprint="fp",
        command_id="cmd-missing",
    )
    data = commands.load_review(cfg, token)
    assert data is not None
    assert data["token"] == token
    path = Path(cfg.state_dir) / "gui" / "reviews" / f"{token}.json"
    assert path.is_file()


def test_remote_bind_hint_mentions_no_auth():
    assert "no auth" in REMOTE_BIND_HINT.lower() or "No auth" in REMOTE_BIND_HINT
