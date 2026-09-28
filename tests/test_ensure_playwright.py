"""ensure_playwright bootstrap helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from paperful import session as sess


def test_chromium_installed_uses_dry_run_not_sync_driver(monkeypatch, tmp_path):
    """Avoid sync_playwright() — it leaks TargetClosedError on later probes."""
    monkeypatch.setattr(sess, "playwright_available", lambda: True)
    chrome_dir = tmp_path / "chromium-999"
    chrome_dir.mkdir()
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Chrome for Testing (playwright chromium v999)\n"
                f"  Install location:    {chrome_dir}\n"
                "FFmpeg\n"
                f"  Install location:    {tmp_path / 'ffmpeg'}\n"
            ),
        )

    monkeypatch.setattr(sess.subprocess, "run", fake_run)
    assert sess.chromium_installed() is True
    assert calls and "--dry-run" in calls[0] and "chromium" in calls[0]

    def missing_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Chrome for Testing\n"
                f"  Install location:    {tmp_path / 'missing-chromium'}\n"
            ),
        )

    monkeypatch.setattr(sess.subprocess, "run", missing_run)
    assert sess.chromium_installed() is False


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
