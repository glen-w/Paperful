"""ensure_playwright bootstrap helpers."""

from __future__ import annotations

import pytest

from paperful import session as sess


def test_ensure_playwright_missing_package(monkeypatch):
    monkeypatch.setattr(sess, "playwright_available", lambda: False)
    with pytest.raises(sess.SessionError, match="uv sync"):
        sess.ensure_playwright(auto_install=False)


def test_ensure_playwright_needs_chromium_no_auto(monkeypatch):
    monkeypatch.setattr(sess, "playwright_available", lambda: True)
    monkeypatch.setattr(sess, "chromium_installed", lambda: False)
    with pytest.raises(sess.SessionError, match="playwright install chromium"):
        sess.ensure_playwright(auto_install=False)


def test_ensure_playwright_auto_installs(monkeypatch):
    monkeypatch.setattr(sess, "playwright_available", lambda: True)
    states = {"n": 0}

    def installed() -> bool:
        return states["n"] > 0

    monkeypatch.setattr(sess, "chromium_installed", installed)

    calls: list[list[str]] = []

    def fake_run(cmd, check):
        calls.append(cmd)
        states["n"] += 1
        return None

    monkeypatch.setattr(sess.subprocess, "run", fake_run)
    note = sess.ensure_playwright(auto_install=True)
    assert note and "Installed" in note
    assert calls and "install" in calls[0] and "chromium" in calls[0]


def test_ensure_playwright_ready(monkeypatch):
    monkeypatch.setattr(sess, "playwright_available", lambda: True)
    monkeypatch.setattr(sess, "chromium_installed", lambda: True)
    assert sess.ensure_playwright() is None
