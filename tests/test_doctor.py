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


def test_remediation_rg_and_twenty(cfg):
    rg = remediation_text(
        Check("ResearchGate request", "amber", "handoff-only", code="rg_handoff"),
        cfg,
    )
    assert rg and "vault click" in rg.lower()
    tw = remediation_text(
        Check("Twenty", "amber", "no key", code="twenty_key"),
        cfg,
    )
    assert tw and "TWENTY_API_KEY" in tw and "twenty lookup" in tw


def test_remediation_vale(cfg):
    text = remediation_text(
        Check("vale", "amber", "missing — optional for critique house style"),
        cfg,
    )
    assert text and "vale.sh" in text
    assert "vale sync" in text
    assert remediation_text(Check("vale", "green", "on PATH"), cfg) is None


def test_remediation_playwright(cfg):
    missing = Check("Playwright", "amber", "missing — run: uv sync")
    text = remediation_text(missing, cfg, docker=False)
    assert text and "uv sync" in text
    browsers = Check("Playwright", "amber", "package ok — Chromium installs")
    text2 = remediation_text(browsers, cfg, docker=False)
    assert text2 and "session login" in text2


def test_core_check_green_optional_or_keyed(cfg):
    from paperful.doctor import run_checks

    cfg.core_api_key = ""
    by_name = {c.name: c for c in run_checks(cfg, zl=None)}
    assert by_name["CORE"].status == "green"
    assert "optional" in by_name["CORE"].detail.lower()

    cfg.core_api_key = "test-key"
    by_name = {c.name: c for c in run_checks(cfg, zl=None)}
    assert by_name["CORE"].status == "green"
    assert "set" in by_name["CORE"].detail.lower()
    assert remediation_text(by_name["CORE"], cfg) is None


def test_osf_signal_counts_recent_misses_only(tmp_path):
    import time

    from paperful.osf_signal import MIN_OSF_MISSES, osf_signal
    from paperful.store import Manifest, Record, STATUS_NOT_FOUND, STATUS_OK

    manifest = Manifest(tmp_path / "manifest.jsonl")
    for i in range(MIN_OSF_MISSES):
        manifest.write(
            Record(itemKey=f"O{i}", status=STATUS_NOT_FOUND, url=f"https://osf.io/preprints/x{i}")
        )
    manifest.write(Record(itemKey="OLD", status=STATUS_NOT_FOUND, url="https://osf.io/old"))
    manifest.records["OLD"].ts = time.time() - 200 * 86400  # write() stamps now; age it after
    manifest.write(Record(itemKey="HAVE", status=STATUS_OK, url="https://osf.io/have"))
    manifest.write(Record(itemKey="ELSE", status=STATUS_NOT_FOUND, attempts=["unpaywall:not_found"]))
    sig = osf_signal(manifest)
    assert (sig.misses, sig.osf) == (MIN_OSF_MISSES + 1, MIN_OSF_MISSES)
    assert sig.meaningful


def test_osf_check_quiet_without_a_manifest_and_green_below_the_bar(tmp_path):
    from paperful.config import Config
    from paperful.doctor import _osf_check
    from paperful.store import Manifest, Record, STATUS_NOT_FOUND

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    assert _osf_check(cfg) is None
    manifest = Manifest(cfg.manifest_path)
    manifest.write(Record(itemKey="A", status=STATUS_NOT_FOUND, url="https://osf.io/a"))
    check = _osf_check(cfg)
    assert check.status == "green" and "no OSF source needed" in check.detail


def test_osf_check_amber_when_the_demand_bar_is_met(tmp_path):
    from paperful.config import Config
    from paperful.doctor import _osf_check
    from paperful.osf_signal import MIN_OSF_MISSES
    from paperful.store import Manifest, Record, STATUS_NOT_FOUND

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    manifest = Manifest(cfg.manifest_path)
    for i in range(MIN_OSF_MISSES):
        manifest.write(
            Record(itemKey=f"O{i}", status=STATUS_NOT_FOUND, url=f"https://psyarxiv.com/x{i}")
        )
    check = _osf_check(cfg)
    assert check is not None
    assert check.status == "amber"
    assert "enough signal to build a thin OSF source" in check.detail
    assert f"{MIN_OSF_MISSES} of {MIN_OSF_MISSES}" in check.detail
