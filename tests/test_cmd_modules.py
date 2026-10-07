"""Wiring for extracted ``*_cmd`` modules (CLI parses flags only)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from paperful import (
    all_cmd,
    authors_cmd,
    fix_metadata_cmd,
    lint_cmd,
    notes_delete_cmd,
    ocr_cmd,
    reachout_cmd,
    recover_cmd,
)
from paperful import cli

ROOT = Path(__file__).resolve().parents[1]

ENTRIES = [
    ("lint", lint_cmd, "run_lint", "lint_cmd"),
    ("fix_metadata", fix_metadata_cmd, "run_fix_metadata", "fix_metadata_cmd"),
    ("ocr", ocr_cmd, "run_ocr", "ocr_cmd"),
    ("recover", recover_cmd, "run_recover", "recover_cmd"),
    ("reachout", reachout_cmd, "run_reachout", "reachout_cmd"),
    ("notes_delete", notes_delete_cmd, "run_notes_delete", "notes_delete_cmd"),
    ("authors", authors_cmd, "run_authors", "authors_cmd"),
    ("all_cmd", all_cmd, "run_all", "all_cmd"),
]


@pytest.mark.parametrize("cli_name,mod,entry,_pkg", ENTRIES)
def test_cmd_entry_is_callable(cli_name, mod, entry, _pkg):
    fn = getattr(mod, entry)
    assert callable(fn)
    assert inspect.signature(fn).parameters["console"]


@pytest.mark.parametrize("cli_name,mod,entry,pkg", ENTRIES)
def test_cli_wrapper_delegates_to_cmd(cli_name, mod, entry, pkg):
    wrapper = getattr(cli, cli_name)
    src = inspect.getsource(wrapper)
    assert f"from .{pkg} import {entry}" in src
    assert f"{entry}(" in src
    # Thin: no domain orchestration left in the Typer body.
    assert "Manifest(" not in src
    assert "write_command_report(" not in src


def test_all_dispatch_keeps_typer_wrappers():
    src = inspect.getsource(all_cmd._dispatch_all_step)
    assert "cli_mod.lint" in src
    assert "cli_mod.run" in src
    assert "cli_mod.gaps" in src


def test_cli_dispatch_alias_forwards():
    src = inspect.getsource(cli._dispatch_all_step)
    assert "all_cmd" in src


def test_cmd_modules_exist_on_disk():
    for _cli_name, _mod, _entry, pkg in ENTRIES:
        path = ROOT / "paperful" / f"{pkg}.py"
        assert path.is_file(), path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        assert any(n.startswith("run_") for n in names)
