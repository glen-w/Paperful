"""System Chrome discovery and login engine selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperful import session as sess


def test_find_system_chrome_prefers_candidate(tmp_path, monkeypatch):
    fake = tmp_path / "Google Chrome"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setattr(sess, "_SYSTEM_CHROME_CANDIDATES", (fake,))
    monkeypatch.setattr(sess, "_SYSTEM_CHROME_WHICH", ())
    assert sess.find_system_chrome() == fake


def test_login_headed_chrome_required(cfg, monkeypatch):
    monkeypatch.setattr(sess, "find_system_chrome", lambda: None)
    with pytest.raises(sess.SessionError, match="No system Chrome"):
        sess.login_headed(cfg, "scholar", confirm=lambda: None, engine="chrome")


def test_login_headed_auto_uses_system_chrome(cfg, monkeypatch):
    calls: list[str] = []

    def via_chrome(*_a, **_k):
        calls.append("chrome")
        return []

    def via_pw(*_a, **_k):
        calls.append("playwright")
        return []

    monkeypatch.setattr(sess, "find_system_chrome", lambda: Path("/bin/chrome"))
    monkeypatch.setattr(sess, "_login_via_system_chrome", via_chrome)
    monkeypatch.setattr(sess, "_login_via_playwright", via_pw)
    sess.login_headed(cfg, "scholar", confirm=lambda: None, engine="auto")
    assert calls == ["chrome"]


def test_login_headed_playwright_forced(cfg, monkeypatch):
    calls: list[str] = []

    def via_chrome(*_a, **_k):
        calls.append("chrome")
        return []

    def via_pw(*_a, **_k):
        calls.append("playwright")
        return []

    monkeypatch.setattr(sess, "find_system_chrome", lambda: Path("/bin/chrome"))
    monkeypatch.setattr(sess, "_login_via_system_chrome", via_chrome)
    monkeypatch.setattr(sess, "_login_via_playwright", via_pw)
    sess.login_headed(cfg, "scholar", confirm=lambda: None, engine="playwright")
    assert calls == ["playwright"]
