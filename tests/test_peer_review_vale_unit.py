"""Vale helper and failure paths (mocked subprocess)."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from paperful.critique_extract import ExtractedDoc
from paperful.critique_vale import _alerts_from_json, _int, run_vale


def _doc(text: str) -> ExtractedDoc:
    return ExtractedDoc(
        text=text,
        format="txt",
        paragraphs=[text],
        finding="ok",
        loc_kind="paragraph",
    )


def test_alerts_from_json_accepts_top_level_list():
    raw = [{"Check": "House.Terms", "Message": "Avoid jargon", "Severity": "warning"}]
    alerts = _alerts_from_json(raw)
    assert len(alerts) == 1
    assert alerts[0]["Check"] == "House.Terms"


def test_int_parses_positive_only():
    assert _int("3") == 3
    assert _int(0) is None
    assert _int("x") is None


def test_vale_empty_stdout_is_clean_run(cfg, tmp_path, monkeypatch):
    ini = tmp_path / ".vale.ini"
    ini.write_text("StylesPath = styles\n", encoding="utf-8")
    cfg.critique_vale_config = ini

    def fake_run(*_a, **_k):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("paperful.critique_vale.shutil.which", lambda _: "/bin/vale")
    monkeypatch.setattr("paperful.critique_vale.subprocess.run", fake_run)
    findings, meta = run_vale(cfg, _doc("Clean prose here."))
    assert findings == []
    assert meta.get("alert_count") == 0


def test_vale_timeout_maps_to_failed(cfg, tmp_path, monkeypatch):
    ini = tmp_path / ".vale.ini"
    ini.write_text("StylesPath = styles\n", encoding="utf-8")
    cfg.critique_vale_config = ini
    cfg.critique_vale_timeout_s = 2.0

    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="vale", timeout=2)

    monkeypatch.setattr("paperful.critique_vale.shutil.which", lambda _: "/bin/vale")
    monkeypatch.setattr("paperful.critique_vale.subprocess.run", fake_run)
    findings, meta = run_vale(cfg, _doc("Some text."))
    assert meta == {"skipped": "failed"}
    row = next(f for f in findings if f.code == "vale_failed")
    assert "timed out" in row.detail.lower()


def test_vale_unparseable_json_maps_to_failed(cfg, tmp_path, monkeypatch):
    ini = tmp_path / ".vale.ini"
    ini.write_text("StylesPath = styles\n", encoding="utf-8")
    cfg.critique_vale_config = ini

    def fake_run(*_a, **_k):
        return SimpleNamespace(returncode=0, stdout="not-json", stderr="")

    monkeypatch.setattr("paperful.critique_vale.shutil.which", lambda _: "/bin/vale")
    monkeypatch.setattr("paperful.critique_vale.subprocess.run", fake_run)
    findings, meta = run_vale(cfg, _doc("Some text."))
    assert meta == {"skipped": "failed"}
    assert any(f.code == "vale_failed" for f in findings)


def test_vale_bad_exit_without_stdout(cfg, tmp_path, monkeypatch):
    ini = tmp_path / ".vale.ini"
    ini.write_text("StylesPath = styles\n", encoding="utf-8")
    cfg.critique_vale_config = ini

    def fake_run(*_a, **_k):
        return SimpleNamespace(returncode=2, stdout="", stderr="config missing")

    monkeypatch.setattr("paperful.critique_vale.shutil.which", lambda _: "/bin/vale")
    monkeypatch.setattr("paperful.critique_vale.subprocess.run", fake_run)
    findings, meta = run_vale(cfg, _doc("Some text."))
    assert meta == {"skipped": "failed"}
    row = next(f for f in findings if f.code == "vale_failed")
    assert "config missing" in row.detail
