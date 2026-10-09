"""Run-report witness block (optional, additive)."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.runreport import RUN_REPORT_KEYS, write_command_report
from paperful.witness import SCHEMA, attach_witness, build_witness, config_sha256


def test_config_sha256_stable_for_same_file(tmp_path: Path, cfg):
    path = tmp_path / "config.toml"
    path.write_text('email = "a@b.c"\n', encoding="utf-8")
    cfg.config_path = path
    first = config_sha256(cfg)
    second = config_sha256(cfg)
    assert first == second
    assert len(first) == 64
    path.write_text('email = "other@b.c"\n', encoding="utf-8")
    assert config_sha256(cfg) != first


def test_build_witness_shape(cfg):
    witness = build_witness(cfg, command="run")
    assert witness["schema"] == SCHEMA
    assert witness["paperful_version"]
    assert witness["config_sha256"]
    assert "llm" in witness
    assert "fetch" in witness
    assert "scope" in witness
    assert witness["command"] == "run"


def test_write_command_report_attaches_witness(cfg):
    path = write_command_report(
        cfg,
        command="coverage",
        scope="BBNJ",
        summary={"missing": 1, "write_api": None},
        items=[],
        flags={"dry_run": True},
    )
    assert path is not None
    report = json.loads(path.read_text(encoding="utf-8"))
    # write_command_report is a slim report (no sources_configured); witness is additive.
    assert report["schema"] == "paperful.run_report.v1"
    assert "witness" in report
    assert report["witness"]["schema"] == SCHEMA
    assert report["witness"]["config_sha256"]
    assert "sources_configured" in RUN_REPORT_KEYS  # freeze still lists full build_report keys


def test_attach_witness_idempotent(cfg):
    report = {"schema": "paperful.run_report.v1", "command": "run"}
    attach_witness(report, cfg)
    digest = report["witness"]["config_sha256"]
    attach_witness(report, cfg)
    assert report["witness"]["config_sha256"] == digest


def test_pack_step_records_witness_id(cfg):
    from paperful.pack import close_pack, current_id, open_pack, pack_path

    open_pack(cfg, "deep-test")
    path = write_command_report(
        cfg,
        command="coverage",
        scope="BBNJ",
        summary={"missing": 0, "write_api": None},
        items=[],
    )
    assert path is not None
    report = json.loads(path.read_text(encoding="utf-8"))
    # note_pack_step already ran inside write_run_report; re-read pack.
    pack = json.loads(pack_path(cfg, current_id(cfg)).read_text(encoding="utf-8"))
    assert pack["steps"]
    assert pack["steps"][-1]["witness_id"] == report["witness"]["config_sha256"][:12]
    close_pack(cfg)
