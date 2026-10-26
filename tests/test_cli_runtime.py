"""``cli_runtime`` owns connect/scope helpers; ``cli`` re-exports them."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from paperful import cli, cli_runtime
from paperful.pipeline import SERIAL_SOURCES as PIPE_SERIAL
from paperful.routing import SERIAL_SOURCES as ROUTE_SERIAL

ROOT = Path(__file__).resolve().parents[1]
PAPERFUL = ROOT / "paperful"

# Command modules that must import cli_runtime, not cli.
RUNTIME_CLIENTS = [
    "run_cmd.py",
    "run_hooks.py",
    "lint_cmd.py",
    "screen_cmd.py",
    "critique_cmd.py",
    "fix_metadata_cmd.py",
    "ocr_cmd.py",
    "ocr_ignore_cmd.py",
    "recover_cmd.py",
    "reachout_cmd.py",
    "notes_delete_cmd.py",
    "authors_cmd.py",
    "acronyms_cmd.py",
    "completeness_cmd.py",
    "ask_cmd.py",
    "authorwatch_suggest.py",
    "snowball/trends_cmd.py",
    "attach_cmd.py",
    "versions_cmd.py",
    "refs_gap_cmd.py",
    "coverage_cmd.py",
    "export_cmd.py",
    "inbox_cmd.py",
    "dedupe_cmd.py",
    "attachments_cmd.py",
    "summarize_cmd.py",
    "synthesize_cmd.py",
    "doctor_cmd.py",
    "collections_cmd.py",
    "session_cmd.py",
    "mirrors_cmd.py",
    "pack_cmd.py",
    "cache_cmd.py",
    "all_cmd.py",
    "gaps_cmd.py",
    "urls_cmd.py",
    "htmlpdf_cmd.py",
    "snapshot_cmd.py",
    "restore_cmd.py",
    "rag_cmd.py",
    "sections_cmd.py",
    "twenty_cmd.py",
    "ingest_cmd.py",
    "sync_cmd.py",
    "report_cmd.py",
    "playbooks_cmd.py",
    "profile_cmd.py",
    "snowball_cmd.py",
    "authorwatch_cmd.py",
    "keepup_cmd.py",
]


def _imports_cli(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "paperful.cli" or alias.name == "cli":
                    # bare `import cli` is not used; still flag paperful.cli
                    if alias.name == "paperful.cli":
                        return True
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in {"cli", "paperful.cli"}:
                return True
            if mod == "paperful" and any(a.name == "cli" for a in node.names):
                return True
            if mod in {".", ""} and any(a.name == "cli" for a in node.names):
                # `from . import cli` / `from . import cli as cli_mod`
                return True
    return False


@pytest.mark.parametrize("rel", RUNTIME_CLIENTS)
def test_cmd_modules_do_not_import_cli(rel: str):
    path = PAPERFUL / rel
    assert path.is_file(), path
    assert not _imports_cli(path), f"{rel} still imports paperful.cli"


def test_all_cmd_dispatch_uses_runtime_not_cli():
    path = PAPERFUL / "all_cmd.py"
    src = path.read_text(encoding="utf-8")
    assert "from . import cli_runtime as cli_mod" in src
    assert "from . import cli as cli_mod" not in src


def test_cli_reexports_runtime_helpers():
    assert cli._source_list is cli_runtime._source_list
    assert cli._connect is cli_runtime._connect
    assert cli.console is cli_runtime.console
    assert cli._cfg is cli_runtime._cfg
    assert cli._finish_run is cli_runtime._finish_run


def test_serial_sources_single_object():
    assert PIPE_SERIAL is ROUTE_SERIAL
    assert "scihub" in ROUTE_SERIAL
    assert "unpaywall" not in ROUTE_SERIAL
    assert "ezproxy" in ROUTE_SERIAL
