"""CLI smoke via typer's CliRunner - Zotero is stubbed, no network."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from paperful import cli
from paperful.store import (
    STATUS_ATTACH_FAILED,
    STATUS_ATTACHED,
    STATUS_NOT_FOUND,
    STATUS_OK,
    Manifest,
    Record,
)
from paperful.zot import Collection

runner = CliRunner()


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    """Rich returns 80x25 for dumb/non-tty terminals unless both dimensions are fixed; widen so cells are not ellipsised."""
    from rich.console import Console

    monkeypatch.setattr(cli, "console", Console(highlight=False, width=250, height=100))


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
        'scihub_mirrors = ["m1.test"]\n'
    )
    return p


class StubZL:
    def __init__(self):
        self.cols = {
            "A": Collection("A", "BBNJ", None, "BBNJ", "BBNJ"),
            "B": Collection("B", "EIA / SEA", "A", "BBNJ/EIA _ SEA", "BBNJ/EIA / SEA"),
        }

    def ping(self):
        return {"zotero_version": "10.0.1", "api_version": "3", "supports_write": True}

    def collections(self):
        return self.cols

    def collection_counts(self):
        return {"A": (5, 3), "B": (2, 1)}

    def resolve_collection(self, spec):
        for c in self.cols.values():
            if spec in (c.key, c.name, c.raw_path):
                return c
        raise LookupError(f"No collection matching '{spec}'")

    def subtree_keys(self, root):
        return [root.key] + [c.key for c in self.cols.values() if c.parent == root.key]

    def items_lacking_pdf(self, keys, upgrade_linked=False):
        from tests.conftest import make_item

        return [
            make_item(key="I1", collection_paths=["BBNJ"]),
            make_item(key="I2", doi=None, collection_paths=["BBNJ/EIA _ SEA"]),
        ]

    def items_in_scope(self, keys):
        from tests.conftest import make_item

        return [make_item(key="I1", collection_paths=["BBNJ"], has_pdf=True)]

    def count_linked_url_only(self, keys):
        return 1


@pytest.fixture
def stub_zotero(monkeypatch):
    zl = StubZL()
    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: zl)
    return zl


def test_version():
    res = runner.invoke(cli.app, ["version"])
    assert res.exit_code == 0 and res.stdout.strip()


def test_run_requires_scope(cfg_file):
    res = runner.invoke(cli.app, ["run", "-c", str(cfg_file)])
    assert res.exit_code == 1 and "--collection" in res.stdout


def test_collections_table(cfg_file, stub_zotero):
    res = runner.invoke(cli.app, ["collections", "-c", str(cfg_file)])
    assert res.exit_code == 0
    assert (
        "BBNJ" in res.stdout
        and "EIA / SEA" in res.stdout
        and "Zotero 10.0.1" in res.stdout
    )


def test_run_dry_run_lists_items_and_writes_nothing(cfg_file, stub_zotero, tmp_path):
    res = runner.invoke(
        cli.app,
        ["run", "-c", str(cfg_file), "--collection", "BBNJ/EIA / SEA", "--dry-run"],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    assert (
        "2 items without PDF" in res.stdout
        and "I1" in res.stdout
        and "10.1000/test.doi" in res.stdout
    )
    assert "Would-hit" in res.stdout and "linked URL only" in res.stdout
    assert "scihub" not in res.stdout.split("Sources:")[-1].split("\n")[0]
    assert "legal grey zone" not in res.stdout
    assert not (tmp_path / "state" / "manifest.jsonl").exists()
    assert not list((tmp_path / "out").rglob("*.pdf"))


def test_run_scihub_opt_in_appends_and_prints_disclaimer(cfg_file, stub_zotero):
    from paperful.config import SCIHUB_DISCLAIMER

    res = runner.invoke(
        cli.app,
        ["run", "-c", str(cfg_file), "--library", "--dry-run", "--scihub"],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    sources_line = res.stdout.split("Sources:")[-1].split("\n")[0]
    assert sources_line.strip().endswith("scihub")
    assert SCIHUB_DISCLAIMER in res.stdout


def test_run_scihub_via_sources_override_prints_disclaimer(cfg_file, stub_zotero):
    from paperful.config import SCIHUB_DISCLAIMER

    res = runner.invoke(
        cli.app,
        [
            "run",
            "-c",
            str(cfg_file),
            "--library",
            "--dry-run",
            "--sources",
            "unpaywall,scihub",
        ],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    assert SCIHUB_DISCLAIMER in res.stdout
    assert "Sources: unpaywall, scihub" in res.stdout


def test_source_list_override_and_scihub_flag():
    from paperful.cli import _source_list
    from paperful.config import EOI_SOURCES, Config

    cfg = Config(sources=["unpaywall", "ezproxy"])
    assert _source_list(cfg, None, False) == ["unpaywall", "ezproxy"]
    assert _source_list(cfg, None, True) == ["unpaywall", "ezproxy", "scihub"]
    assert _source_list(cfg, "unpaywall,scihub", False) == ["unpaywall", "scihub"]
    assert _source_list(cfg, "unpaywall", True) == ["unpaywall", "scihub"]
    assert _source_list(cfg, "unpaywall,scihub", True) == ["unpaywall", "scihub"]
    assert _source_list(cfg, None, False, preset="eoi") == EOI_SOURCES
    assert "scholar" not in _source_list(cfg, "eoi", False)


def test_run_unknown_collection(cfg_file, stub_zotero):
    res = runner.invoke(
        cli.app, ["run", "-c", str(cfg_file), "-C", "nope", "--dry-run"]
    )
    assert res.exit_code == 1 and "No collection matching" in res.stdout


def test_run_skips_already_handled_items(cfg_file, stub_zotero, tmp_path):
    m = Manifest(tmp_path / "state" / "manifest.jsonl")
    m.write(Record(itemKey="I1", status=STATUS_ATTACHED))
    m.write(Record(itemKey="I2", status=STATUS_NOT_FOUND))
    res = runner.invoke(
        cli.app,
        ["run", "-c", str(cfg_file), "--library", "--dry-run"],
        env={"COLUMNS": "200"},
    )
    assert "2 already handled" in res.stdout and "0 to process" in res.stdout
    res2 = runner.invoke(
        cli.app,
        ["run", "-c", str(cfg_file), "--library", "--dry-run", "--retry-failed"],
        env={"COLUMNS": "200"},
    )
    assert "1 to process" in res2.stdout


def test_zotero_unreachable_exits_2(cfg_file, monkeypatch):
    class Down:
        def ping(self):
            raise ConnectionError("Zotero local API is disabled.")

    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: Down())
    res = runner.invoke(cli.app, ["collections", "-c", str(cfg_file)])
    assert (
        res.exit_code == 2
        and "disabled" in res.stdout
        and "paperful doctor" in res.stdout
    )


def test_report_empty_and_populated(cfg_file, tmp_path):
    res = runner.invoke(cli.app, ["report", "-c", str(cfg_file)])
    assert res.exit_code == 0 and "empty" in res.stdout
    m = Manifest(tmp_path / "state" / "manifest.jsonl")
    m.write(
        Record(
            itemKey="K1",
            status=STATUS_OK,
            source="scihub",
            title="Paper one",
            doi="10.1/a",
            path="/x/a.pdf",
        )
    )
    m.write(
        Record(
            itemKey="K2",
            status=STATUS_NOT_FOUND,
            title="Paper two",
            doi="10.1/b",
            attempts=["scihub:not_found"],
        )
    )
    res = runner.invoke(
        cli.app, ["report", "-c", str(cfg_file), "--not-found"], env={"COLUMNS": "200"}
    )
    assert res.exit_code == 0
    assert (
        "scihub=1" in res.stdout
        and "Paper two" in res.stdout
        and "10.1/b" in res.stdout
    )


def test_scholar_command_missing_cookies(cfg_file, monkeypatch):
    monkeypatch.setattr("webbrowser.open", lambda url: None)
    res = runner.invoke(cli.app, ["scholar", "-c", str(cfg_file), "--no-open"])
    assert res.exit_code == 2 and "No session yet" in res.stdout
    assert "mv ~/Desktop/cookies.txt" in res.stdout
    assert "session login" in res.stdout


def test_scholar_command_session_ok(cfg_file, tmp_path, monkeypatch):
    cookie_file = tmp_path / "state" / "scholar-cookies.txt"
    cookie_file.parent.mkdir(parents=True)
    cookie_file.write_text(".google.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n")
    monkeypatch.setattr("webbrowser.open", lambda url: None)
    monkeypatch.setattr(
        "paperful.sources.scholar.session_ok", lambda ctx: (True, "ok (200)")
    )
    res = runner.invoke(cli.app, ["scholar", "-c", str(cfg_file), "--no-open"])
    assert res.exit_code == 0 and "Session OK" in res.stdout


def test_scholar_command_session_not_ready(cfg_file, tmp_path, monkeypatch):
    cookie_file = tmp_path / "state" / "scholar-cookies.txt"
    cookie_file.parent.mkdir(parents=True)
    cookie_file.write_text(".google.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n")
    monkeypatch.setattr("webbrowser.open", lambda url: None)
    monkeypatch.setattr(
        "paperful.sources.scholar.session_ok",
        lambda ctx: (
            False,
            "blocked or CAPTCHA (HTTP 429 at https://www.google.com/sorry/index)",
        ),
    )
    res = runner.invoke(cli.app, ["scholar", "-c", str(cfg_file), "--no-open"])
    assert res.exit_code == 2
    assert "Session not ready" in res.stdout
    assert "not cookies alone" in res.stdout
    assert "session login scholar" in res.stdout


def test_session_status_empty_vault(cfg_file):
    res = runner.invoke(cli.app, ["session", "status", "-c", str(cfg_file)])
    assert res.exit_code == 0
    assert "Ready:" in res.stdout
    assert "False" in res.stdout


def test_session_status_probe_scholar(cfg_file, tmp_path, monkeypatch):
    cookie_file = tmp_path / "state" / "scholar-cookies.txt"
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text(".google.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n")
    monkeypatch.setattr(
        "paperful.sources.scholar.session_ok", lambda ctx: (True, "ok (200)")
    )
    res = runner.invoke(
        cli.app, ["session", "status", "--probe", "-c", str(cfg_file)]
    )
    assert res.exit_code == 0 and "Session OK" in res.stdout


def test_session_login_unknown_slot(cfg_file):
    res = runner.invoke(cli.app, ["session", "login", "ftp", "-c", str(cfg_file)])
    assert res.exit_code == 1
    assert "Unknown slot" in res.stdout


def test_mirrors_command(cfg_file, monkeypatch):
    from paperful.config import SCIHUB_DISCLAIMER

    monkeypatch.setattr(
        cli,
        "ping_mirrors",
        lambda ctx: [("m1.test", "HTTP 200"), ("m2.test", "down (ConnectError)")],
    )
    res = runner.invoke(cli.app, ["mirrors", "-c", str(cfg_file)])
    assert res.exit_code == 0 and "m1.test" in res.stdout and "down" in res.stdout
    assert SCIHUB_DISCLAIMER in res.stdout
    assert "Sci-Hub is off until" in res.stdout


def test_doctor_ok(cfg_file, stub_zotero):
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file)])
    assert res.exit_code == 0
    assert "green" in res.stdout and "Zotero :23119" in res.stdout
    assert "pdftotext" in res.stdout
    assert "Grey playbooks" in res.stdout
    assert "UNGA/undocs" in res.stdout


def test_doctor_scholar_session_amber_without_vault(cfg_file, stub_zotero):
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file)])
    assert res.exit_code == 0
    assert "Scholar session" in res.stdout
    assert "paperful session login scholar" in res.stdout


def test_doctor_scholar_session_green_with_cookies(cfg_file, tmp_path, stub_zotero):
    cookie = tmp_path / "state" / "scholar-cookies.txt"
    cookie.parent.mkdir(parents=True, exist_ok=True)
    cookie.write_text(".google.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n")
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file)])
    assert res.exit_code == 0
    assert "Scholar session" in res.stdout
    assert "session login scholar" not in res.stdout


def test_doctor_pdftotext_amber(cfg_file, stub_zotero, monkeypatch):
    monkeypatch.setattr("paperful.doctor.shutil.which", lambda name: None)
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file)])
    assert res.exit_code == 0
    assert "pdftotext" in res.stdout
    assert "amber" in res.stdout


def test_doctor_zotero_red(cfg_file, monkeypatch):
    class Down:
        def ping(self):
            raise ConnectionError("Zotero local API is disabled.")

    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: Down())
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file)])
    assert res.exit_code == 2 and "red" in res.stdout


def test_report_json(cfg_file, tmp_path):
    m = Manifest(tmp_path / "state" / "manifest.jsonl")
    m.write(Record(itemKey="K1", status=STATUS_OK, source="unpaywall", doi="10.1/a"))
    m.write(
        Record(
            itemKey="K2", status=STATUS_ATTACH_FAILED, reason="storage quota exceeded"
        )
    )
    res = runner.invoke(cli.app, ["report", "-c", str(cfg_file), "--json"])
    assert res.exit_code == 0
    import json

    data = json.loads(res.stdout)
    assert data["counts"]["ok"] == 1
    assert data["no_doi"] == 1
    assert data["attach_failed_by_code"].get("quota") == 1


def test_report_last_run(cfg_file, tmp_path):
    import json

    last = {
        "schema": "paperful.run_report.v1",
        "command": "run",
        "summary": {
            "pdfs_downloaded": 3,
            "attached": 2,
            "attach_failed": 0,
            "fields_corrected": 1,
            "fields_corrected_by_kind": {"doi_swap": 1},
            "identifiers_verified": 0,
            "sources_checked": {"unpaywall": {"found": 2, "not_found": 1}},
            "errors_by_type": {"captcha": 1},
            "by_source": {"unpaywall": 3},
            "skipped_manifest": 0,
            "linked_url_skipped": 0,
            "not_found": 0,
            "no_identifier": 0,
        },
        "paths": {
            "out_dir": str(tmp_path / "out"),
            "manifest": str(tmp_path / "state" / "manifest.jsonl"),
        },
        "items": [],
    }
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "last-run.json").write_text(json.dumps(last))
    res = runner.invoke(cli.app, ["report", "-c", str(cfg_file), "--last-run"])
    assert res.exit_code == 0
    assert "PDFs downloaded" in res.stdout and "3" in res.stdout
    assert "Fields corrected" in res.stdout
    assert "Sources checked" in res.stdout
    assert "captcha=1" in res.stdout


def test_attach_command_uses_pending_records(
    cfg_file, stub_zotero, tmp_path, monkeypatch
):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    m = Manifest(tmp_path / "state" / "manifest.jsonl")
    m.write(Record(itemKey="K1", status=STATUS_OK, path=str(pdf)))
    m.write(Record(itemKey="K2", status=STATUS_ATTACHED, path=str(pdf)))

    class FakeAttacher:
        def __init__(self, cfg, zl):
            pass

        def supports_write(self):
            return True

        def attach(self, key, path, title=None):
            from paperful.attach import AttachResult

            return AttachResult(True, "ATT", "success")

    monkeypatch.setattr(cli, "Attacher", FakeAttacher)
    res = runner.invoke(cli.app, ["attach", "-c", str(cfg_file)])
    assert (
        res.exit_code == 0
        and "1 PDFs to attach" in res.stdout
        and "Attached 1/1" in res.stdout
    )
    assert (
        Manifest(tmp_path / "state" / "manifest.jsonl").get("K1").status
        == STATUS_ATTACHED
    )


def test_lint_json(cfg_file, stub_zotero, monkeypatch):
    monkeypatch.setattr("paperful.lint.lint_items", lambda *a, **k: [])
    res = runner.invoke(cli.app, ["lint", "-c", str(cfg_file), "--library", "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout) == []


def test_lint_strict_exits_1(cfg_file, stub_zotero, monkeypatch):
    from paperful.lint import Finding

    monkeypatch.setattr(
        "paperful.lint.lint_items",
        lambda *a, **k: [Finding("I1", "missing_doi", "T", "no DOI")],
    )
    res = runner.invoke(cli.app, ["lint", "-c", str(cfg_file), "--library", "--strict"])
    assert res.exit_code == 1
    assert "missing_doi" in res.stdout


def test_fix_metadata_dry_run(cfg_file, stub_zotero, tmp_path, monkeypatch):
    monkeypatch.setattr("paperful.lint.lint_item", lambda *a, **k: [])
    monkeypatch.setattr("paperful.metadata.propose_patch", lambda *a, **k: None)
    res = runner.invoke(cli.app, ["fix-metadata", "-c", str(cfg_file), "--library"])
    assert res.exit_code == 0
    assert "Dry-run" in res.stdout
    assert "0 proposed patches" in res.stdout
    assert (tmp_path / "state" / "metadata-patches.jsonl").exists()


def test_fix_metadata_apply(cfg_file, stub_zotero, monkeypatch):
    from paperful.metadata import Patch

    patch = Patch(
        itemKey="I1",
        title="T",
        before={"doi": None},
        after={"doi": "10.1/x"},
        source="swap",
    )
    monkeypatch.setattr("paperful.lint.lint_item", lambda *a, **k: [])
    monkeypatch.setattr("paperful.metadata.propose_patch", lambda *a, **k: patch)
    seen: list = []

    def fake_apply(backend, patches):
        seen.append(list(patches))
        return 1, []

    monkeypatch.setattr("paperful.metadata.apply_patches", fake_apply)
    res = runner.invoke(
        cli.app, ["fix-metadata", "-c", str(cfg_file), "--library", "--apply"]
    )
    assert res.exit_code == 0, res.stdout
    assert seen and seen[0][0].after["doi"] == "10.1/x"


def test_mendeley_manager_exits(cfg_file, tmp_path):
    cfg_file.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
        'manager = "mendeley"\n'
    )
    res = runner.invoke(cli.app, ["collections", "-c", str(cfg_file)])
    assert res.exit_code == 1
    assert "not implemented" in res.stdout
