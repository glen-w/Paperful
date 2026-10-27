"""PaperGuard forensics helper (mocked subprocess)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from paperful.critique_forensics import (
    MAX_FORENSICS_FINDINGS,
    paperguard_code,
    resolve_forensics_files,
    run_forensics,
)


def _report(**overrides) -> dict:
    base = {
        "overall_severity": 3,
        "integrity_score": 0.12,
        "all_findings": [
            {
                "detector_id": "A1",
                "detector_name": "Terminal Digit Distribution Analysis",
                "severity": 1,
                "summary": "Last-digit distribution is non-uniform.",
                "detail": "Column Cell_Count.",
                "p_value_adjusted": 0.01,
                "innocent_explanations": ["Instrument quantisation"],
                "evidence": {"column": "Cell_Count"},
            },
            {
                "detector_id": "B2",
                "detector_name": "GRIM",
                "severity": 3,
                "summary": "Mean is GRIM-impossible.",
                "detail": "",
                "innocent_explanations": [],
            },
            {
                "detector_id": "Z0",
                "detector_name": "Nothing",
                "severity": 0,
                "summary": "PASS row",
            },
        ],
    }
    base.update(overrides)
    return base


def _fake_run(report: dict):
    def fake_run(cmd, **_kwargs):
        out = Path(cmd[cmd.index("--output-json") + 1])
        out.write_text(json.dumps(report), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return fake_run


def test_paperguard_code_sanitizes_detector_id():
    assert paperguard_code("A1") == "paperguard_a1"
    assert paperguard_code("F-3") == "paperguard_f_3"


def test_resolve_forensics_files_file_mode_is_that_path(tmp_path: Path):
    pdf = tmp_path / "draft.pdf"
    pdf.write_bytes(b"%PDF")
    (tmp_path / "table.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert resolve_forensics_files(pdf, item_mode=False) == [pdf]


def test_resolve_forensics_files_item_mode_adds_sibling_tables(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    csv = tmp_path / "S1.csv"
    csv.write_text("a,b\n", encoding="utf-8")
    xlsx = tmp_path / "table.xlsx"
    xlsx.write_bytes(b"PK")
    (tmp_path / "notes.txt").write_text("no", encoding="utf-8")
    got = resolve_forensics_files(pdf, item_mode=True)
    names = {p.name for p in got}
    assert names == {"paper.pdf", "S1.csv", "table.xlsx"}


def test_resolve_forensics_files_missing_src():
    assert resolve_forensics_files(None, item_mode=True) == []
    assert resolve_forensics_files(Path("/no/such.pdf"), item_mode=True) == []


def test_unavailable_when_not_on_path(cfg, monkeypatch):
    monkeypatch.setattr("paperful.critique_forensics.shutil.which", lambda _: None)
    findings, meta, raw = run_forensics(cfg, files=[])
    assert meta == {"skipped": "unavailable"}
    assert raw is None
    row = findings[0]
    assert row.code == "paperguard_unavailable"
    assert row.lane == "suggested"
    assert row.severity == "info"
    assert row.source == "paperguard"


def test_no_input_when_binary_present(cfg, monkeypatch):
    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _: "/usr/bin/paperguard"
    )
    findings, meta, raw = run_forensics(cfg, files=[])
    assert meta == {"skipped": "no_input"}
    assert raw is None
    assert findings[0].code == "paperguard_no_input"
    assert findings[0].lane == "suggested"


def test_maps_findings_and_omits_integrity_score(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.pdf"
    src.write_bytes(b"%PDF")
    seen: list[list[str]] = []
    seen_env: list[dict] = []

    def fake_run(cmd, **kwargs):
        seen.append(list(cmd))
        seen_env.append(kwargs.get("env") or {})
        return _fake_run(_report())(cmd)

    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _: "/usr/bin/paperguard"
    )
    monkeypatch.setattr("paperful.critique_forensics.subprocess.run", fake_run)
    findings, meta, raw = run_forensics(
        cfg, files=[src], doi="10.1000/test.doi", offline=False
    )
    codes = {f.code for f in findings}
    assert "paperguard_a1" in codes
    assert "paperguard_b2" in codes
    assert not any(f.code == "paperguard_z0" for f in findings)
    a1 = next(f for f in findings if f.code == "paperguard_a1")
    assert a1.lane == "suggested"
    assert a1.severity == "info"
    assert a1.loc == "Cell_Count"
    assert "Instrument quantisation" in a1.detail
    assert a1.extra["paperguard_severity"] == "NOTE"
    b2 = next(f for f in findings if f.code == "paperguard_b2")
    assert b2.severity == "major"
    assert "integrity_score" not in meta
    assert meta["overall_severity"] == "SUSPICIOUS"
    assert meta["finding_count"] == 2
    assert raw and "integrity_score" in raw
    cmd = seen[0]
    assert cmd[0] == "/usr/bin/paperguard"
    assert cmd[1] == "scan"
    assert "--ml-check" not in cmd
    assert "--llm-review" not in cmd
    assert "--perplexity-check" not in cmd
    assert "--detectgpt-check" not in cmd
    assert "--check-paper-mill" not in cmd
    assert "--doi" in cmd
    assert "10.1000/test.doi" in cmd
    assert "--lang" in cmd
    assert cmd[cmd.index("--lang") + 1] == "en"
    assert seen_env[0].get("PAPERGUARD_LANG") == "en"


def test_offline_omits_doi_flag(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.pdf"
    src.write_bytes(b"%PDF")
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        return _fake_run(_report())(cmd)

    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _: "/usr/bin/paperguard"
    )
    monkeypatch.setattr("paperful.critique_forensics.subprocess.run", fake_run)
    run_forensics(cfg, files=[src], doi="10.1000/test.doi", offline=True)
    assert "--doi" not in seen[0]


def test_timeout_maps_to_failed(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.pdf"
    src.write_bytes(b"%PDF")
    cfg.critique_forensics_timeout_s = 2.0

    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="paperguard", timeout=2)

    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _: "/usr/bin/paperguard"
    )
    monkeypatch.setattr("paperful.critique_forensics.subprocess.run", fake_run)
    findings, meta, raw = run_forensics(cfg, files=[src])
    assert meta == {"skipped": "failed"}
    assert raw is None
    assert "timed out" in findings[0].detail.lower()
    assert findings[0].code == "paperguard_failed"
    assert findings[0].lane == "suggested"


def test_unparseable_json_maps_to_failed(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.pdf"
    src.write_bytes(b"%PDF")

    def fake_run(cmd, **_kwargs):
        out = Path(cmd[cmd.index("--output-json") + 1])
        out.write_text("not-json", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _: "/usr/bin/paperguard"
    )
    monkeypatch.setattr("paperful.critique_forensics.subprocess.run", fake_run)
    findings, meta, _raw = run_forensics(cfg, files=[src])
    assert meta == {"skipped": "failed"}
    assert findings[0].code == "paperguard_failed"


def test_truncates_after_cap(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.pdf"
    src.write_bytes(b"%PDF")
    hits = [
        {
            "detector_id": f"A{i}",
            "detector_name": "Hit",
            "severity": 2,
            "summary": f"row {i}",
        }
        for i in range(MAX_FORENSICS_FINDINGS + 3)
    ]
    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _: "/usr/bin/paperguard"
    )
    monkeypatch.setattr(
        "paperful.critique_forensics.subprocess.run",
        _fake_run(_report(all_findings=hits, integrity_score=None)),
    )
    findings, meta, _raw = run_forensics(cfg, files=[src])
    mapped = [f for f in findings if f.code.startswith("paperguard_a")]
    assert len(mapped) == MAX_FORENSICS_FINDINGS
    assert any(f.code == "paperguard_truncated" for f in findings)
    assert meta["finding_count"] == MAX_FORENSICS_FINDINGS + 3


def test_string_severity_labels_map(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.pdf"
    src.write_bytes(b"%PDF")
    report = _report(
        overall_severity="CONCERN",
        all_findings=[
            {
                "detector_id": "A1",
                "detector_name": "Digits",
                "severity": "NOTE",
                "summary": "mild",
            },
            {
                "detector_id": "C9",
                "detector_name": "TIVA",
                "severity": "CRITICAL",
                "summary": "strong",
            },
            {
                "detector_id": "Z0",
                "detector_name": "ok",
                "severity": "PASS",
                "summary": "drop me",
            },
        ],
    )
    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _: "/usr/bin/paperguard"
    )
    monkeypatch.setattr("paperful.critique_forensics.subprocess.run", _fake_run(report))
    findings, meta, _raw = run_forensics(cfg, files=[src])
    by_code = {f.code: f for f in findings}
    assert by_code["paperguard_a1"].severity == "info"
    assert by_code["paperguard_c9"].severity == "major"
    assert "paperguard_z0" not in by_code
    assert meta["overall_severity"] == "CONCERN"


def test_detector_results_fallback_when_all_findings_empty(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.pdf"
    src.write_bytes(b"%PDF")
    report = {
        "overall_severity": 2,
        "all_findings": [],
        "detector_results": [
            {
                "detector_id": "A1",
                "findings": [
                    {
                        "detector_id": "A1",
                        "detector_name": "Terminal Digit",
                        "severity": 2,
                        "summary": "from nested block",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _: "/usr/bin/paperguard"
    )
    monkeypatch.setattr("paperful.critique_forensics.subprocess.run", _fake_run(report))
    findings, meta, _raw = run_forensics(cfg, files=[src])
    assert any(f.code == "paperguard_a1" for f in findings)
    assert meta["finding_count"] == 1


def test_nonzero_exit_without_json_is_failed(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.pdf"
    src.write_bytes(b"%PDF")

    def fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom")

    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _: "/usr/bin/paperguard"
    )
    monkeypatch.setattr("paperful.critique_forensics.subprocess.run", fake_run)
    findings, meta, raw = run_forensics(cfg, files=[src])
    assert meta == {"skipped": "failed"}
    assert raw is None
    assert "boom" in findings[0].detail


def test_item_mode_passes_sibling_tables_as_minus_f(cfg, tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    csv = tmp_path / "S1.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        return _fake_run(_report())(cmd)

    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _: "/usr/bin/paperguard"
    )
    monkeypatch.setattr("paperful.critique_forensics.subprocess.run", fake_run)
    files = resolve_forensics_files(pdf, item_mode=True)
    run_forensics(cfg, files=files)
    cmd = seen[0]
    assert "-f" in cmd
    assert str(pdf) in cmd
    assert str(csv) in cmd
