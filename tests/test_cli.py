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
            make_item(key="I1", year=2024, collection_paths=["BBNJ"]),
            make_item(key="I2", year=2019, doi=None, collection_paths=["BBNJ/EIA _ SEA"]),
        ]

    def items_in_scope(self, keys):
        from tests.conftest import make_item

        return [
            make_item(key="I1", year=2024, collection_paths=["BBNJ"], has_pdf=True),
            make_item(
                key="I2",
                year=2019,
                doi=None,
                collection_paths=["BBNJ/EIA _ SEA"],
                has_linked_url=True,
            ),
        ]

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


def test_run_uses_mirror_when_manager_is_down(cfg_file, tmp_path, monkeypatch):
    class Down:
        def __init__(self, *args, **kwargs):
            pass

        def ping(self):
            raise ConnectionError("connection refused")

    monkeypatch.setattr(cli, "ZoteroLocal", Down)
    folder = tmp_path / "out" / "BBNJ" / "Smith - 2019 - Title -- ITEM0001"
    folder.mkdir(parents=True)
    (folder / "record.json").write_text(
        json.dumps(
            {
                "item_key": "ITEM0001",
                "item_type": "journalArticle",
                "title": "Mirror title",
                "doi": "10.1000/mirror",
                "year": 2019,
                "collection_paths": ["BBNJ"],
            }
        )
    )
    held = folder.parent / "Held - 2020 - Done -- ITEM0002"
    held.mkdir()
    (held / "record.json").write_text(json.dumps({"item_key": "ITEM0002", "title": "Has PDF"}))
    (held / "paper.pdf").write_bytes(b"%PDF-1.4")
    res = runner.invoke(
        cli.app,
        ["run", "-c", str(cfg_file), "--library", "--dry-run"],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    assert "not reachable" in res.stdout
    assert "ITEM0001" in res.stdout
    assert "ITEM0002" not in res.stdout
    assert "Not copied to zotero yet" in res.stdout
    assert "Next steps" not in res.stdout


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
    from tests.conftest import make_item

    stub_zotero.items_in_scope = lambda keys: [
        make_item(key="I1", year=2024, collection_paths=["BBNJ"]),
        make_item(
            key="I2",
            year=2019,
            doi=None,
            collection_paths=["BBNJ/EIA _ SEA"],
            has_linked_url=True,
        ),
    ]
    res = runner.invoke(
        cli.app,
        ["run", "-c", str(cfg_file), "--collection", "BBNJ/EIA / SEA", "--dry-run"],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    assert (
        "1 items without PDF" in res.stdout
        and "I1" in res.stdout
        and "10.1000/test.doi" in res.stdout
    )
    assert "Would-hit" in res.stdout and "linked URL only" in res.stdout
    assert "scihub" not in res.stdout.split("Sources:")[-1].split("\n")[0]
    assert "legal grey zone" not in res.stdout
    assert not (tmp_path / "state" / "manifest.jsonl").exists()
    assert not list((tmp_path / "out").rglob("*.pdf"))


def test_run_year_range_filters_items(cfg_file, stub_zotero):
    from tests.conftest import make_item

    stub_zotero.items_in_scope = lambda keys: [
        make_item(key="I1", year=2024, collection_paths=["BBNJ"]),
        make_item(key="I2", year=2019, doi=None, collection_paths=["BBNJ"]),
    ]
    res = runner.invoke(
        cli.app,
        [
            "run",
            "-c",
            str(cfg_file),
            "-C",
            "BBNJ",
            "--year-from",
            "2023",
            "--year-to",
            "2026",
            "--dry-run",
        ],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    assert "years 2023–2026" in res.stdout
    assert "1 items without PDF" in res.stdout
    assert "I1" in res.stdout
    assert "I2" not in res.stdout.split("Dry run")[-1]


def test_run_type_filter(cfg_file, stub_zotero):
    from tests.conftest import make_item

    stub_zotero.items_in_scope = lambda keys: [
        make_item(
            key="I1", year=2024, item_type="journalArticle", collection_paths=["BBNJ"]
        ),
        make_item(
            key="I2", year=2019, item_type="report", doi=None, collection_paths=["BBNJ"]
        ),
    ]
    res = runner.invoke(
        cli.app,
        [
            "run",
            "-c",
            str(cfg_file),
            "-C",
            "BBNJ",
            "-T",
            "Journal Article",
            "--dry-run",
        ],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    assert "types journalArticle" in res.stdout
    assert "1 items without PDF" in res.stdout
    assert "I1" in res.stdout
    assert "I2" not in res.stdout.split("Dry run")[-1]


def test_run_rejects_unknown_type(cfg_file, stub_zotero):
    res = runner.invoke(
        cli.app,
        ["run", "-c", str(cfg_file), "--library", "-T", "banana", "--dry-run"],
    )
    assert res.exit_code == 1
    assert "Unknown item type" in res.stdout


def test_run_rejects_inverted_year_range(cfg_file, stub_zotero):
    res = runner.invoke(
        cli.app,
        [
            "run",
            "-c",
            str(cfg_file),
            "--library",
            "--year-from",
            "2026",
            "--year-to",
            "2023",
            "--dry-run",
        ],
    )
    assert res.exit_code == 1
    assert "--year-from must be" in res.stdout


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


def test_run_drops_scihub_when_year_from_past_coverage(cfg_file, stub_zotero):
    from paperful.config import SCIHUB_DISCLAIMER
    from paperful.routing import SCIHUB_COVERAGE_THROUGH_YEAR

    res = runner.invoke(
        cli.app,
        [
            "run",
            "-c",
            str(cfg_file),
            "--library",
            "--dry-run",
            "--scihub",
            "--year-from",
            str(SCIHUB_COVERAGE_THROUGH_YEAR + 1),
            "--year-to",
            "2026",
        ],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    sources_line = res.stdout.split("Sources:")[-1].split("\n")[0]
    assert "scihub" not in sources_line
    assert SCIHUB_DISCLAIMER not in res.stdout


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
    from paperful.config import OA_SOURCES

    assert _source_list(cfg, None, False, preset="oa") == OA_SOURCES
    assert "ezproxy" not in OA_SOURCES


def test_jobs_matches_registered_commands():
    from typer.main import get_command

    from paperful.cli import JOBS

    names = set(get_command(cli.app).commands)
    listed = {verb for verbs in JOBS.values() for verb in verbs}
    assert listed == names


def test_jobs_command_names_snowball_and_run():
    res = runner.invoke(cli.app, ["jobs"])
    assert res.exit_code == 0
    assert "snowball" in res.stdout
    assert "run" in res.stdout
    assert "grows" in res.stdout.lower() or "Snowball" in res.stdout


def test_dedupe_dry_run_skips_the_duplicate_line(cfg_file, stub_zotero, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "paperful.remarks.remark_duplicates",
        lambda *a, **k: calls.append(k.get("surface")),
    )
    dry = runner.invoke(cli.app, ["dedupe", "-c", str(cfg_file), "-C", "BBNJ", "--dry-run"])
    assert dry.exit_code == 0, dry.stdout
    assert calls == []
    live = runner.invoke(cli.app, ["dedupe", "-c", str(cfg_file), "-C", "BBNJ"])
    assert live.exit_code == 0, live.stdout
    assert calls == ["note"]


def test_mutating_commands_name_the_write_gate():
    tokens = {
        "run": "--dry-run",
        "fix-metadata": "--apply",
        "dedupe": "--apply",
        "restore": "--apply",
        "import": "--apply",
        "attach": "dry-run",
        "snapshot": "--dry-run",
        "snowball": "dry-run",
    }
    for name, token in tokens.items():
        res = runner.invoke(cli.app, [name, "--help"])
        assert res.exit_code == 0, name
        assert token in res.stdout, name


def test_doctor_email_red_when_unpaywall_and_empty(cfg_file, stub_zotero):
    text = cfg_file.read_text().replace('email = "t@example.org"', 'email = ""')
    cfg_file.write_text(text)
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--no-guide", "--json"])
    assert res.exit_code == 2
    assert "unpaywall_email" in res.stdout


def test_run_unknown_collection(cfg_file, stub_zotero):
    res = runner.invoke(
        cli.app, ["run", "-c", str(cfg_file), "-C", "nope", "--dry-run"]
    )
    assert res.exit_code == 1 and "No collection matching" in res.stdout


def test_run_skips_already_handled_items(cfg_file, stub_zotero, tmp_path):
    from tests.conftest import make_item

    stub_zotero.items_in_scope = lambda keys: [
        make_item(key="I1", year=2024, collection_paths=["BBNJ"]),
        make_item(key="I2", year=2019, doi=None, collection_paths=["BBNJ"]),
    ]
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
    text = cfg_file.read_text()
    cfg_file.write_text(
        text
        + 'sources = ["unpaywall", "scholar", "direct", "ezproxy", "htmlpdf"]\n'
    )
    cookie_file = tmp_path / "state" / "scholar-cookies.txt"
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text(".google.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n")
    monkeypatch.setattr(
        "paperful.sources.scholar.session_ok", lambda ctx: (True, "ok (200)")
    )
    res = runner.invoke(cli.app, ["session", "status", "--probe", "-c", str(cfg_file)])
    assert res.exit_code == 0 and "Session OK" in res.stdout


def test_session_login_unknown_slot(cfg_file):
    res = runner.invoke(cli.app, ["session", "login", "ftp", "-c", str(cfg_file)])
    assert res.exit_code == 1
    assert "Unknown slot" in res.stdout


def test_session_login_mendeley_needs_app(cfg_file):
    res = runner.invoke(cli.app, ["session", "login", "mendeley", "-c", str(cfg_file)])
    assert res.exit_code == 2
    assert "client_id" in res.stdout


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
    assert "Playwright" in res.stdout
    assert "Grey playbooks" in res.stdout
    assert "UNGA/undocs" in res.stdout


def test_doctor_scholar_not_in_default_sources(cfg_file, stub_zotero):
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--no-guide"])
    assert res.exit_code == 0
    assert "Scholar" in res.stdout
    assert "not in sources" in res.stdout
    assert "Scholar session" not in res.stdout
    assert "session login scholar" not in res.stdout


def test_doctor_scholar_session_amber_without_vault(cfg_file, stub_zotero):
    text = cfg_file.read_text()
    cfg_file.write_text(
        text
        + 'sources = ["unpaywall", "scholar", "direct", "ezproxy", "htmlpdf"]\n'
    )
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--no-guide"])
    assert res.exit_code == 0
    assert "Scholar session" in res.stdout
    assert "paperful session login scholar" in res.stdout
    assert "\nGuide" not in res.stdout
    assert "paperful doctor --guide" in res.stdout


def test_doctor_guide_greens_scholar_after_host_login(
    cfg_file, tmp_path, stub_zotero, monkeypatch
):
    text = cfg_file.read_text()
    cfg_file.write_text(
        text
        + 'sources = ["unpaywall", "scholar", "direct", "ezproxy", "htmlpdf"]\n'
    )
    monkeypatch.setattr("paperful.doctor.shutil.which", lambda name: "/bin/pdftotext")
    # CI has the Playwright package but no Chromium: that amber step would come
    # first in the guide and consume the input stub. Pin it green.
    from paperful.doctor import Check

    monkeypatch.setattr(
        "paperful.doctor._playwright_check",
        lambda: Check("Playwright", "green", "package + Chromium ready"),
    )
    cookie = tmp_path / "state" / "scholar-cookies.txt"

    def after_login(_prompt: str = "") -> str:
        cookie.parent.mkdir(parents=True, exist_ok=True)
        cookie.write_text(".google.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n")
        return ""

    monkeypatch.setattr("builtins.input", after_login)
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--guide"])
    assert res.exit_code == 0
    assert "Guide" in res.stdout
    assert "session login scholar" in res.stdout
    assert "Scholar session" in res.stdout
    assert "is green" in res.stdout


def test_doctor_guide_docker_hints_host_login(cfg_file, stub_zotero, monkeypatch):
    text = cfg_file.read_text()
    cfg_file.write_text(
        text
        + 'sources = ["unpaywall", "scholar", "direct", "ezproxy", "htmlpdf"]\n'
    )
    monkeypatch.setattr("paperful.doctor.shutil.which", lambda name: "/bin/pdftotext")
    monkeypatch.setattr("paperful.cli.in_docker", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _p="": "")
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--guide"])
    assert res.exit_code == 0
    assert "on the host (not inside this container)" in res.stdout
    assert "PAPERFUL_DATA" in res.stdout


def test_doctor_auto_guides_in_docker(cfg_file, stub_zotero, monkeypatch):
    text = cfg_file.read_text()
    cfg_file.write_text(
        text
        + 'sources = ["unpaywall", "scholar", "direct", "ezproxy", "htmlpdf"]\n'
    )
    monkeypatch.setattr("paperful.doctor.shutil.which", lambda name: "/bin/pdftotext")
    monkeypatch.setattr("paperful.cli.in_docker", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _p="": "")
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file)])
    assert res.exit_code == 0
    assert "Guide" in res.stdout
    assert "session login scholar" in res.stdout


def test_doctor_scholar_session_green_with_cookies(cfg_file, tmp_path, stub_zotero):
    text = cfg_file.read_text()
    cfg_file.write_text(
        text
        + 'sources = ["unpaywall", "scholar", "direct", "ezproxy", "htmlpdf"]\n'
    )
    cookie = tmp_path / "state" / "scholar-cookies.txt"
    cookie.parent.mkdir(parents=True, exist_ok=True)
    cookie.write_text(".google.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n")
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file)])
    assert res.exit_code == 0
    assert "Scholar session" in res.stdout
    assert "session login scholar" not in res.stdout


def test_doctor_pdftotext_amber(cfg_file, stub_zotero, monkeypatch):
    monkeypatch.setattr("paperful.doctor.shutil.which", lambda name: None)
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--no-guide"])
    assert res.exit_code == 0
    assert "pdftotext" in res.stdout
    assert "ocrmypdf" in res.stdout
    assert "tesseract" in res.stdout
    assert "amber" in res.stdout


def test_doctor_zotero_red(cfg_file, monkeypatch):
    class Down:
        def ping(self):
            raise ConnectionError("Zotero local API is disabled.")

    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: Down())
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--no-guide"])
    assert res.exit_code == 2 and "red" in res.stdout
    assert "Allow other applications" in res.stdout
    assert "paperful doctor" not in res.stdout.split("Next steps", 1)[-1]


def test_doctor_json_api_off_code(cfg_file, monkeypatch):
    class Off:
        def ping(self):
            raise ConnectionError("Zotero local API is disabled.")

    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: Off())
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--json"])
    assert res.exit_code == 2
    payload = json.loads(res.stdout)
    zot = next(row for row in payload if row["name"] == "Zotero :23119")
    assert zot["code"] == "zotero_api_off"


def test_doctor_json_codes_when_zotero_down(cfg_file, monkeypatch):
    class Down:
        def ping(self):
            raise ConnectionError("connection refused")

    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: Down())
    monkeypatch.setenv("PAPERFUL_ZOTERO_HOST", "host.docker.internal")
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--json"])
    assert res.exit_code == 2
    payload = json.loads(res.stdout)
    zot = next(row for row in payload if row["name"] == "Zotero :23119")
    assert zot["status"] == "red"
    assert zot["code"] == "zotero_down"
    human = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--no-guide"])
    assert "Host header is always localhost:23119" in human.stdout
    assert "paperful doctor" not in human.stdout.split("Next steps", 1)[-1]


def test_doctor_shows_paperful_zotero_host(cfg_file, stub_zotero, monkeypatch):
    monkeypatch.setenv("PAPERFUL_ZOTERO_HOST", "host.docker.internal")
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--no-guide"])
    assert res.exit_code == 0
    assert "host.docker.internal:23119" in res.stdout


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

    class FakeBackend:
        def supports_write(self):
            return True

        def attach(self, key, path, title=None, note=None):
            from paperful.attach import AttachResult

            return AttachResult(True, attachment_key="ATT", reason="success", code="success")

        def flush_writes(self):
            return None

    monkeypatch.setattr(cli, "_connect", lambda cfg, quiet=False: FakeBackend())
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


def test_lint_json(cfg_file, stub_zotero, monkeypatch, tmp_path):
    monkeypatch.setattr("paperful.lint.lint_items", lambda *a, **k: [])
    res = runner.invoke(cli.app, ["lint", "-c", str(cfg_file), "--library", "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout) == []
    runs = list((tmp_path / "state" / "runs").glob("*-lint.json"))
    assert len(runs) == 1
    data = json.loads(runs[0].read_text())
    assert data["summary"]["findings"] == 0
    assert not (tmp_path / "state" / "last-run.json").exists()


def test_lint_strict_exits_1(cfg_file, stub_zotero, monkeypatch, tmp_path):
    from paperful.lint import Finding

    monkeypatch.setattr(
        "paperful.lint.lint_items",
        lambda *a, **k: [Finding("I1", "missing_doi", "T", "no DOI")],
    )
    res = runner.invoke(cli.app, ["lint", "-c", str(cfg_file), "--library", "--strict"])
    assert res.exit_code == 1
    assert "missing_doi" in res.stdout
    runs = list((tmp_path / "state" / "runs").glob("*-lint.json"))
    assert len(runs) == 1
    data = json.loads(runs[0].read_text())
    assert data["summary"]["findings"] == 1
    assert data["items"][0]["status"] == "missing_doi"


def test_fix_metadata_dry_run(cfg_file, stub_zotero, tmp_path, monkeypatch):
    monkeypatch.setattr("paperful.lint.lint_item", lambda *a, **k: [])
    monkeypatch.setattr("paperful.metadata.propose_patch", lambda *a, **k: None)
    res = runner.invoke(cli.app, ["fix-metadata", "-c", str(cfg_file), "--library"])
    assert res.exit_code == 0
    assert "Dry-run" in res.stdout
    assert "0 proposed patches" in res.stdout
    assert (tmp_path / "state" / "metadata-patches.jsonl").exists()
    runs = list((tmp_path / "state" / "runs").glob("*-fix-metadata.json"))
    assert len(runs) == 1
    data = json.loads(runs[0].read_text())
    assert data["flags"]["apply"] is False
    assert "patches_applied" not in data["summary"]
    assert not (tmp_path / "state" / "last-run.json").exists()


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


def test_mendeley_manager_asks_for_auth(cfg_file, tmp_path):
    cfg_file.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
        'manager = "mendeley"\n'
    )
    res = runner.invoke(cli.app, ["collections", "-c", str(cfg_file)])
    assert res.exit_code == 2
    assert "not authorised" in res.stdout.lower()
    assert "not implemented" not in res.stdout.lower()


def test_import_ris_dry_run(cfg_file, tmp_path):
    ris = tmp_path / "lib.ris"
    ris.write_text("TY  - JOUR\nTI  - Hello seas\nER  - \n", encoding="utf-8")
    res = runner.invoke(cli.app, ["import", str(ris), "-c", str(cfg_file)])
    assert res.exit_code == 0, res.stdout
    assert "1 record" in res.stdout
    assert "Dry run" in res.stdout


def test_export_ris_library(cfg_file, stub_zotero, tmp_path):
    dest = tmp_path / "lib.ris"
    res = runner.invoke(
        cli.app, ["export", str(dest), "--library", "-c", str(cfg_file)]
    )
    assert res.exit_code == 0, res.stdout
    text = dest.read_text(encoding="utf-8")
    assert "TY  - JOUR" in text
    assert "TI  -" in text


def test_restore_dry_run_names_the_library_not_zotero(
    cfg_file, stub_zotero, tmp_path
):
    res = runner.invoke(
        cli.app, ["restore", "--library", "--dry-run", "-c", str(cfg_file)]
    )
    assert res.exit_code == 0, res.stdout
    assert "into the library" in res.stdout
    assert "into Zotero" not in res.stdout


# ---- LLM verbs: recover / summarize gating -----------------------------------


def _llm_cfg_file(tmp_path, extra=""):
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
        "[llm]\nenabled = true\n" + extra
    )
    return p


def test_recover_requires_item(cfg_file):
    res = runner.invoke(cli.app, ["recover", "-c", str(cfg_file)])
    assert res.exit_code == 1 and "--item" in res.stdout


def test_recover_exits_when_llm_disabled(cfg_file, stub_zotero):
    res = runner.invoke(cli.app, ["recover", "-c", str(cfg_file), "--item", "I1"])
    assert res.exit_code == 1 and "llm.enabled" in res.stdout


def test_recover_python_gate(cfg_file, monkeypatch):
    import sys as real_sys
    from collections import namedtuple

    VI = namedtuple("VI", "major minor micro releaselevel serial")
    fake = type("S", (), {"version_info": VI(3, 10, 0, "final", 0), "modules": real_sys.modules})()
    monkeypatch.setattr(cli, "sys", fake)
    res = runner.invoke(cli.app, ["recover", "-c", str(cfg_file), "--item", "I1"])
    assert res.exit_code == 1 and "3.11" in res.stdout


def test_recover_dry_run_prints_start_url(tmp_path, stub_zotero, monkeypatch):
    from paperful.config import RECOVER_DISCLAIMER
    from tests.conftest import make_item

    cfg_file = _llm_cfg_file(tmp_path)
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_verb", lambda cfg, **k: cfg.llm_model)
    monkeypatch.setattr(
        cli, "get_backend", lambda cfg, zl: type("B", (), {"get_item": lambda self, k: make_item(key=k)})()
    )
    res = runner.invoke(cli.app, ["recover", "-c", str(cfg_file), "--item", "I1", "--dry-run"])
    assert res.exit_code == 0, res.stdout
    assert RECOVER_DISCLAIMER in res.stdout
    assert "https://doi.org/10.1000/test.doi" in res.stdout
    assert not (tmp_path / "state" / "manifest.jsonl").exists()


def test_run_dry_run_appends_recover_lane(tmp_path, stub_zotero, monkeypatch):
    cfg_file = _llm_cfg_file(tmp_path)
    monkeypatch.setattr(
        "paperful.browser_agent.browser_agent_extra_available", lambda: True
    )
    res = runner.invoke(
        cli.app,
        ["run", "-c", str(cfg_file), "--library", "--dry-run"],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    sources_line = res.stdout.split("Sources:")[-1].split("\n")[0]
    assert "browser_agent" in sources_line
    assert "htmlpdf" in sources_line
    assert "Browser recovery is experimental" in res.stdout
    assert sources_line.index("htmlpdf") < sources_line.index("browser_agent")


def test_run_dry_run_skips_recover_lane_when_during_run_off(
    tmp_path, stub_zotero, monkeypatch
):
    cfg_file = _llm_cfg_file(tmp_path, extra="[browser_agent]\nduring_run = false\n")
    monkeypatch.setattr(
        "paperful.browser_agent.browser_agent_extra_available", lambda: True
    )
    res = runner.invoke(
        cli.app,
        ["run", "-c", str(cfg_file), "--library", "--dry-run"],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    sources_line = res.stdout.split("Sources:")[-1].split("\n")[0]
    assert "browser_agent" not in sources_line
    assert "Browser recovery is experimental" not in res.stdout


def test_recover_unknown_item(tmp_path, stub_zotero, monkeypatch):
    cfg_file = _llm_cfg_file(tmp_path)
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_verb", lambda cfg, **k: cfg.llm_model)
    monkeypatch.setattr(cli, "get_backend", lambda cfg, zl: type("B", (), {"get_item": lambda self, k: None})())
    res = runner.invoke(cli.app, ["recover", "-c", str(cfg_file), "--item", "NOPE", "--dry-run"])
    assert res.exit_code == 1 and "Unknown item" in res.stdout


def test_summarize_requires_scope(cfg_file):
    res = runner.invoke(cli.app, ["summarize", "-c", str(cfg_file)])
    assert res.exit_code == 1 and "--item" in res.stdout


def test_summarize_exits_when_llm_disabled(cfg_file, stub_zotero):
    res = runner.invoke(cli.app, ["summarize", "-c", str(cfg_file), "--item", "I1"])
    assert res.exit_code == 1 and "llm.enabled" in res.stdout


def test_summarize_default_writes_note_and_disk_only_skips_it(tmp_path, stub_zotero, monkeypatch):
    from tests.conftest import make_item

    cfg_file = _llm_cfg_file(tmp_path)
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_verb", lambda cfg, **k: cfg.llm_model)

    class B:
        applied = []

        def get_item(self, k):
            return make_item(key=k, has_pdf=True)

        def create_or_update_note(self, *a):
            self.applied.append(a)
            return "N1"

    monkeypatch.setattr(cli, "get_backend", lambda cfg, zl: B())
    monkeypatch.setattr("paperful.summarize.pdf_text_for", lambda *a, **k: "Marine governance text.")

    class Stub:
        provider = "stub"

        def complete(self, req):
            return "<h2>Objective</h2><p>ok</p>"

    monkeypatch.setattr("paperful.summarize.get_client", lambda cfg: Stub())
    res = runner.invoke(cli.app, ["summarize", "-c", str(cfg_file), "--item", "I1"])
    assert res.exit_code == 0, res.stdout
    assert (tmp_path / "state" / "summaries" / "I1.html").is_file()
    assert "attached note N1" in res.stdout and len(B.applied) == 1
    assert "Dry-run" not in res.stdout
    reports = list((tmp_path / "state" / "runs").glob("*-summarize.json"))
    assert len(reports) == 1
    summary = json.loads(reports[0].read_text())
    assert summary["summary"]["summarized"] == 1
    assert summary["summary"]["failed"] == 0
    assert summary["summary"]["dest"] == "both"
    assert summary["items"][0]["status"] == "summarized"
    assert not (tmp_path / "state" / "last-run.json").exists()

    res = runner.invoke(
        cli.app, ["summarize", "-c", str(cfg_file), "--item", "I1", "--to", "disk"]
    )
    assert res.exit_code == 0, res.stdout
    assert "Zotero not written" in res.stdout and len(B.applied) == 1

    res = runner.invoke(
        cli.app,
        ["summarize", "-c", str(cfg_file), "--item", "I1", "--to", "disk", "--apply"],
    )
    assert res.exit_code == 1 and "--apply" in res.stdout


def test_synthesize_report_collection_conflicts_with_disk(tmp_path, stub_zotero, monkeypatch):
    cfg_file = _llm_cfg_file(tmp_path)
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_verb", lambda cfg, **k: cfg.llm_model)
    res = runner.invoke(
        cli.app,
        [
            "synthesize",
            "-c",
            str(cfg_file),
            "--item",
            "I1",
            "--to",
            "disk",
            "--report-collection",
            "BBNJ",
        ],
    )
    assert res.exit_code == 1, res.stdout
    assert "--report-collection" in res.stdout


def test_summarize_remote_egress_notice(tmp_path, stub_zotero, monkeypatch):
    from tests.conftest import make_item

    cfg_file = _llm_cfg_file(tmp_path, 'provider = "litellm"\nmodel = "openai/gpt"\n')
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_verb", lambda cfg, **k: cfg.llm_model)
    monkeypatch.setattr(
        cli, "get_backend", lambda cfg, zl: type("B", (), {"get_item": lambda self, k: make_item(key=k, has_pdf=False)})()
    )
    res = runner.invoke(cli.app, ["summarize", "-c", str(cfg_file), "--item", "I1"])
    assert "Remote LLM" in res.stdout
    assert "No items with PDFs" in res.stdout


def test_doctor_llm_disabled_row(cfg_file, stub_zotero):
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--no-guide"])
    assert res.exit_code == 0 and "LLM" in res.stdout and "disabled" in res.stdout


def test_doctor_llm_enabled_amber_when_unreachable(tmp_path, stub_zotero, monkeypatch):
    cfg_file = _llm_cfg_file(tmp_path, 'base_url = "http://127.0.0.1:1"\n')
    import httpx as _httpx

    import paperful.llm.client as mod

    orig = _httpx.Client

    class _C(orig):
        def __init__(self, *a, **kw):
            def boom(r):
                raise _httpx.ConnectError("refused")

            kw["transport"] = _httpx.MockTransport(boom)
            super().__init__(*a, **kw)

    monkeypatch.setattr(mod.httpx, "Client", _C)
    res = runner.invoke(cli.app, ["doctor", "-c", str(cfg_file), "--no-guide"])
    assert res.exit_code == 0
    assert "LLM" in res.stdout and "unreachable" in res.stdout
    assert "browser-agent extra" in res.stdout


def test_synthesize_requires_scope(cfg_file):
    res = runner.invoke(cli.app, ["synthesize", "-c", str(cfg_file)])
    assert res.exit_code == 1 and "--item" in res.stdout


def test_synthesize_exits_when_llm_disabled(cfg_file, stub_zotero):
    res = runner.invoke(cli.app, ["synthesize", "-c", str(cfg_file), "--item", "I1"])
    assert res.exit_code == 1 and "llm.enabled" in res.stdout


def test_synthesize_library_needs_a_collection_for_zotero(tmp_path, stub_zotero, monkeypatch):
    cfg_file = _llm_cfg_file(tmp_path)
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_verb", lambda cfg, **k: cfg.llm_model)

    class B:
        def items_in_scope(self, keys):
            return []

        def read_child_note(self, *a):
            return None

    monkeypatch.setattr(cli, "get_backend", lambda cfg, zl: B())
    res = runner.invoke(cli.app, ["synthesize", "-c", str(cfg_file), "--library"])
    assert res.exit_code == 1, res.stdout
    assert "--report-collection" in res.stdout


def test_synthesize_dry_run_and_disk_report(tmp_path, stub_zotero, monkeypatch):
    from tests.conftest import make_item

    cfg_file = _llm_cfg_file(tmp_path)
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_verb", lambda cfg, **k: cfg.llm_model)
    summary = tmp_path / "state" / "summaries"
    summary.mkdir(parents=True)
    (summary / "I1.html").write_text("<h2>Objective</h2><p>Governance.</p>", encoding="utf-8")
    calls = []

    class B:
        notes = []

        def get_item(self, k):
            return make_item(key=k, has_pdf=True)

        def read_child_note(self, *a):
            return None

        def create_or_update_collection_note(self, *a):
            self.notes.append(a)
            return "R1"

    class Stub:
        def complete(self, req):
            calls.append(req.prompt)
            return "<h2>Themes</h2><p>See [Smith 2019].</p>"

    monkeypatch.setattr(cli, "get_backend", lambda cfg, zl: B())
    monkeypatch.setattr("paperful.llm.get_client", lambda cfg: Stub())
    res = runner.invoke(
        cli.app, ["synthesize", "-c", str(cfg_file), "--item", "I1", "--to", "disk", "--dry-run"]
    )
    assert res.exit_code == 0, res.stdout
    assert "1 on disk" in res.stdout and not calls
    assert not (tmp_path / "state" / "reports").exists()

    res = runner.invoke(
        cli.app, ["synthesize", "-c", str(cfg_file), "--item", "I1", "--to", "disk"]
    )
    assert res.exit_code == 0, res.stdout
    reports = list((tmp_path / "state" / "reports").glob("*.html"))
    assert len(reports) == 1 and "Paperful report:" in reports[0].read_text()
    assert list((tmp_path / "state" / "reports").glob("*.json"))
    assert list((tmp_path / "state" / "runs").glob("*-synthesize.json"))
    assert not B.notes and len(calls) == 1

    res = runner.invoke(
        cli.app, ["synthesize", "-c", str(cfg_file), "--item", "I1", "--to", "disk"]
    )
    assert res.exit_code == 0, res.stdout
    assert "up to date" in res.stdout and len(calls) == 1


def test_pack_second_open_exits(cfg_file, tmp_path):
    res = runner.invoke(
        cli.app, ["pack", "open", "-c", str(cfg_file), "--label", "bbnj"]
    )
    assert res.exit_code == 0, res.stdout
    pack_id = res.stdout.strip()
    assert (tmp_path / "state" / "packs" / "current").read_text().strip() == pack_id
    again = runner.invoke(cli.app, ["pack", "open", "-c", str(cfg_file)])
    assert again.exit_code == 1
    assert "still open" in again.stdout


def test_gaps_joins_open_pack_unless_opted_out(cfg_file, stub_zotero, tmp_path, monkeypatch):
    opened = runner.invoke(cli.app, ["pack", "open", "-c", str(cfg_file)])
    assert opened.exit_code == 0, opened.stdout
    pack_id = opened.stdout.strip()
    res = runner.invoke(
        cli.app, ["gaps", "-c", str(cfg_file), "--library", "--json"]
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["items"] == 2
    assert payload["no_stored_pdf"] == 1
    runs = list((tmp_path / "state" / "runs").glob("*-gaps.json"))
    assert len(runs) == 1
    report = json.loads(runs[0].read_text())
    assert report["command"] == "gaps"
    assert report["items"][0]["itemKey"] == "I2"
    pack = json.loads((tmp_path / "state" / "packs" / f"{pack_id}.json").read_text())
    assert pack["status"] == "open"
    assert pack["steps"][0]["command"] == "gaps"
    assert pack["scope"]
    assert not (tmp_path / "state" / "last-run.json").exists()

    monkeypatch.setenv("PAPERFUL_PACK", "off")
    again = runner.invoke(
        cli.app, ["gaps", "-c", str(cfg_file), "--library", "--json"]
    )
    assert again.exit_code == 0, again.stdout
    pack = json.loads((tmp_path / "state" / "packs" / f"{pack_id}.json").read_text())
    assert len(pack["steps"]) == 1
    assert list((tmp_path / "state" / "runs").glob("*-gaps.json"))


def test_pack_close_and_show_json(cfg_file, stub_zotero, tmp_path):
    runner.invoke(cli.app, ["pack", "open", "-c", str(cfg_file), "--label", "bbnj"])
    runner.invoke(cli.app, ["gaps", "-c", str(cfg_file), "--library"])
    closed = runner.invoke(cli.app, ["pack", "close", "-c", str(cfg_file)])
    assert closed.exit_code == 0, closed.stdout
    assert "Closed" in closed.stdout
    assert not (tmp_path / "state" / "packs" / "current").exists()
    missing = runner.invoke(cli.app, ["pack", "close", "-c", str(cfg_file)])
    assert missing.exit_code == 1

    shown = runner.invoke(cli.app, ["pack", "show", "-c", str(cfg_file), "--json"])
    assert shown.exit_code == 0, shown.stdout
    data = json.loads(shown.stdout)
    assert data["status"] == "closed"
    assert data["label"] == "bbnj"
    assert data["steps"][0]["summary"]["items"] == 2
    assert "itemKey" not in json.dumps(data["steps"])


def test_pack_show_human_table_and_empty(cfg_file, stub_zotero, tmp_path):
    empty = runner.invoke(cli.app, ["pack", "show", "-c", str(cfg_file)])
    assert empty.exit_code == 0
    assert "No pack yet" in empty.stdout

    runner.invoke(cli.app, ["pack", "open", "-c", str(cfg_file)])
    runner.invoke(cli.app, ["gaps", "-c", str(cfg_file), "--library"])
    shown = runner.invoke(cli.app, ["pack", "show", "-c", str(cfg_file)])
    assert shown.exit_code == 0, shown.stdout
    assert "gaps" in shown.stdout
    assert "no PDF" in shown.stdout
    assert "missing DOI" in shown.stdout
    assert not (tmp_path / "state" / "last-run.json").exists()


