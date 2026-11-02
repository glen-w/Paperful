"""paperful command line."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from enum import Enum
from pathlib import Path
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import typer
from rich.console import Console
from typer.core import TyperGroup
from .progress import Track, item_progress, pause_live, tracker

from . import __version__
from .config import (
    CAMOFOX_DISCLAIMER,
    KNOWN_MANAGERS,
    RECOVER_DISCLAIMER,
    SCIHUB_DISCLAIMER,
    SOURCE_PRESETS,
    Config,
    load_config,
    parse_pdfs,
    wants_disk,
    wants_zotero,
)
from .doctor import (
    Check,
    actionable_checks,
    has_red,
    in_docker,
    remediation_text,
    run_checks,
)
from .catalogue import MirrorCatalogue, MirrorFirstBackend, open_library
from .library import LibraryBackend, LibraryError, get_backend, mirrored
from .mirror import pdf_for
from .pack import PackError, close_pack, current_id, open_pack, pack_join_disabled
from .pipeline import Pipeline, RunStats, make_client, session_expired_items
from .routing import (
    filter_sources_for_item_types,
    filter_sources_for_year_scope,
    sources_for_item,
    with_recover_lane,
    with_serpapi_lane,
)
from .run_config import (
    ProfileListing,
    ResolvedRunConfig,
    RunConfigError,
    collect_save_body,
    format_effective,
    list_profiles,
    resolve_run_config,
    save_profile,
)
from .runreport import (
    ItemOutcome,
    build_report,
    print_run_summary,
    write_command_report,
    write_run_report,
)
from . import run_hooks
from .run_hooks import (
    ezproxy_headed_login_and_probe,
    ensure_ezproxy_session,
    gaps_downloads_dir,
    inbox_handoff_session,
    maybe_ezproxy_relogin,
    mid_run_ezproxy_hook,
    preflight_ezproxy_session,
    run_dry_run_table_and_payload,
    run_session_handoff,
)
from .scope import ScopeError, filter_scope_items, load_scope, resolve_keys
from .sources import Context
from .sources.scihub import ping_mirrors
from .store import (
    REASON_SHORT_PDF,
    STATUS_ATTACHED,
    STATUS_NOT_FOUND,
    STATUS_OK,
    Manifest,
    items_from_mirror,
)
from .zot import (
    ZoteroLocal,
    items_without_stored_pdf,
    linked_url_only_count,
    resolve_item_types,
)


def _load_dotenv() -> None:
    """Fill unset variables from a gitignored .env in the working directory."""
    path = Path.cwd() / ".env"
    try:
        if not path.is_file():
            return
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        # Unreadable cwd (e.g. Compose mount owned by another uid) must not abort CLI start.
        return
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Research helper for a reference library: clean records, find missing PDFs, "
        "summarise papers, keep an on-disk mirror. Zotero is the well-tested adapter. "
        "Mendeley and EndNote are seeking testers. "
        "`paperful jobs` lists the five jobs."
    ),
)
session_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Local browser session vault for Scholar, EZProxy, and publishers.",
)
app.add_typer(session_app, name="session")
pack_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Group command reports from one operator sequence.",
)
app.add_typer(pack_app, name="pack")
profile_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Named run configs (SCOPE + policy). Not grey-lit playbooks.",
)
app.add_typer(profile_app, name="profile")
playbooks_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Propose, promote, and probe grey-lit PDF playbooks. Not run-config profiles."
    ),
)
app.add_typer(playbooks_app, name="playbooks")
snowball_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Grow a library: find works and create metadata parents from a keyword, DOI, "
        "ORCID, or seed collection. Dry-run unless --gate auto. Does not fill PDFs "
        "unless --fetch-pdfs. Use `paperful run` to fill items already in the library. "
        "The public verb is snowball (there is no harvest command)."
    ),
)
app.add_typer(snowball_app, name="snowball")
inbox_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Watch a PDF drop folder and attach downloads to matching library items. "
        "Not snowball's watch inbox.jsonl."
    ),
)
app.add_typer(inbox_app, name="inbox")
capture_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    invoke_without_command=True,
    help=(
        "Save a browser page into the quiet mirror. Reads Zotero so a stale "
        "snapshot cannot create a second item. Does not attach or create in the library."
    ),
)
app.add_typer(capture_app, name="capture")
htmlpdf_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Academic HTML page snapshots. Proposals stay on disk until apply.",
)
app.add_typer(htmlpdf_app, name="htmlpdf")
htmlpdf_proposals_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Gated HTML snapshot proposals. Apply attaches a snapshot-tier PDF.",
)
htmlpdf_app.add_typer(htmlpdf_proposals_app, name="proposals")
notes_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Paperful-owned notes only (summaries, remarks, briefing). Never parent items.",
)
app.add_typer(notes_app, name="notes")
rag_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Library index behind `paperful ask`. Built from the on-disk mirror; "
        "it never calls the reference manager."
    ),
)
app.add_typer(rag_app, name="rag")
refs_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Bibliography coverage: cited-in-PDF works missing from the library.",
)
app.add_typer(refs_app, name="refs")
twenty_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Twenty CRM author lookup and sync (opt-in). "
        "lookup is read-only. sync --apply writes People. Never sends mail."
    ),
)
app.add_typer(twenty_app, name="twenty")
authorwatch_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "People lists: poll OpenAlex for those authors' new papers. "
        "Not snowball watch, not the PDF inbox folder. Does not scrape social sites."
    ),
)
app.add_typer(authorwatch_app, name="authorwatch")
network_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "ORCID ego co-authorship network: phase slices, SNA metrics, "
        "and Discover People map. Writes state/network/<run-id>/. "
        "Betweenness/brokerage need the network extra (NetworkX)."
    ),
)
app.add_typer(network_app, name="network")
keepup_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Alert loop and collection digests: poll watches / authorwatch / "
        "what-cites, then apply into -C. Paperful does not schedule; "
        "call keepup run from cron."
    ),
)
app.add_typer(keepup_app, name="keepup")


class _SearchGroup(TyperGroup):
    """`paperful search Gjerde` stays a query; `search watch` is the sub-app."""

    def resolve_command(  # type: ignore[override]
        self, ctx: typer.Context, args: list[str]
    ):
        args = list(args or [])
        names = set(self.list_commands(ctx))
        if args and args[0] in names:
            return super().resolve_command(ctx, args)
        return super().resolve_command(ctx, ["run", *args])


search_app = typer.Typer(
    cls=_SearchGroup,
    add_completion=False,
    no_args_is_help=False,
    help=(
        "Discover grey PDFs and landings via SearXNG. Metadata only; PDFs stay "
        "Wanted / run. Subcommand watch saves a recurring URL poll. Paperful "
        "does not schedule watches; call search watch run yourself. "
        "`search run` is implied when the first token is not a subcommand."
    ),
)
app.add_typer(search_app, name="search")
search_watch_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Pull-only grey watch: re-run a saved web query, remember seen URLs, "
        "propose new arrivals on disk. Never creates library items until "
        "watch apply. Paperful does not schedule watches."
    ),
)
search_app.add_typer(search_watch_app, name="watch")
collections_app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    help="Collection tree and membership batch (add existing keys).",
)
app.add_typer(collections_app, name="collections")
cache_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Manage throwaway files under state/pdf-cache/.",
)
app.add_typer(cache_app, name="cache")
openalex_store_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Optional OpenAlex parquet snapshot helpers (local or SSH DuckDB). "
        "Most installs leave [openalex_store] unset and use the live API."
    ),
)
app.add_typer(openalex_store_app, name="openalex-store")
critique_app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    help=(
        "Local manuscript critique pack: checked deterministic findings, "
        "optional LLM suggestions. --item KEY or --file PATH. Not a grade."
    ),
)
app.add_typer(critique_app, name="critique")
glossary_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "House glossary for critique acronym expansions. "
        "JSON files in state/glossary/; optional Vale swap export."
    ),
)
app.add_typer(glossary_app, name="glossary")

config_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Validate config.toml keys and secret placement.",
)
app.add_typer(config_app, name="config")

sr_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Systematic review protocol and screening (local; no scheduler).",
)
app.add_typer(sr_app, name="sr")

# Canonical top-level verbs. tests/test_cli.py asserts this matches `paperful --help`.
JOBS: dict[str, tuple[str, ...]] = {
    "library": (
        "collections",
        "import",
        "export",
        "export-proposals",
        "snowball",
        "ingest-dois",
        "twenty",
        "reachout",
        "authorwatch",
        "network",
        "keepup",
    ),
    "find": (
        "run",
        "attach",
        "recover",
        "gaps",
        "inbox",
        "capture",
        "urls",
        "htmlpdf",
        "search",
    ),
    "completeness": (
        "lint",
        "screen",
        "critique",
        "rewrite",
        "fix-metadata",
        "dedupe",
        "attachments",
        "versions",
        "ocr",
        "ocr-ignore",
        "summarize",
        "extract-sections",
        "synthesize",
        "rag",
        "ask",
        "refs",
        "coverage",
        "precedent",
        "stuff",
        "sr",
        "acronyms",
        "glossary",
        "authors",
        "notes",
        "all",
    ),
    "mirror": ("sync", "snapshot", "restore", "cache"),
    "control": (
        "doctor",
        "config",
        "session",
        "mirrors",
        "ezproxy",
        "scholar",
        "pack",
        "profile",
        "playbooks",
        "openalex-store",
        "mcp",
        "serve",
    ),
    "utility": (
        "report",
        "run-report-counts",
        "run-report-new-count",
        "version",
        "jobs",
    ),
}

from .cli_runtime import (
    console,
    _OFFLINE,
    _stdin_is_tty,
    _bind_run,
    _scope_unset,
    _refuse_missing_scope,
    _inbox_library_when_unscoped,
    _take_scope,
    _item_progress,
    _track,
    _spinner,
    _load_scope,
    _cfg,
    _typer_opt,
    _typer_enum_value,
    _resolve_source_names,
    _source_list,
    _zotero,
    _env_code,
    _zotero_next_steps,
    _print_exit_ladder,
    _exit_env,
    _warn_if_scihub,
    _warn_if_recover,
    _warn_if_camofox,
    _require_manager,
    _manager_name,
    _offline,
    _try_live,
    _mirror_first,
    _open_library,
    _live_backend,
    _connect,
    _no_write,
    _flush,
    _scope_error,
    _scope_keys,
    _resolve_types,
    _apply_item_filters,
    _loaded_scope,
    _opt_bool,
    _child_bytes,
    _print_attachment_table,
    _print_version_table,
    _print_dedupe_table,
    _ezproxy_headed_login_and_probe,
    _ensure_ezproxy_session,
    _preflight_ezproxy_session,
    _mid_run_ezproxy_hook,
    _maybe_ezproxy_relogin,
    _run_session_handoff,
    _inbox_handoff_session,
    _mirror_deferred,
    _library_write_api,
    _run_flags,
    _agent_json,
    _emit_agent,
    _agent_wins,
    _finish_run,
    _load_last_run,
    _rag_require,
    _rag_embedder,
    _rag_open,
    _rag_auto,
    _print_hits,
    _ask_once,
    _ask_questions,
)

from .snowball_cmd import _run_snowball


# Command signatures live in cli_bind so this module stays the app tree.
from . import cli_bind as _cli_bind

for _name, _value in vars(_cli_bind).items():
    if _name.startswith("__"):
        continue
    if _name not in globals():
        globals()[_name] = _value

if __name__ == "__main__":
    app()
