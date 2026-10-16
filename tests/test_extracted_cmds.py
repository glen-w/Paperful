"""Behavioral tests for extracted ``*_cmd`` modules and related CLI smoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from paperful import cli, gaps_cmd, ocr_ignore_cmd, screen_cmd
from tests.conftest import make_item

runner = CliRunner()


def _console() -> Console:
    return Console(width=200, highlight=False, record=True)


@pytest.fixture
def stub_zotero(monkeypatch):
    from tests.test_cli import StubZL

    zl = StubZL()
    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: zl)
    return zl


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
        'scihub_mirrors = ["m1.test"]\n'
    )
    return p


class _QuietBackend:
    def supports_write(self) -> bool:
        return True


def test_run_screen_json_no_findings(cfg_file, stub_zotero, monkeypatch, tmp_path):
    monkeypatch.setattr("paperful.screen.screen_items", lambda *a, **k: [])
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    screen_cmd.run_screen(
        _console(),
        collection=[],
        library=True,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
        as_json=True,
        strict=False,
        apply=False,
        refresh=False,
        profile=None,
        run_config=None,
        config=cfg_file,
        fmt="",
    )
    runs = list((tmp_path / "state" / "runs").glob("*-screen.json"))
    assert len(runs) == 1
    assert json.loads(runs[0].read_text())["summary"]["findings"] == 0


def test_run_screen_strict_raises_exit(cfg_file, stub_zotero, monkeypatch):
    from paperful.screen import ScreenFinding

    monkeypatch.setattr(
        "paperful.screen.screen_items",
        lambda *a, **k: [
            ScreenFinding("I1", "retracted", "Title", "detail")
        ],
    )
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    with pytest.raises(typer.Exit) as exc:
        screen_cmd.run_screen(
            _console(),
            collection=[],
            library=True,
            year_from=None,
            year_to=None,
            item_type=[],
            limit=None,
            as_json=False,
            strict=True,
            apply=False,
            refresh=False,
            profile=None,
            run_config=None,
            config=cfg_file,
            fmt="",
        )
    assert exc.value.exit_code == 1


def test_run_screen_format_json_envelope(cfg_file, stub_zotero, monkeypatch):
    monkeypatch.setattr("paperful.screen.screen_items", lambda *a, **k: [])
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    screen_cmd.run_screen(
        _console(),
        collection=[],
        library=True,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
        as_json=False,
        strict=False,
        apply=False,
        refresh=False,
        profile=None,
        run_config=None,
        config=cfg_file,
        fmt="json",
    )


def test_run_ocr_ignore_list_empty(cfg_file, tmp_path):
    c = _console()
    ocr_ignore_cmd.run_ocr_ignore_list(c, config=cfg_file)
    assert "No ignored items" in c.export_text()


def test_run_ocr_ignore_add_and_remove(cfg_file, tmp_path):
    c = _console()
    ocr_ignore_cmd.run_ocr_ignore_add(
        c, item=["KEY1", "KEY2"], reason="test", config=cfg_file
    )
    ocr_ignore_cmd.run_ocr_ignore_list(c, config=cfg_file)
    listed = c.export_text(clear=False)
    assert "KEY1" in listed and "KEY2" in listed
    ocr_ignore_cmd.run_ocr_ignore_remove(c, item=["KEY1"], config=cfg_file)
    from paperful.ocr_ignore import OcrIgnoreList

    cfg = cli._cfg(cfg_file)
    ignores = OcrIgnoreList(cfg.ocr_ignore_path)
    assert not ignores.is_ignored("KEY1")
    assert ignores.is_ignored("KEY2")


def test_run_ocr_ignore_add_requires_item(cfg_file):
    with pytest.raises(typer.Exit) as exc:
        ocr_ignore_cmd.run_ocr_ignore_add(_console(), item=[], reason="", config=cfg_file)
    assert exc.value.exit_code == 1


def test_run_ocr_ignore_import_failures_missing_report(cfg_file):
    with pytest.raises(typer.Exit) as exc:
        ocr_ignore_cmd.run_ocr_ignore_import_failures(
            _console(), report=None, config=cfg_file
        )
    assert exc.value.exit_code == 1


def test_run_ocr_ignore_import_failures_from_report(cfg_file, tmp_path):
    report = tmp_path / "state" / "runs" / "2020-ocr.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "command": "ocr",
                "items": [
                    {"itemKey": "A", "status": "failed", "reason": "boom"},
                    {"itemKey": "B", "status": "ok"},
                ],
            }
        ),
        encoding="utf-8",
    )
    ocr_ignore_cmd.run_ocr_ignore_import_failures(
        _console(), report=report, config=cfg_file
    )
    from paperful.ocr_ignore import OcrIgnoreList

    cfg = cli._cfg(cfg_file)
    assert OcrIgnoreList(cfg.ocr_ignore_path).is_ignored("A")
    assert not OcrIgnoreList(cfg.ocr_ignore_path).is_ignored("B")


def test_run_gaps_human_counts(cfg, tmp_path):
    items = [
        make_item(key="A", has_pdf=True, doi="10.1/a"),
        make_item(key="B", has_pdf=False, has_linked_url=True, doi=None),
    ]
    emitted: list[dict] = []

    def emit_agent(payload, *, json_out, human):
        emitted.append(payload)
        if human:
            human()

    c = _console()
    gaps_cmd.run_gaps(
        c,
        cfg,
        _QuietBackend(),
        items,
        "BBNJ",
        list_missing=False,
        mode="list",
        json_out=False,
        as_json=False,
        to=None,
        include_doi_tabs=False,
        downloads_dir=None,
        re_request=False,
        emit_agent=emit_agent,
        inbox_handoff=lambda *a, **k: None,
    )
    text = c.export_text()
    assert "no stored PDF" in text
    runs = list((tmp_path / "state" / "runs").glob("*-gaps.json"))
    assert len(runs) == 1


def test_run_gaps_agent_json(cfg, tmp_path):
    items = [make_item(key="A", has_pdf=False)]
    captured: list[dict] = []

    def emit_agent(payload, *, json_out, human):
        captured.append({"json_out": json_out, "payload": payload})

    gaps_cmd.run_gaps(
        _console(),
        cfg,
        _QuietBackend(),
        items,
        "BBNJ",
        list_missing=False,
        mode="list",
        json_out=True,
        as_json=False,
        to=None,
        include_doi_tabs=False,
        downloads_dir=None,
        re_request=False,
        emit_agent=emit_agent,
        inbox_handoff=lambda *a, **k: None,
    )
    assert captured and captured[0]["json_out"] is True


def test_cli_screen_library_json(cfg_file, stub_zotero, monkeypatch, tmp_path):
    monkeypatch.setattr("paperful.screen.screen_items", lambda *a, **k: [])
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    res = runner.invoke(
        cli.app, ["screen", "-c", str(cfg_file), "--library", "--format", "json"]
    )
    assert res.exit_code == 0, res.stdout
    body = json.loads(res.stdout)
    assert body["command"] == "screen"


def test_cli_ocr_ignore_add_and_list(cfg_file, tmp_path):
    res = runner.invoke(
        cli.app,
        ["ocr-ignore", "add", "-c", str(cfg_file), "--item", "SCAN1", "--reason", "x"],
    )
    assert res.exit_code == 0, res.stdout
    res2 = runner.invoke(cli.app, ["ocr-ignore", "list", "-c", str(cfg_file)])
    assert res2.exit_code == 0
    assert "SCAN1" in res2.stdout


def test_cli_ocr_ignore_remove_requires_item(cfg_file):
    res = runner.invoke(cli.app, ["ocr-ignore", "remove", "-c", str(cfg_file)])
    assert res.exit_code == 1


def test_run_gaps_list_missing_as_json(cfg, tmp_path):
    items = [
        make_item(key="M", has_pdf=False, doi="10.1/m", url="https://example.org/p"),
    ]
    c = _console()
    gaps_cmd.run_gaps(
        c,
        cfg,
        _QuietBackend(),
        items,
        "BBNJ",
        list_missing=True,
        mode="list",
        json_out=False,
        as_json=True,
        to=None,
        include_doi_tabs=False,
        downloads_dir=None,
        re_request=False,
        emit_agent=lambda *a, **k: None,
        inbox_handoff=lambda *a, **k: None,
    )
    # as_json prints to console; verify run report exists
    runs = list((tmp_path / "state" / "runs").glob("*-gaps.json"))
    assert runs


def test_cli_screen_strict_exits_1(cfg_file, stub_zotero, monkeypatch):
    from paperful.screen import ScreenFinding

    monkeypatch.setattr(
        "paperful.screen.screen_items",
        lambda *a, **k: [ScreenFinding("I1", "retracted", "T", "d")],
    )
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    res = runner.invoke(
        cli.app, ["screen", "-c", str(cfg_file), "--library", "--strict"]
    )
    assert res.exit_code == 1
    assert "retracted" in res.stdout or "findings" in res.stdout.lower()


def test_cli_screen_json_legacy(cfg_file, stub_zotero, monkeypatch):
    monkeypatch.setattr("paperful.screen.screen_items", lambda *a, **k: [])
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    res = runner.invoke(cli.app, ["screen", "-c", str(cfg_file), "--library", "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout) == []
