"""Behavioral tests for extracted ``*_cmd`` modules and related CLI smoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from paperful import cli, cli_runtime, gaps_cmd, ocr_ignore_cmd, screen_cmd
from tests.conftest import make_item

runner = CliRunner()


def _console() -> Console:
    return Console(width=200, highlight=False, record=True)


@pytest.fixture
def stub_zotero(monkeypatch):
    from tests.conftest import patch_cli_runtime
    from tests.test_cli import StubZL

    zl = StubZL()
    patch_cli_runtime(monkeypatch, ZoteroLocal=lambda *a, **k: zl)
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


def test_run_screen_human_findings_table(cfg_file, stub_zotero, monkeypatch):
    from paperful.screen import ScreenFinding

    monkeypatch.setattr(
        "paperful.screen.screen_items",
        lambda *a, **k: [ScreenFinding("I1", "retracted", "Long title here", "detail")],
    )
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    c = _console()
    screen_cmd.run_screen(
        c,
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
        fmt="",
    )
    assert "retracted" in c.export_text()


def test_run_screen_apply_calls_apply_screen(cfg_file, stub_zotero, monkeypatch):
    from paperful.screen import ScreenFinding

    finding = ScreenFinding("I1", "retracted", "T", "d")
    monkeypatch.setattr(
        "paperful.screen.screen_items", lambda *a, **k: [finding]
    )
    applied: list[int] = []

    def fake_apply(backend, cfg, items, findings):
        applied.append(len(findings))
        return 1

    monkeypatch.setattr("paperful.screen.apply_screen", fake_apply)
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
        apply=True,
        refresh=False,
        profile=None,
        run_config=None,
        config=cfg_file,
        fmt="",
    )
    assert applied == [1]


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


def test_run_gaps_list_missing_human_table(cfg, tmp_path, monkeypatch):
    items = [make_item(key="M", has_pdf=False, doi="10.1/m")]
    monkeypatch.setattr(
        "paperful.handoff.list_missing_pdfs",
        lambda items, manifest, **k: [
            __import__("paperful.handoff", fromlist=["MissingPdf"]).MissingPdf(
                key="M",
                title="T",
                doi="10.1/m",
                url="",
                hint="",
                miss_surface="",
                miss_plain="",
                miss_detail="",
                oa_status="",
                license="",
                version="",
                scholar_url="",
                request_url="",
            )
        ],
    )
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
        as_json=False,
        to=None,
        include_doi_tabs=False,
        downloads_dir=None,
        re_request=False,
        emit_agent=lambda *a, **k: None,
        inbox_handoff=lambda *a, **k: None,
    )
    assert "missing PDF" in c.export_text()


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


def test_run_attach_empty_pending(cfg_file, stub_zotero, monkeypatch):
    from paperful.attach_cmd import run_attach

    monkeypatch.setattr(
        "paperful.cli_runtime._connect",
        lambda cfg, quiet=False: _QuietBackend(),
    )
    c = _console()
    run_attach(
        c,
        item=[],
        file=None,
        config=cfg_file,
        limit=None,
        allow_pdf_doi_mismatch=False,
        allow_short_pdf=False,
    )
    assert "Attached 0/0" in c.export_text()


def test_run_versions_dry_run_empty(cfg_file, stub_zotero, monkeypatch):
    from paperful.versions_cmd import run_versions

    class Backend(_QuietBackend):
        def items_in_scope(self, keys):
            return []

        def collections(self):
            return []

    monkeypatch.setattr(
        "paperful.cli_runtime._connect", lambda cfg, quiet=False: Backend()
    )
    monkeypatch.setattr(
        "paperful.cli_runtime._load_scope",
        lambda *a, **k: type("L", (), {"items": [], "label": "library"})(),
    )
    run_versions(
        _console(),
        collection=[],
        library=True,
        dry_run=True,
        apply=None,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
        as_json=True,
        profile=None,
        run_config=None,
        config=cfg_file,
    )


def test_run_refs_gap_empty_scope(cfg_file, stub_zotero, monkeypatch, tmp_path):
    from paperful.refs_gap_cmd import run_refs_gap

    class Backend(_QuietBackend):
        def items_in_scope(self, keys):
            return []

    monkeypatch.setattr(
        "paperful.cli_runtime._connect",
        lambda cfg, quiet=False: Backend(),
    )
    monkeypatch.setattr(
        "paperful.cli_runtime._load_scope",
        lambda *a, **k: type("L", (), {"items": [], "label": "library"})(),
    )
    run_refs_gap(
        _console(),
        collection=[],
        library=True,
        year_from=None,
        year_to=None,
        item_type=[],
        item=[],
        pdf=[],
        dedupe_scope="library",
        profile=None,
        run_config=None,
        config=cfg_file,
        fmt="json",
    )


def test_run_coverage_empty_file(cfg_file, stub_zotero, monkeypatch, tmp_path):
    from paperful.coverage_cmd import run_coverage

    src = tmp_path / "dois.txt"
    src.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "paperful.cli_runtime._connect",
        lambda cfg, quiet=False: _QuietBackend(),
    )
    run_coverage(
        _console(),
        collection=["BBNJ"],
        from_note=None,
        from_file=src,
        profile=None,
        run_config=None,
        config=cfg_file,
        fmt="json",
    )


def test_run_export_library_ris(cfg_file, stub_zotero, monkeypatch, tmp_path):
    from paperful.export_cmd import run_export_library

    class Backend(_QuietBackend):
        def items_in_scope(self, keys):
            return []

        def collections(self):
            return []

    monkeypatch.setattr(
        "paperful.cli_runtime._connect", lambda cfg, quiet=False: Backend()
    )
    monkeypatch.setattr(
        "paperful.cli_runtime._load_scope",
        lambda *a, **k: type("L", (), {"items": [], "label": "library"})(),
    )
    dest = tmp_path / "out.ris"
    run_export_library(
        _console(),
        dest=dest,
        fmt="ris",
        collection=[],
        library=True,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
        pdfs=False,
        config=cfg_file,
    )
    assert dest.is_file()
