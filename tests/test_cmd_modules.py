"""Wiring for extracted ``*_cmd`` modules (CLI parses flags only)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from paperful import (
    all_cmd,
    attach_cmd,
    authorwatch_cmd,
    acronyms_cmd,
    authors_cmd,
    cache_cmd,
    collections_cmd,
    coverage_cmd,
    doctor_cmd,
    export_cmd,
    fix_metadata_cmd,
    htmlpdf_cmd,
    inbox_cmd,
    ingest_cmd,
    keepup_cmd,
    lint_cmd,
    mirrors_cmd,
    notes_delete_cmd,
    ocr_cmd,
    pack_cmd,
    playbooks_cmd,
    profile_cmd,
    rag_cmd,
    reachout_cmd,
    recover_cmd,
    refs_gap_cmd,
    report_cmd,
    restore_cmd,
    screen_cmd,
    critique_cmd,
    rewrite_cmd,
    sections_cmd,
    session_cmd,
    snapshot_cmd,
    snowball_cmd,
    sync_cmd,
    twenty_cmd,
    urls_cmd,
    versions_cmd,
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
    ("acronyms", acronyms_cmd, "run_acronyms", "acronyms_cmd"),
    ("all_cmd", all_cmd, "run_all", "all_cmd"),
    ("screen", screen_cmd, "run_screen", "screen_cmd"),
    ("critique", critique_cmd, "run_critique", "critique_cmd"),
    ("critique_dismiss", critique_cmd, "run_dismiss", "critique_cmd"),
    ("rewrite", rewrite_cmd, "run_rewrite", "rewrite_cmd"),
    ("attach", attach_cmd, "run_attach", "attach_cmd"),
    ("versions", versions_cmd, "run_versions", "versions_cmd"),
    ("refs_gap", refs_gap_cmd, "run_refs_gap", "refs_gap_cmd"),
    ("coverage_cmd", coverage_cmd, "run_coverage", "coverage_cmd"),
    ("export_library", export_cmd, "run_export_library", "export_cmd"),
    ("inbox_watch", inbox_cmd, "run_inbox_watch", "inbox_cmd"),
    ("inbox_drain", inbox_cmd, "run_inbox_drain", "inbox_cmd"),
    ("inbox_proposals_list", inbox_cmd, "run_inbox_proposals_list", "inbox_cmd"),
    ("inbox_proposals_apply", inbox_cmd, "run_inbox_proposals_apply", "inbox_cmd"),
    ("inbox_proposals_reject", inbox_cmd, "run_inbox_proposals_reject", "inbox_cmd"),
    ("doctor", doctor_cmd, "run_doctor", "doctor_cmd"),
    ("collections_list", collections_cmd, "run_collections_show", "collections_cmd"),
    ("collections_add_cmd", collections_cmd, "run_collections_add", "collections_cmd"),
    ("session_login", session_cmd, "run_session_login", "session_cmd"),
    ("session_status", session_cmd, "run_session_status", "session_cmd"),
    ("session_export", session_cmd, "run_session_export", "session_cmd"),
    ("ezproxy_cmd", session_cmd, "run_ezproxy", "session_cmd"),
    ("scholar_cmd", session_cmd, "run_scholar", "session_cmd"),
    ("mirrors", mirrors_cmd, "run_mirrors", "mirrors_cmd"),
    ("pack_open", pack_cmd, "run_pack_open", "pack_cmd"),
    ("pack_close", pack_cmd, "run_pack_close", "pack_cmd"),
    ("pack_show", pack_cmd, "run_pack_show", "pack_cmd"),
    ("cache_clean", cache_cmd, "run_cache_clean", "cache_cmd"),
    ("snapshot", snapshot_cmd, "run_snapshot_cmd", "snapshot_cmd"),
    ("restore", restore_cmd, "run_restore", "restore_cmd"),
    ("urls_check", urls_cmd, "run_urls", "urls_cmd"),
    (
        "htmlpdf_proposals_list",
        htmlpdf_cmd,
        "run_htmlpdf_proposals_list",
        "htmlpdf_cmd",
    ),
    (
        "htmlpdf_proposals_apply",
        htmlpdf_cmd,
        "run_htmlpdf_proposals_apply",
        "htmlpdf_cmd",
    ),
    (
        "htmlpdf_proposals_reject",
        htmlpdf_cmd,
        "run_htmlpdf_proposals_reject",
        "htmlpdf_cmd",
    ),
    ("rag_ingest", rag_cmd, "run_rag_ingest", "rag_cmd"),
    ("rag_status", rag_cmd, "run_rag_status", "rag_cmd"),
    ("rag_search", rag_cmd, "run_rag_search", "rag_cmd"),
    ("rag_questions", rag_cmd, "run_rag_questions", "rag_cmd"),
    ("rag_answered", rag_cmd, "run_rag_answered", "rag_cmd"),
    ("extract_sections", sections_cmd, "run_extract_sections", "sections_cmd"),
    ("twenty_lookup_cmd", twenty_cmd, "run_twenty_lookup", "twenty_cmd"),
    ("twenty_sync_cmd", twenty_cmd, "run_twenty_sync", "twenty_cmd"),
    ("ingest_dois_cmd", ingest_cmd, "run_ingest_dois", "ingest_cmd"),
    ("sync", sync_cmd, "run_sync_command", "sync_cmd"),
    ("import_library", sync_cmd, "run_import_library", "sync_cmd"),
    (
        "openalex_store_build_cites",
        sync_cmd,
        "run_openalex_store_build_cites",
        "sync_cmd",
    ),
    ("report", report_cmd, "run_report", "report_cmd"),
    ("export_proposals", report_cmd, "run_export_proposals", "report_cmd"),
    ("playbooks_probe", playbooks_cmd, "run_playbooks_probe", "playbooks_cmd"),
    ("profile_list", profile_cmd, "run_profile_list", "profile_cmd"),
    ("snowball_search", snowball_cmd, "run_snowball_search", "snowball_cmd"),
    ("snowball_run", snowball_cmd, "run_snowball_run", "snowball_cmd"),
    ("authorwatch_run", authorwatch_cmd, "run_authorwatch_run", "authorwatch_cmd"),
    ("keepup_run", keepup_cmd, "run_keepup_run", "keepup_cmd"),
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


def test_all_dispatch_uses_cmd_modules_not_cli():
    src = inspect.getsource(all_cmd._dispatch_all_step)
    assert "run_lint" in src
    assert "run_ocr" in src
    assert "run_fix_metadata" in src
    assert "run_dedupe" in src
    assert "run_summarize" in src
    assert "run_synthesize" in src
    assert "run_snapshot_cmd" in src
    assert "run_restore" in src
    assert "run_gaps_command" in src
    assert "run_run_command" in src
    assert "cli_mod." not in src
    assert "import cli" not in src


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


def test_completeness_shim_reexports_split_modules():
    from paperful import (
        attachments_cmd,
        completeness_cmd,
        dedupe_cmd,
        summarize_cmd,
        synthesize_cmd,
    )

    assert completeness_cmd.run_attachments is attachments_cmd.run_attachments
    assert completeness_cmd.run_dedupe is dedupe_cmd.run_dedupe
    assert completeness_cmd.run_summarize is summarize_cmd.run_summarize
    assert completeness_cmd.run_synthesize is synthesize_cmd.run_synthesize


@pytest.mark.parametrize(
    "cli_name,entry",
    [
        ("dedupe", "run_dedupe"),
        ("attachments", "run_attachments"),
        ("summarize", "run_summarize"),
        ("synthesize", "run_synthesize"),
    ],
)
def test_completeness_cli_uses_shim(cli_name, entry):
    src = inspect.getsource(getattr(cli, cli_name))
    assert f"from .completeness_cmd import {entry}" in src
