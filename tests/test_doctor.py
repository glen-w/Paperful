"""Doctor remediations and check helpers (no CLI)."""

from __future__ import annotations

from paperful.doctor import Check, actionable_checks, remediation_text


def test_remediation_scholar_host_vs_docker(cfg):
    ch = Check("Scholar session", "amber", "missing")
    host = remediation_text(ch, cfg, docker=False)
    dock = remediation_text(ch, cfg, docker=True)
    assert host and "uv run paperful session login scholar" in host
    assert "not inside this container" not in host
    assert dock and "not inside this container" in dock
    assert "PAPERFUL_DATA" in dock
    assert "uv run paperful session login scholar" in dock


def test_remediation_write_api_names_dedupe(cfg):
    text = remediation_text(Check("Write API", "amber", "no"), cfg)
    assert text and "dedupe --apply" in text
    assert "fix-metadata --apply" in text


def test_remediation_skips_green(cfg):
    assert remediation_text(Check("email", "green", "x@y.z"), cfg) is None


def test_actionable_checks_order(cfg):
    checks = [
        Check("email", "amber", "empty"),
        Check("Scholar session", "amber", "missing"),
        Check("out_dir", "green", "/tmp/out"),
    ]
    names = [c.name for c, _ in actionable_checks(checks, cfg, docker=False)]
    assert names == ["email", "Scholar session"]


def test_remediation_playwright(cfg):
    missing = Check("Playwright", "amber", "missing — run: uv sync")
    text = remediation_text(missing, cfg, docker=False)
    assert text and "uv sync" in text
    browsers = Check("Playwright", "amber", "package ok — Chromium installs")
    text2 = remediation_text(browsers, cfg, docker=False)
    assert text2 and "session login" in text2
