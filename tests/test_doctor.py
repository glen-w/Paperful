"""Doctor remediations and check helpers (no CLI)."""

from __future__ import annotations

from paperful.doctor import Check, actionable_checks, remediation_text


def test_remediation_zotero_branches_on_code(cfg, monkeypatch):
    down = remediation_text(
        Check("Zotero :23119", "red", "refused", code="zotero_down"), cfg, docker=False
    )
    assert down and "local mirror does not need Zotero" in down
    unresolved = remediation_text(
        Check("Zotero :23119", "red", "nodename", code="zotero_host_unresolved"),
        cfg,
        docker=False,
    )
    assert unresolved and "does not resolve" in unresolved
    assert "Start Zotero" not in unresolved
    assert "Allow other applications" in down or "enable the local API" in down

    api_off = remediation_text(
        Check("Zotero :23119", "red", "403", code="zotero_api_off"), cfg, docker=False
    )
    assert api_off and "Allow other applications" in api_off
    assert "Start Zotero" not in api_off

    bad = remediation_text(
        Check("Zotero :23119", "red", "400", code="zotero_bad_host"), cfg, docker=False
    )
    assert bad and "PAPERFUL_ZOTERO_HOST" in bad and "Host header" in bad

    monkeypatch.setenv("PAPERFUL_ZOTERO_HOST", "host.docker.internal")
    down_host = remediation_text(
        Check("Zotero :23119", "red", "refused", code="zotero_down"), cfg, docker=True
    )
    assert down_host and "not inside this container" in down_host
    assert "PAPERFUL_ZOTERO_HOST" in down_host


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


def test_remediation_mendeley_and_endnote(cfg):
    men = remediation_text(Check("Mendeley API", "red", "missing"), cfg)
    assert men and "dev.mendeley.com" in men and "session login mendeley" in men
    en = remediation_text(Check("EndNote library", "red", "missing"), cfg)
    assert en and ".enl" in en and "sdb.eni" in en


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
