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
from .progress import Track, item_progress, pause_live, tracker
from rich.table import Table

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
        "Propose, promote, and probe grey-lit PDF playbooks. "
        "Not run-config profiles."
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
    ),
    "find": ("run", "attach", "recover", "gaps", "inbox", "urls", "htmlpdf"),
    "completeness": (
        "lint",
        "screen",
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
        "acronyms",
        "authors",
        "notes",
        "all",
    ),
    "mirror": ("sync", "snapshot", "restore", "cache"),
    "control": (
        "doctor",
        "session",
        "mirrors",
        "ezproxy",
        "scholar",
        "pack",
        "profile",
        "playbooks",
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

ConfigOpt = typer.Option(
    None, "--config", "-c", help="Path to config.toml", exists=True, dir_okay=False
)
AgentFormatOpt = typer.Option(
    "text",
    "--format",
    help="text (default) or json for agents. JSON is paperful.agent.json.v1.",
)
FetchPdfsOpt = typer.Option(
    None,
    "--fetch-pdfs",
    help="PDF mode after create: off, fast, or full. true means fast. Default: config, else off.",
)
MaxCandidatesOpt = typer.Option(
    None,
    "--max-candidates",
    help="Stop after this many new+exists rows. Use all for every row.",
)
PerHopLimitOpt = typer.Option(
    None,
    "--per-hop-limit",
    help="Neighbours per seed per hop. Use all for every neighbour.",
)
PerHopRankOpt = typer.Option(
    None,
    "--per-hop-rank",
    help="Which neighbours a numeric limit keeps: most-cited, least-cited, or random.",
)
KeywordLimitOpt = typer.Option(
    None,
    "--keyword-limit",
    help="How many of a work's OpenAlex keywords to expand (1–5). 5 uses every stored keyword. all is refused.",
)
KeywordHopLimitOpt = typer.Option(
    None,
    "--keyword-hop-limit",
    help="Works kept per seed on the keyword side. A positive integer. all is refused.",
)
KeywordMinScoreOpt = typer.Option(
    None,
    "--keyword-min-score",
    help="Drop seed keywords below this similarity. 0 keeps whatever OpenAlex assigned.",
)
CitesQueryOpt = typer.Option(
    None,
    "--cites-query",
    help=(
        "Only references and citing works that match this OpenAlex search "
        "(title, abstract, or full text). Needs refs or cites in the direction, and depth of at least 1."
    ),
)
StudyDesignOpt = typer.Option(
    [],
    "--study-design",
    help=(
        "OpenAlex study design filter (repeatable or comma-separated). "
        "Ids: randomized-controlled-trial, clinical-trial, observational-study, "
        "case-report, systematic-review, meta-analysis, study-protocol. "
        "Aliases: rct, meta, sr, observational, protocol, case, trial."
    ),
)
CreateTagOpt = typer.Option(
    [],
    "--tag",
    help="Extra tags on created parents (repeatable). Combined with config default_tags and from-<seed-slug>.",
)
DedupeScopeOpt = typer.Option(
    None,
    "--dedupe-scope",
    help="library, collection, or none. Crawl default: config/profile. apply defaults to library unless this flag is set.",
)
DedupeAfterOpt = typer.Option(
    None,
    "--dedupe-after",
    help="After create: off (default), classify, or apply. classify writes state/dedupe-packs/.",
)
AuthorSitePreflightOpt = typer.Option(
    None,
    "--author-site-preflight/--no-author-site-preflight",
    help="Opt-in co-author graph and proposed field pack. Default: config.",
)
StopRuleOpt = typer.Option(
    None,
    "--stop-rule",
    help=(
        "off, marginal_yield, asymptotic_coverage, budget, or any. "
        "Off walks every hop in one shot. A rule pauses after each hop for Keep/Skip. "
        "Default: config, else off."
    ),
)
StopEpsOpt = typer.Option(
    None,
    "--stop-eps",
    help="marginal_yield: Keep rate below this. Default 0.01.",
)
StopKOpt = typer.Option(
    None,
    "--stop-k",
    help="Consecutive low-yield iterations. The rule cannot fire before iteration k+1. Default 2.",
)
StopMaxScreenedOpt = typer.Option(
    None,
    "--stop-max-screened",
    help="budget: stop after this many screened new rows. 0 means no cap.",
)
TwentyWritebackOpt = typer.Option(
    None,
    "--twenty-writeback/--no-twenty-writeback",
    help=(
        "Append SearXNG or author-site personal pages onto a unique Twenty Person. "
        "Does not create People. Default: [twenty].writeback_listings (off)."
    ),
)
RequestRgOpt = typer.Option(
    None,
    "--request-rg/--no-request-rg",
    help=(
        "Open existing ResearchGate publication URLs in the system browser "
        "so you can click Request full-text. Paperful never clicks. Default: [request].channels."
    ),
)
ReRequestOpt = typer.Option(
    False,
    "--re-request",
    help="Open ResearchGate handoff tabs even if state/author-requests.jsonl already recorded them.",
)
SeedsFileOpt = typer.Option(
    None,
    "--seeds-file",
    help="One DOI or ORCID per line (# comments). Use - to read stdin.",
)
DIRECTION_HELP = (
    "refs, cites, both, keywords, similar, refs+keywords, cites+keywords, "
    "refs+similar, or refs+cites+keywords. both stays references plus cited-by."
)
ProfileOpt = typer.Option(
    None,
    "--profile",
    help="Named run config from [profiles.*] or profiles/<name>.toml beside config.toml.",
)
RunConfigFileOpt = typer.Option(
    None,
    "--run-config",
    "-f",
    help="Run-config TOML file. Overlays --profile when both are set.",
    exists=True,
    dir_okay=False,
)
LibraryOpt = typer.Option(
    None,
    "--library/--no-library",
    help="Whole library instead of --collection. --no-library clears library = true on a profile.",
)
YearFromOpt = typer.Option(
    None,
    "--year-from",
    help="Only items dated this year or later (inclusive). Undated items excluded.",
)
YearToOpt = typer.Option(
    None,
    "--year-to",
    help="Only items dated this year or earlier (inclusive). Undated items excluded.",
)
ItemTypeOpt = typer.Option(
    [],
    "--type",
    "-T",
    help=(
        "Only these Zotero item types (repeatable or comma-separated; "
        "e.g. journalArticle, 'Journal Article', report)."
    ),
)
TryAllOpt = typer.Option(
    None,
    "--try-all/--no-try-all",
    help=(
        "Try every configured source even when item metadata looks inapplicable. "
        "--no-try-all turns a profile default off."
    ),
)
RetryFailedOpt = typer.Option(
    None,
    "--retry-failed/--no-retry-failed",
    help="Retry items previously marked not_found. --no-retry-failed turns a profile default off.",
)
UpgradeLinkedOpt = typer.Option(
    None,
    "--upgrade-linked/--no-upgrade-linked",
    help=(
        "Also fetch items that only have a linked PDF URL. "
        "--no-upgrade-linked turns a profile default off."
    ),
)
UpgradeSnapshotOpt = typer.Option(
    None,
    "--upgrade-snapshot/--no-upgrade-snapshot",
    help=(
        "Re-fetch items whose only PDF is an HTML page snapshot. "
        "A native PDF replaces the snapshot unless --keep-snapshot."
    ),
)
NoAttachOpt = typer.Option(
    None,
    "--no-attach/--attach",
    help="Do not attach PDFs into Zotero. --attach turns a profile's no_attach off.",
)
StrictPdfDoiOpt = typer.Option(
    None,
    "--strict-pdf-doi/--no-strict-pdf-doi",
    help=(
        "Save a PDF whose DOI differs from the library item, but do not attach it. "
        "--no-strict-pdf-doi turns a profile default off."
    ),
)
EzproxyReloginOpt = typer.Option(
    None,
    "--ezproxy-relogin/--no-ezproxy-relogin",
    help=(
        "After a run, pause to re-login when the EZProxy session expired, "
        "then retry those items. Default follows ezproxy_relogin in config (on)."
    ),
)
SciHubOpt = typer.Option(
    None,
    "--scihub/--no-scihub",
    help=(
        "Opt in to Sci-Hub for this run (off by default; legal grey zone in some jurisdictions). "
        "--no-scihub turns a profile default off."
    ),
)
BrowserAgentOpt = typer.Option(
    None,
    "--browser-agent/--no-browser-agent",
    help=(
        "Auto-append the browser-agent recover lane when llm.enabled "
        "(default: [browser_agent].during_run). "
        "--no-browser-agent skips it for this run so other PDF lanes can be tested alone."
    ),
)
CamofoxOpt = typer.Option(
    None,
    "--camofox/--no-camofox",
    help=(
        "Auto-append the camofox recover lane when [camofox].enabled "
        "(default: [camofox].during_run). "
        "Needs an external camofox-browser server at [camofox].base_url. "
        "See docs/camofox.md."
    ),
)
ApplyOpt = typer.Option(
    None,
    "--apply/--no-apply",
    help="Write changes (metadata, summaries, or optional steps). --no-apply keeps the dry-run.",
)
OverwriteOpt = typer.Option(
    None,
    "--overwrite/--no-overwrite",
    help="Replace title/date/venue even when already set.",
)
StepsOpt = typer.Option(
    None,
    "--steps",
    help="Comma-separated commands, replacing the profile step list.",
)
SkipOpt = typer.Option(
    [],
    "--skip",
    help="Omit this step (repeatable or comma-separated).",
)

class WriteDest(str, Enum):
    disk = "disk"
    zotero = "zotero"
    both = "both"

class SummarizeOrder(str, Enum):
    newest = "newest"
    oldest = "oldest"
    library = "library"


@app.callback()
def _main(
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Do not contact the reference manager. Work from the mirror as it is.",
    ),
) -> None:
    """paperful."""
    from . import cli_runtime as _rt

    _rt._OFFLINE = offline

@app.command()
def jobs() -> None:
    """List canonical verbs for the five jobs (library, find, completeness, mirror, control)."""
    for name, verbs in JOBS.items():
        console.print(f"[bold]{name}[/]: {', '.join(verbs)}")
    console.print(
        "Snowball grows the library (metadata parents). "
        "Run fills PDFs for items already there. "
        "Reachout lists missing PDFs for author contact (no fetch, no mail). "
        "Twenty lookup caches CRM contacts locally. twenty sync --apply writes People."
    )

@app.command()
def mcp(config: Path | None = ConfigOpt) -> None:
    """Optional stdio MCP: read-only gaps, snowball preview, export, refs_gap, ask."""
    from .mcp_server import serve_stdio

    serve_stdio(_cfg(config))

@app.command()
def serve(
    host: str = typer.Option(
        "127.0.0.1",
        help="Bind address. Default is localhost only.",
    ),
    port: int = typer.Option(8765, help="TCP port."),
    config: Path | None = ConfigOpt,
) -> None:
    """Localhost workbench and JSON API. Needs paperful[serve]."""
    from .serve import SERVE_HINT, fastapi_available, run_server

    if not fastapi_available():
        console.print(f"[red]{SERVE_HINT}[/]")
        raise typer.Exit(1)
    run_server(_cfg(config), host=host, port=port)

@app.command()
def version() -> None:
    console.print(__version__)

@app.command()
def doctor(
    config: Path | None = ConfigOpt,
    guide: bool | None = typer.Option(
        None,
        "--guide/--no-guide",
        help="Walk through amber/red fixes interactively (default: on when stdin is a TTY)",
    ),
    probe: bool = typer.Option(
        False,
        "--probe/--no-probe",
        help="Hit Scholar / EZProxy session_ok (network); amber when files exist but CAS/captcha",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Print checks as JSON (name, status, code, detail)."
    ),
) -> None:
    """Check Zotero, paths, email, and optional browser sessions (green / amber / red)."""
    from .doctor_cmd import run_doctor

    run_doctor(
        console,
        config=config,
        guide=guide,
        probe=probe,
        as_json=as_json,
    )

@collections_app.callback(invoke_without_command=True)
def collections_root(
    ctx: typer.Context,
    config: Path | None = ConfigOpt,
) -> None:
    """Show the collection tree with item counts and how many lack a PDF."""
    if ctx.invoked_subcommand is not None:
        return
    from .collections_cmd import run_collections_show

    run_collections_show(console, config=config)


@collections_app.command("list")
def collections_list(config: Path | None = ConfigOpt) -> None:
    """Show the collection tree with item counts and how many lack a PDF."""
    from .collections_cmd import run_collections_show

    run_collections_show(console, config=config)


@collections_app.command("children")
def collections_children_cmd(
    parent: str = typer.Option(
        "ocean",
        "--parent",
        "-p",
        help="Parent collection path (default: ocean).",
    ),
    exclude: str = typer.Option(
        "BBNJ",
        "--exclude",
        help="Child collection name to omit (default: BBNJ).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Print child collection paths under --parent (for night batch scripts)."""
    from .collections_cmd import run_collections_children_paths

    for path in run_collections_children_paths(
        parent=parent,
        exclude_name=exclude or None,
        config=config,
    ):
        print(path)


@collections_app.command("add")
def collections_add_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Target collection path/name/key."
    ),
    keys_file: Path = typer.Option(
        ...,
        "--keys-file",
        help="Text file: one library item key per line.",
        exists=True,
        dir_okay=False,
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Add membership. Default is dry-run."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify only (default)."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """File existing item keys into a collection. Dry-run unless --apply. Does not create items."""
    from .collections_cmd import run_collections_add

    run_collections_add(
        console,
        collection=collection,
        keys_file=keys_file,
        apply=apply,
        dry_run=dry_run,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def lint(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(False, "--json", help="Legacy findings array. Prefer --format json."),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any finding."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Read-only check of identifiers vs APIs and PDF text on disk. Does not write to the manager."""
    from .lint_cmd import run_lint

    run_lint(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        as_json=as_json,
        strict=strict,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def screen(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(False, "--json", help="Legacy findings array. Prefer --format json."),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any finding."),
    apply: bool = typer.Option(False, "--apply", help="Write parent tag and child note for flagged items."),
    refresh: bool = typer.Option(
        False, "--refresh", help="Bypass status cache and re-download fingerprint CSVs."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Flag items using retraction APIs, optional PubPeer, and PPS fingerprint CSVs."""
    from .screen_cmd import run_screen

    run_screen(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        as_json=as_json,
        strict=strict,
        apply=apply,
        refresh=refresh,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def acronyms(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    min_count: int = typer.Option(
        2, "--min-count", min=1, help="Items a short token must appear in."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write state/acronyms/<scope>.json. Default prints the list only.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Harvest all-caps tokens from mixed-case titles, abstracts, and venues.

    Frequency and shape only. Does not call a model and does not recase titles.
    ``fix-metadata`` uses the written list when it Title-Cases an ALL CAPS title.
    """
    from .acronyms import file_slug, harvest, write_allowlist

    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
    bound = _bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    if not collection and not library:
        _refuse_missing_scope()
    backend = _connect(cfg, quiet=False)
    loaded = _load_scope(
        backend,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    rows = harvest(loaded.items, min_count=min_count)
    slug = file_slug(collection, library=library or not collection)
    console.print(
        f"Scope: [bold]{loaded.label}[/] — {len(loaded.items)} items, "
        f"{len(rows)} acronym{'s' if len(rows) != 1 else ''}"
    )
    if rows:
        table = Table(title="Acronyms")
        table.add_column("Token")
        table.add_column("Items", justify="right")
        for row in rows:
            table.add_row(row.token, str(row.count))
        console.print(table)
    else:
        console.print("[green]No acronyms at this count.[/]")
    if not apply:
        console.print("[dim]Dry-run. Pass --apply to write the allowlist.[/]")
        return
    path = write_allowlist(
        cfg.state_dir,
        slug,
        scope=loaded.label,
        rows=rows,
        min_count=min_count,
        n_items=len(loaded.items),
    )
    console.print(f"Wrote [bold]{path}[/]")

@app.command()
def authors(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    min_count: int = typer.Option(
        2, "--min-count", min=1, help="Items an author or org must appear in."
    ),
    max_authors: int = typer.Option(
        15,
        "--max-authors",
        min=1,
        help="Top people written into the proposed field author pack on --apply.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help=(
            "Write state/reports/<scope>-authors.json and seed "
            "state/author-packs/<slug>.proposed.toml. Default prints the tables only."
        ),
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Frequency report for creators in scope; seed a proposed field author pack.

    People are counted by name fingerprint; corporate ``name``-only creators are
    orgs. Dry-run prints tables. ``--apply`` writes the report and merges top
    people into a proposed pack (promote before ``author_site`` fetch).
    """
    from .authors_cmd import run_authors

    run_authors(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        min_count=min_count,
        max_authors=max_authors,
        apply=apply,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )

@app.command("fix-metadata")
def fix_metadata(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    apply: bool | None = ApplyOpt,
    overwrite: bool | None = OverwriteOpt,
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Propose bibliographic patches on disk; --apply writes them through the library adapter.

    `run` never rewrites metadata. This is the only write path for DOI/title/date/venue.
    """
    from .fix_metadata_cmd import run_fix_metadata

    run_fix_metadata(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        apply=apply,
        overwrite=overwrite,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )

@app.command()
def dedupe(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Write the pack only. This is the default; do not combine with --apply.",
    ),
    apply: bool | None = typer.Option(
        None,
        "--apply/--no-apply",
        help="Merge high_doi extras onto the keeper, then trash them (Zotero 10+). Title+year needs --apply-medium.",
    ),
    apply_medium: bool = typer.Option(
        False,
        "--apply-medium",
        help="Also merge title+year extras. Off by default.",
    ),
    phase: str = typer.Option(
        "all",
        "--phase",
        help="high_doi, grey_id, grey_host, medium_title_year, or all (default). Apply runs high_doi and grey_id first. grey_host needs --apply-medium.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(
        False, "--json", help="Legacy pack paths JSON. Prefer --format json."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Find duplicate parents and write a review pack. Merge only with --apply.

    Default is classify-only. ``--apply`` writes a plain-language line on each
    spare copy, then merges. Same-DOI groups whose titles diverge are held.
    A profile's ``apply`` flag does not merge; pass --apply on this command.
    """
    from .completeness_cmd import run_dedupe

    run_dedupe(
        console,
        collection=collection,
        library=library,
        dry_run=dry_run,
        apply=apply,
        apply_medium=apply_medium,
        phase=phase,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        as_json=as_json,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )

@app.command()
def attachments(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report only. This is the default; do not combine with --apply.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Run the named surgery flags. With no flags, this still only writes the report.",
    ),
    fix_broken: bool | None = typer.Option(
        None,
        "--fix-broken/--no-fix-broken",
        help="Refill a ghost or broken link from out/ when the MD5 matches.",
    ),
    merge_files: bool | None = typer.Option(
        None,
        "--merge-files/--no-merge-files",
        help="Trash extra PDF children on the same parent that share an MD5.",
    ),
    rename: bool | None = typer.Option(
        None,
        "--rename/--no-rename",
        help="Rename attachment files under out/ to the mirror stem.",
    ),
    link: bool | None = typer.Option(
        None,
        "--link/--no-link",
        help="Turn a stored PDF into a linked file under out/. Personal library only.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(False, "--json", help="Print the summary as JSON."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Compare attachments to the out/ mirror. Surgery needs a flag and --apply.

    Zotero can repair, rename, and link. Mendeley can upload and delete cloud
    files. EndNote only writes the report. ``--link`` is Zotero only.
    Paths outside out/ are never moved or deleted.
    """
    from .completeness_cmd import run_attachments

    run_attachments(
        console,
        collection=collection,
        library=library,
        dry_run=dry_run,
        apply=apply,
        fix_broken=fix_broken,
        merge_files=merge_files,
        rename=rename,
        link=link,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        as_json=as_json,
        profile=profile,
        run_config=run_config,
        config=config,
    )

@app.command()
def versions(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Write the pack only. This is the default; do not combine with --apply.",
    ),
    apply: bool | None = typer.Option(
        None,
        "--apply/--no-apply",
        help="Write the published citation onto the existing parent and keep the preprint as a version.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(
        False, "--json", help="Print pack paths and counts as JSON."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Link a preprint and its published paper as one work. Write only with --apply.

The older parent keeps the citation key. Its fields become the version of
record and the published PDF is attached beside the preprint PDF. A later
sibling is trashed only after that PDF is on the survivor. Title-only
matches are listed and not applied."""
    from .versions_cmd import run_versions

    run_versions(
        console,
        collection=collection,
        library=library,
        dry_run=dry_run,
        apply=apply,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        as_json=as_json,
        profile=profile,
        run_config=run_config,
        config=config,
    )

@app.command("urls")
def urls_check(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Rewrite a URL only when a grey playbook already knows the PDF target.",
    ),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """HEAD/GET metadata and linked-PDF URLs. Report only unless --apply."""
    import httpx

    from .agent_json import envelope
    from .urls import probe_target, targets_for_item

    if _scope_unset(collection, library, None, None):
        _refuse_missing_scope()
    started = time.time()
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    _require_manager(cfg)
    backend = _connect(cfg, quiet=json_out)
    keys, scope = _scope_keys(backend, collection, library)
    items = backend.items_in_scope(keys)
    if limit:
        items = items[:limit]
    findings = []
    applied = 0
    refused = 0
    with httpx.Client(follow_redirects=True, timeout=8.0) as client:
        for item in items:
            children = []
            if hasattr(backend, "children"):
                try:
                    children = backend.children(item.key)
                except Exception:
                    children = []
            for target in targets_for_item(item, children):
                finding = probe_target(
                    client, target, playbooks=cfg.grey_playbooks
                )
                row = finding.to_dict()
                if apply:
                    patch_key = (
                        finding.attachment_key
                        if finding.role == "linked_pdf" and finding.attachment_key
                        else item.key if finding.role == "parent" else ""
                    )
                    if not finding.rewrite or not patch_key or not backend.supports_write():
                        refused += 1
                        row["apply"] = "refused"
                    else:
                        backend.apply_patch(patch_key, {"url": finding.rewrite})
                        applied += 1
                        row["apply"] = "rewritten"
                findings.append(row)
    summary = {
        "scope": scope,
        "checked": len(findings),
        "applied": applied,
        "refused": refused,
    }
    for code in ("ok", "redirect", "soft_404", "hard_dead", "paywall_html"):
        summary[code] = sum(1 for row in findings if row["code"] == code)
    write_command_report(
        cfg,
        command="urls",
        scope=scope,
        summary=summary,
        items=findings,
        flags={"apply": apply},
        started=started,
    )
    payload = envelope(command="urls check", summary=summary, items=findings, flags={"apply": apply})

    def _human() -> None:
        table = Table(title="URL health")
        table.add_column("code")
        table.add_column("item")
        table.add_column("url")
        for row in findings:
            table.add_row(row["code"], row["item_key"], row["url"][:80])
        console.print(table)
        if apply:
            console.print(f"Rewrote {applied}. Refused {refused} (no known playbook rewrite).")

    _emit_agent(payload, json_out=json_out, human=_human)

@htmlpdf_proposals_app.command("list")
def htmlpdf_proposals_list(
    status: str = typer.Option("pending", "--status", help="pending, applied, rejected, or all."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .agent_json import envelope
    from .sources.htmlpdf import list_proposals

    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    want = None if status == "all" else status
    rows = list_proposals(cfg, status=want)
    payload = envelope(
        command="htmlpdf proposals list",
        summary={"count": len(rows)},
        items=rows,
        flags={"status": status},
    )

    def _human() -> None:
        if not rows:
            console.print("No HTML snapshot proposals.")
            return
        table = Table(title="htmlpdf proposals")
        table.add_column("id")
        table.add_column("item")
        table.add_column("status")
        for row in rows:
            table.add_row(str(row.get("id")), str(row.get("item_key")), str(row.get("status")))
        console.print(table)

    _emit_agent(payload, json_out=json_out, human=_human)

@htmlpdf_proposals_app.command("apply")
def htmlpdf_proposals_apply(
    proposal_id: str = typer.Argument(..., help="Proposal id."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .agent_json import envelope
    from .provenance import provenance_stamp
    from .sources.htmlpdf import load_proposal, mark_applied, proposal_gate

    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    _require_manager(cfg)
    backend = _connect(cfg, quiet=json_out)
    if not backend.supports_write():
        _exit_env("htmlpdf proposals apply needs library write support.", cfg)
    _path, payload_row = load_proposal(cfg, proposal_id)
    if payload_row.get("status") != "pending":
        console.print(f"[red]Proposal {proposal_id} is {payload_row.get('status') or 'not pending'}.[/]")
        raise typer.Exit(1)
    refusal = proposal_gate(payload_row)
    if refusal:
        console.print(f"[red]Proposal {proposal_id} failed the page gate ({refusal}).[/]")
        raise typer.Exit(1)
    pdf = Path(str(payload_row.get("pdf") or ""))
    item_key = str(payload_row.get("item_key") or "")
    if not pdf.is_file() or not item_key:
        console.print("[red]Proposal is missing a PDF or item key.[/]")
        raise typer.Exit(1)
    note = provenance_stamp("htmlpdf")
    result = backend.attach(item_key, pdf, note=note)
    if not result.ok:
        console.print(f"[red]{result.reason}[/]")
        raise typer.Exit(1)
    data = mark_applied(cfg, proposal_id, item_key=item_key)
    _flush(backend)
    payload = envelope(
        command="htmlpdf proposals apply",
        summary={"id": proposal_id, "item_key": item_key},
        items=[data],
        flags={"apply": True},
    )

    def _human_apply() -> None:
        console.print(f"Attached snapshot {proposal_id} → {item_key}")

    _emit_agent(payload, json_out=json_out, human=_human_apply)

@htmlpdf_proposals_app.command("reject")
def htmlpdf_proposals_reject(
    proposal_id: str = typer.Argument(..., help="Proposal id."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .agent_json import envelope
    from .sources.htmlpdf import reject_proposal

    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    try:
        data = reject_proposal(cfg, proposal_id)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    payload = envelope(
        command="htmlpdf proposals reject",
        summary={"id": proposal_id, "status": "rejected"},
        items=[data],
    )

    def _human_reject() -> None:
        console.print(f"Rejected proposal {proposal_id}")

    _emit_agent(payload, json_out=json_out, human=_human_reject)

@app.command()
def gaps(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    list_missing: bool = typer.Option(
        False,
        "--list-missing",
        help="List items with no stored PDF (key, title, DOI, URL, hint).",
    ),
    handoff: str | None = typer.Option(
        None,
        "--handoff",
        help=(
            "After listing: list (default), tabs (open URLs), walk (interactive "
            "Downloads ingest), or watch (tabs + poll the inbox.dir folder)."
        ),
    ),
    include_doi_tabs: bool = typer.Option(
        False,
        "--include-doi-tabs",
        help="With --handoff tabs|watch, also open doi.org for doi_only rows.",
    ),
    downloads_dir: Path | None = typer.Option(
        None,
        "--downloads-dir",
        help="Directory for --handoff walk newest-PDF pickup (default ~/Downloads).",
    ),
    request_rg: bool | None = RequestRgOpt,
    re_request: bool = ReRequestOpt,
    to: Path | None = typer.Option(
        None,
        "--to",
        help="Write the missing-PDF list to a .tsv or .md file.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Legacy counts JSON. Prefer --format json."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Count items with no stored PDF, a linked PDF URL only, or no DOI.

    Points at `run` (PDFs) and `lint` (identifiers). Does not write the library
    unless ``--handoff walk`` or ``--handoff watch`` attaches files.
    """
    from .gaps_cmd import run_gaps
    from .handoff import parse_handoff

    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
    from .author_request import apply_request_rg_override

    apply_request_rg_override(cfg, request_rg)
    json_out, as_json = _agent_wins(fmt, as_json)
    bound = _bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    if not collection and not library:
        _refuse_missing_scope()
    try:
        mode = parse_handoff(handoff, default=cfg.gaps_handoff)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if mode in {"tabs", "walk", "watch"} and not list_missing:
        list_missing = True
    _require_manager(cfg)
    quiet = as_json or json_out
    backend = _connect(cfg, quiet=quiet)
    loaded = _load_scope(
        backend,
        json_out=quiet,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    run_gaps(
        console,
        cfg,
        backend,
        loaded.items,
        loaded.label,
        list_missing=list_missing,
        mode=mode,
        json_out=json_out,
        as_json=as_json,
        to=to,
        include_doi_tabs=include_doi_tabs,
        downloads_dir=downloads_dir,
        re_request=re_request,
        emit_agent=_emit_agent,
        inbox_handoff=_inbox_handoff_session,
    )

@app.command()
def reachout(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    non_oa_only: bool = typer.Option(
        False,
        "--non-oa-only",
        help="Keep paywalled / no_oa / license_blocked misses only.",
    ),
    lookup: bool = typer.Option(
        False,
        "--lookup",
        help="When Twenty is enabled, search People for authors still missing an email.",
    ),
    to: Path | None = typer.Option(
        None,
        "--to",
        help="Write CSV (default), TSV, or Markdown (.csv / .tsv / .md).",
    ),
    handoff: str | None = typer.Option(
        None,
        "--handoff",
        help="list (default), tabs, or walk — ResearchGate publication URLs only.",
    ),
    request_rg: bool | None = RequestRgOpt,
    re_request: bool = ReRequestOpt,
    downloads_dir: Path | None = typer.Option(
        None,
        "--downloads-dir",
        help="Directory for --handoff walk newest-PDF pickup (default ~/Downloads).",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Contact authors for missing PDFs. Never fetches. Never sends mail."""
    from .reachout_cmd import run_reachout

    run_reachout(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        non_oa_only=non_oa_only,
        lookup=lookup,
        to=to,
        handoff=handoff,
        request_rg=request_rg,
        re_request=re_request,
        downloads_dir=downloads_dir,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )

@app.command()
def run(
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Collection path/name/key (repeatable). Subcollections included.",
    ),
    library: bool | None = LibraryOpt,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List what would be fetched; no network beyond Zotero."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    no_attach: bool | None = NoAttachOpt,
    retry_failed: bool | None = RetryFailedOpt,
    try_all: bool | None = TryAllOpt,
    sources: str | None = typer.Option(
        None,
        "--sources",
        help="Comma-separated source order override (or a preset name: oa, eoi).",
    ),
    preset: str | None = typer.Option(
        None,
        "--preset",
        help=(
            "Source preset. oa = open-access sources only (no EZProxy). "
            "eoi = OA + EZProxy, no Scholar or Sci-Hub (same as the default list)."
        ),
    ),
    scihub: bool | None = SciHubOpt,
    ezproxy_relogin: bool | None = EzproxyReloginOpt,
    browser_agent: bool | None = BrowserAgentOpt,
    camofox: bool | None = CamofoxOpt,
    upgrade_linked: bool | None = UpgradeLinkedOpt,
    upgrade_snapshot: bool | None = UpgradeSnapshotOpt,
    keep_snapshot: bool = typer.Option(
        False,
        "--keep-snapshot",
        help="With --upgrade-snapshot, leave the HTML print beside the new PDF.",
    ),
    htmlpdf_mode: str | None = typer.Option(
        None,
        "--htmlpdf",
        help="Academic HTML snapshot for this run: off, gated, or auto. Default off.",
    ),
    serpapi_max: int | None = typer.Option(
        None,
        "--serpapi-max",
        help="Cap paid SerpApi Scholar searches this run (0 = unlimited). Default [serpapi].max_calls.",
    ),
    strict_pdf_doi: bool | None = StrictPdfDoiOpt,
    handoff: str | None = typer.Option(
        None,
        "--handoff",
        help=(
            "After the run: list|tabs|walk|watch for soft-blocked openable PDF URLs. "
            "watch = tabs then poll the inbox.dir folder."
        ),
    ),
    include_doi_tabs: bool = typer.Option(
        False,
        "--include-doi-tabs",
        help="With --handoff tabs|watch, also open doi.org for doi_only rows.",
    ),
    downloads_dir: Path | None = typer.Option(
        None,
        "--downloads-dir",
        help="Downloads dir for --handoff walk (default ~/Downloads).",
    ),
    request_rg: bool | None = RequestRgOpt,
    re_request: bool = ReRequestOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    promote: str | None = typer.Option(
        None,
        "--promote",
        help="Override [playbooks].promote for this run: gated or auto.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Fill PDFs into the local mirror. Copies into the library when it is reachable. --dry-run does not write."""
    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
    from .author_request import apply_request_rg_override

    apply_request_rg_override(cfg, request_rg)
    twenty_writeback = _typer_opt(twenty_writeback)
    promote = _typer_opt(promote)
    upgrade_snapshot = _typer_opt(upgrade_snapshot)
    keep_snapshot = _typer_opt(keep_snapshot, False)
    htmlpdf_mode = _typer_opt(htmlpdf_mode)
    if twenty_writeback is not None:
        cfg.twenty_writeback_listings = twenty_writeback
    json_out = _agent_json(fmt)
    if isinstance(promote, str):
        from .config import parse_playbooks_promote

        try:
            cfg.playbooks_promote = parse_playbooks_promote(promote)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(2)
    bound = _bind_run(
        cfg,
        use_run_policy=True,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        no_attach=no_attach,
        retry_failed=retry_failed,
        try_all=try_all,
        sources=sources,
        preset=preset,
        scihub=scihub,
        upgrade_linked=upgrade_linked,
        upgrade_snapshot=upgrade_snapshot if isinstance(upgrade_snapshot, bool) else None,
        strict_pdf_doi=strict_pdf_doi,
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    limit = bound.limit
    no_attach = bound.no_attach
    retry_failed = bound.retry_failed
    try_all = bound.try_all
    sources = bound.sources_csv
    preset = bound.preset
    scihub = bound.scihub
    upgrade_linked = bound.upgrade_linked
    strict_pdf_doi = bound.strict_pdf_doi
    if isinstance(htmlpdf_mode, str) and htmlpdf_mode.strip():
        from .config import _one_of

        try:
            cfg.htmlpdf_academic = _one_of(
                "--htmlpdf", htmlpdf_mode, ("off", "gated", "auto")
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(2)
    if isinstance(serpapi_max, int):
        cfg.serpapi_max_calls = max(0, serpapi_max)
    if isinstance(upgrade_snapshot, bool):
        want_snapshot_upgrade = upgrade_snapshot
    elif bound.upgrade_snapshot is not None:
        want_snapshot_upgrade = bound.upgrade_snapshot
    else:
        want_snapshot_upgrade = cfg.htmlpdf_upgrade
    if keep_snapshot:
        cfg.htmlpdf_keep_snapshot = True
    # `all` calls this function directly. An omitted flag is a Typer option
    # object, not None; only an explicit bool overrides config.
    relogin = (
        ezproxy_relogin if isinstance(ezproxy_relogin, bool) else cfg.ezproxy_relogin
    )
    from .run_cmd import run_fetch

    run_fetch(
        console,
        cfg,
        collection=collection,
        library=library,
        dry_run=dry_run,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        no_attach=no_attach,
        retry_failed=retry_failed,
        try_all=try_all,
        sources=sources,
        preset=preset,
        scihub=scihub,
        relogin=relogin,
        browser_agent=browser_agent,
        upgrade_linked=upgrade_linked,
        want_snapshot_upgrade=want_snapshot_upgrade,
        strict_pdf_doi=strict_pdf_doi,
        handoff=handoff,
        include_doi_tabs=include_doi_tabs,
        downloads_dir=downloads_dir,
        re_request=re_request,
        json_out=json_out,
        camofox=camofox,
    )

@app.command()
def attach(
    item: list[str] = typer.Option(
        [], "--item", help="Attach a file to this item key."
    ),
    file: Path | None = typer.Option(
        None,
        "--file",
        help="PDF path for --item (manual download ingest).",
    ),
    config: Path | None = ConfigOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    allow_pdf_doi_mismatch: bool = typer.Option(
        False,
        "--allow-pdf-doi-mismatch",
        help="Also attach PDFs that --strict-pdf-doi left on disk.",
    ),
    allow_short_pdf: bool = typer.Option(
        False,
        "--allow-short-pdf",
        help="Also attach dense one-page PDFs held for admit.",
    ),
) -> None:
    """Write already-downloaded PDFs into the library. This command attaches; it is not a dry-run.

Use ``--item KEY --file PATH`` to ingest a hand-downloaded PDF."""
    from .attach_cmd import run_attach

    run_attach(
        console,
        item=item,
        file=file,
        config=config,
        limit=limit,
        allow_pdf_doi_mismatch=allow_pdf_doi_mismatch,
        allow_short_pdf=allow_short_pdf,
    )

@inbox_app.command("watch")
def inbox_watch(
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Optional narrow; omit (or pass --library) to match any missing-PDF item.",
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    idle: float | None = typer.Option(
        None,
        "--idle",
        help="Stop after this many idle seconds (default: inbox.idle_seconds, 0=forever).",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    tag: list[str] = CreateTagOpt,
) -> None:
    """Long-running sidecar: poll inbox.dir and attach by PDF DOI (no FIFO).

Defaults to the whole library so one drop folder can serve every topic.
Pass ``-C`` only when you intentionally want a narrower DOI index."""
    from .inbox_cmd import run_inbox_watch

    run_inbox_watch(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        idle=idle,
        profile=profile,
        run_config=run_config,
        config=config,
        tag=tag,
    )

@inbox_app.command("drain")
def inbox_drain(
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Optional narrow; omit (or pass --library) to match any missing-PDF item.",
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    tag: list[str] = CreateTagOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """One-shot: ingest current PDFs in inbox.dir.

Default match is DOI-only. ``[inbox].match`` can add title / OCR / LLM stages.
Defaults to the whole library so one drop folder can serve every topic.
Pass ``-C`` only when you intentionally want a narrower DOI index."""
    from .inbox_cmd import run_inbox_drain

    run_inbox_drain(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        profile=profile,
        run_config=run_config,
        config=config,
        tag=tag,
        fmt=fmt,
    )

inbox_proposals_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Gated inbox create/attach proposals. Never silent parent create.",
)
inbox_app.add_typer(inbox_proposals_app, name="proposals")

@inbox_proposals_app.command("list")
def inbox_proposals_list(
    status: str = typer.Option("pending", "--status", help="pending, applied, rejected, or all."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .inbox_cmd import run_inbox_proposals_list

    run_inbox_proposals_list(
        console,
        status=status,
        config=config,
        fmt=fmt,
    )

@inbox_proposals_app.command("apply")
def inbox_proposals_apply(
    proposal_id: str = typer.Argument(..., help="Proposal id from inbox proposals list."),
    tag: list[str] = CreateTagOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .inbox_cmd import run_inbox_proposals_apply

    run_inbox_proposals_apply(
        console,
        proposal_id=proposal_id,
        tag=tag,
        config=config,
        fmt=fmt,
    )

@inbox_proposals_app.command("reject")
def inbox_proposals_reject(
    proposal_id: str = typer.Argument(..., help="Proposal id from inbox proposals list."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .inbox_cmd import run_inbox_proposals_reject

    run_inbox_proposals_reject(
        console,
        proposal_id=proposal_id,
        config=config,
        fmt=fmt,
    )

@notes_app.command("delete")
def notes_delete(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    item: list[str] = typer.Option([], "--item", help="Parent item key (repeatable)."),
    note_type: list[str] = typer.Option(
        [],
        "--type",
        help="summary, review, attach, duplicate, linked, snowball, briefing (repeatable).",
    ),
    model: str = typer.Option("", "--model", help="Only notes from this LLM id."),
    except_model: str = typer.Option(
        "",
        "--except-model",
        help="Skip this LLM id. Without --type, only summary and review notes.",
    ),
    all_owned: bool = typer.Option(
        False,
        "--all",
        help="Every Paperful-owned note in scope. Never user notes.",
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Trash matched notes. Default is dry-run."
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip confirm on --apply --all (needed when not a TTY)."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = typer.Option(
        [],
        "-T",
        "--item-type",
        help="Only these Zotero parent item types (repeatable or comma-separated).",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Trash Paperful-owned notes. Never parent items. Dry-run unless --apply."""
    from .notes_delete_cmd import run_notes_delete

    run_notes_delete(
        console,
        collection=collection,
        library=library,
        item=item,
        note_type=note_type,
        model=model,
        except_model=except_model,
        all_owned=all_owned,
        apply=apply,
        yes=yes,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )

@refs_app.command("gap")
def refs_gap(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    item: list[str] = typer.Option([], "--item", help="Seed item keys (repeatable)."),
    pdf: list[Path] = typer.Option(
        [],
        "--pdf",
        help="Extra PDF paths to scan (repeatable).",
        exists=True,
        dir_okay=False,
    ),
    dedupe_scope: str = typer.Option(
        "library",
        "--dedupe-scope",
        help="Fingerprint exists against library or collection.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Works cited inside collection PDFs that are not in the library. Never writes."""
    from .refs_gap_cmd import run_refs_gap

    run_refs_gap(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        item=item,
        pdf=pdf,
        dedupe_scope=dedupe_scope,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("coverage")
def coverage_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection to check membership against."
    ),
    from_note: str | None = typer.Option(
        None,
        "--from-note",
        help="Zotero note key, or a path to note HTML/markdown.",
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Markdown / text / DOI list file.",
        exists=True,
        dir_okay=False,
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """DOIs named in a briefing/note/file that are not filed under -C. Always dry-run."""
    from .coverage_cmd import run_coverage

    run_coverage(
        console,
        collection=collection,
        from_note=from_note,
        from_file=from_file,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@twenty_app.command("lookup")
def twenty_lookup_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write proposed author-pack listings and state/author-contacts/. Default is dry-run.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Match collection authors against Twenty People. Read-only unless --apply."""
    from .twenty import authors_from_items, lookup_authors, twenty_ready

    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
    if not cfg.twenty_enabled:
        console.print(
            "[red]Twenty is off.[/] Set [twenty].enabled = true and TWENTY_API_KEY."
        )
        raise typer.Exit(1)
    if not twenty_ready(cfg):
        console.print(
            "[red]Twenty is not ready.[/] Set [twenty].base_url (or TWENTY_BASE_URL) "
            "and env TWENTY_API_KEY. Paperful never probes Twenty from doctor."
        )
        raise typer.Exit(1)
    bound = _bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    if not collection and not library:
        _refuse_missing_scope()
    _require_manager(cfg)
    backend = _connect(cfg)
    loaded = _load_scope(
        backend,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    authors = authors_from_items(loaded.items)
    label = collection[0] if collection else "library"
    if not loaded.items:
        console.print(
            f"[yellow]No items in scope ({label}).[/] "
            "Check the collection path (e.g. ocean/BBNJ vs a same-named empty folder)."
        )
        raise typer.Exit(1)
    if not authors:
        console.print(
            f"[yellow]{len(loaded.items)} item(s) in scope, but no creator names.[/]"
        )
        raise typer.Exit(1)
    rows = lookup_authors(
        cfg,
        authors,
        collection=label,
        apply=apply,
    )
    table = Table(title=f"Twenty lookup ({'apply' if apply else 'dry-run'})")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Website")
    table.add_column("Email")
    table.add_column("Note")
    for row in rows:
        table.add_row(
            row.query_name,
            row.status,
            (row.listing_url or (row.hit.website if row.hit else ""))[:50] or "-",
            (row.emails[0] if row.emails else "-"),
            row.note or "-",
        )
    console.print(table)
    matched = sum(1 for r in rows if r.status == "match")
    console.print(
        f"{len(rows)} authors · {matched} unique matches · "
        f"{sum(1 for r in rows if r.status == 'ambiguous')} ambiguous · "
        f"{sum(1 for r in rows if r.status == 'miss')} miss"
        f" · {len(loaded.items)} items"
    )
    if apply:
        console.print(
            "Wrote proposed pack listings (promote before author_site fetch) "
            "and contacts under state/author-contacts/. Paperful does not send mail."
        )
    else:
        console.print("[dim]Dry-run. Pass --apply to write proposed packs and contacts.[/]")

@twenty_app.command("sync")
def twenty_sync_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create and enrich Twenty People. Default is dry-run.",
    ),
    limit: int = typer.Option(
        0, "--limit", "-n", help="Only the first N person authors (0 = all)."
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip confirm when --apply would create many People."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Create or enrich Twenty People from collection authors. Dry-run unless --apply."""
    from .agent_json import EXIT_PARTIAL, envelope
    from .twenty import apply_sync_actions, plan_sync, twenty_ready

    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    if not cfg.twenty_enabled:
        console.print(
            "[red]Twenty is off.[/] Set [twenty].enabled = true and TWENTY_API_KEY."
        )
        raise typer.Exit(1)
    if not twenty_ready(cfg):
        console.print(
            "[red]Twenty is not ready.[/] Set [twenty].base_url (or TWENTY_BASE_URL) "
            "and env TWENTY_API_KEY."
        )
        raise typer.Exit(1)
    bound = _bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    if not collection and not library:
        _refuse_missing_scope()
    _require_manager(cfg)
    backend = _connect(cfg)
    loaded = _load_scope(
        backend,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    label = collection[0] if collection else "library"
    if not loaded.items:
        console.print(f"[yellow]No items in scope ({label}).[/]")
        raise typer.Exit(1)
    actions = plan_sync(cfg, loaded.items, collection=label, limit=limit)
    creates = [row for row in actions if row.action == "create"]
    if apply and len(creates) >= 50 and not yes:
        import sys

        if not sys.stdin.isatty():
            console.print(
                f"[red]{len(creates)} People would be created.[/] Pass --yes to confirm."
            )
            raise typer.Exit(1)
        if not typer.confirm(f"Create {len(creates)} Twenty People?"):
            raise typer.Exit(1)
    if apply:
        actions = apply_sync_actions(cfg, actions, collection=label)
    wrote = sum(1 for row in actions if row.note == "wrote")
    failed = sum(1 for row in actions if row.action == "miss-http")

    def _human() -> None:
        table = Table(title=f"Twenty sync ({'apply' if apply else 'dry-run'})")
        table.add_column("Name")
        table.add_column("Action")
        table.add_column("Note")
        for row in actions:
            table.add_row(row.name, row.action, (row.note or "-")[:80])
        console.print(table)
        console.print(
            f"{len(actions)} rows · "
            f"{sum(1 for row in actions if row.action == 'create')} create · "
            f"{sum(1 for row in actions if row.action == 'enrich')} enrich · "
            f"{sum(1 for row in actions if row.action == 'ambiguous')} ambiguous · "
            f"{sum(1 for row in actions if row.action == 'skip-corporate')} orgs · "
            f"{failed} http"
        )
        if apply:
            console.print(
                "Wrote People (keywords + a Paperful note) and state/author-contacts/. "
                "Paperful does not send mail."
            )
        else:
            console.print("[dim]Dry-run. Pass --apply to create and enrich People.[/]")

    code = 0
    if failed and wrote:
        code = EXIT_PARTIAL
    elif failed and apply:
        code = 1
    payload = envelope(
        command="twenty sync",
        summary={
            "rows": len(actions),
            "create": sum(1 for row in actions if row.action == "create"),
            "enrich": sum(1 for row in actions if row.action == "enrich"),
            "ambiguous": sum(1 for row in actions if row.action == "ambiguous"),
            "skip_corporate": sum(1 for row in actions if row.action == "skip-corporate"),
            "http_errors": failed,
            "items": len(loaded.items),
        },
        items=[
            {"name": row.name, "action": row.action, "note": row.note, "twenty_id": row.twenty_id}
            for row in actions
        ],
        flags={"apply": apply, "collection": label, "limit": limit},
        exit_code=code,
    )
    _emit_agent(payload, json_out=json_out, human=_human)

@app.command("ingest-dois")
def ingest_dois_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Target collection for new parents."
    ),
    from_file: Path | None = typer.Option(
        None, "--from-file", help="Text file: one DOI per line.", exists=True, dir_okay=False
    ),
    from_pack: Path | None = typer.Option(
        None,
        "--from-pack",
        help="refs_gap or coverage pack.json (or its parent folder).",
        exists=True,
    ),
    apply: bool = typer.Option(False, "--apply", help="Create parents. Default is dry-run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify only (default)."),
    tag: list[str] = typer.Option([], "--tag", help="Extra tags on created parents (repeatable)."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Create metadata parents from a DOI list. Dry-run unless --apply. Then run fills PDFs."""
    from .identity import LibraryFingerprint
    from .ingest_dois import (
        apply_creates,
        classify_rows,
        default_resolver,
        dois_from_file,
        dois_from_refs_pack,
        ingest_tags,
        write_summary,
    )

    if apply and dry_run:
        console.print("[red]Pass either --dry-run or --apply, not both.[/]")
        raise typer.Exit(1)
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    bound = _bind_run(cfg, profile=profile, run_config=run_config, collection=collection)
    collection, _library, _yf, _yt, _types = _take_scope(bound)
    if not collection:
        _refuse_missing_scope()
    if from_file is None and from_pack is None:
        console.print("[red]Pass --from-file dois.txt or --from-pack state/refs-gaps/.../pack.json[/]")
        raise typer.Exit(1)
    if from_pack is not None:
        pack_path = from_pack / "pack.json" if from_pack.is_dir() else from_pack
        dois = dois_from_refs_pack(pack_path)
        source_path = pack_path
    else:
        dois = dois_from_file(from_file)
        source_path = from_file
    if not dois:
        console.print("No DOIs to ingest.")
        raise typer.Exit(0)
    backend = _connect(cfg, quiet=json_out)
    all_items = list(backend.items_in_scope(None)) if hasattr(backend, "items_in_scope") else []
    fingerprint = LibraryFingerprint.from_items(
        all_items,
        scope=cfg.ingest_dedupe_scope,
        collection=collection[0],
    )
    works = {}
    resolver = default_resolver(cfg.email)

    def resolve(doi: str):
        work = resolver(doi)
        if work is not None:
            works[doi] = work
        return work

    from .acronyms import load_acronym_allowlist

    allowed = load_acronym_allowlist(cfg.state_dir)
    batch = classify_rows(dois, fingerprint, resolve=resolve, allowlist=allowed)
    tags = ingest_tags(
        cli_tags=tag, default_tags=cfg.ingest_default_tags, from_file=source_path
    )
    if apply:
        _require_manager(cfg)
        if not backend.supports_write():
            _exit_env("ingest-dois --apply needs library write support.", cfg)
        apply_creates(
            backend, batch, collection[0], works=works, tags=tags, allowlist=allowed
        )
        _flush(backend)
    folder = write_summary(cfg.state_dir, collection[0], batch)
    counts = batch.counts()
    from dataclasses import asdict as _asdict

    from .agent_json import envelope
    from .agent_ops import ingest_dois_exit

    payload = envelope(
        command="ingest-dois",
        summary=counts,
        items=[_asdict(row) for row in batch.rows],
        paths={"summary": str(folder)},
        flags={"apply": apply, "dry_run": not apply},
        exit_code=ingest_dois_exit(
            apply=apply, created=int(counts["created"]), failed=int(counts["failed"])
        ),
    )

    def _human_ingest() -> None:
        table = Table(title="ingest-dois")
        table.add_column("DOI")
        table.add_column("Status")
        table.add_column("Title")
        table.add_column("Detail")
        for row in batch.rows:
            table.add_row(row.doi, row.status, (row.title or "")[:50], row.detail)
        console.print(table)
        console.print(
            f"created {counts['created']} · exists {counts['exists']} · "
            f"unresolved {counts['unresolved']} · held {counts['held']}"
            + (" (dry-run)" if not apply else "")
        )
        console.print(f"Summary: {folder}")
        if apply and counts["created"]:
            console.print(f"Next: paperful run -C {collection[0]}")

    _emit_agent(payload, json_out=json_out, human=_human_ingest)

@app.command()
def snapshot(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Count what would be written. Still reads Zotero."
    ),
    pdfs: str | None = typer.Option(
        None,
        "--pdfs",
        help="all (also copy library PDFs), lazy (fetched PDFs only), or none.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Write per-item restore folders under out/. --dry-run counts and does not write."""
    from .snapshot import run_snapshot, snapshot_report

    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
    bound = _bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    limit = bound.limit
    if not collection and not library:
        _refuse_missing_scope()
    _require_manager(cfg)
    try:
        mode = parse_pdfs(pdfs) if pdfs else cfg.mirror_pdfs
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    backend = _live_backend(cfg)
    loaded = _load_scope(
        backend,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    if limit:
        items = items[:limit]
    manifest = Manifest(cfg.manifest_path)
    verb = "Would write" if dry_run else "Writing"
    console.print(
        f"{verb} restore folders for [bold]{len(items)}[/] items "
        f"in [bold]{scope}[/] (pdfs={mode})"
    )
    with _item_progress() as progress:
        stats = run_snapshot(
            cfg,
            backend,
            items,
            pdfs=mode,
            dry_run=dry_run,
            manifest=manifest,
            track=_track(progress, "Counting folders" if dry_run else "Writing folders"),
        )
    report = snapshot_report(cfg, scope, mode, dry_run, stats)
    if not dry_run:
        write_run_report(cfg, report, as_last_run=False)
    console.print(
        f"[bold]records {stats.records}[/] · pdf exports {stats.pdf_exports} · "
        f"notes {stats.notes}"
    )
    if stats.unread:
        console.print(
            f"[yellow]{stats.unread} item(s) could not be read. "
            "Their folders were left as they were; run snapshot again.[/]"
        )
    if not dry_run:
        # Exports do not go through the manifest, so name the items.
        _rag_auto(cfg, time.time(), keys=stats.pdf_keys)

def _print_sync(stats, *, dry_run: bool) -> None:
    was = "none" if stats.previous is None else f"v{stats.previous}"
    kind = "full" if stats.full else "changes since last refresh"
    verb = "would write" if dry_run else "written"
    console.print(
        f"[bold]library {was} → v{stats.version}[/] ({kind}) · "
        f"{verb} {stats.written} · left the library {stats.gone} · "
        f"pdfs copied {stats.pdf_exports}"
    )
    if stats.unread:
        console.print(
            f"[yellow]{stats.unread} item(s) could not be read. The mirror keeps "
            "what it had for them and the next refresh tries again.[/]"
        )
    if stats.unwritten:
        console.print(
            f"[yellow]{len(stats.unwritten)} item folder(s) could not be written. "
            "The next refresh tries again.[/]"
        )
        for line in stats.unwritten[:5]:
            console.print(f"[dim]  {line}[/]")
    if stats.pdf_missing:
        console.print(
            f"[yellow]{stats.pdf_missing} PDF(s) are listed in the library with no "
            "file behind them. See paperful attachments.[/]"
        )

@cache_app.command("clean")
def cache_clean(
    apply: bool | None = ApplyOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Remove pdf-cache files already in the mirror (or stale vs the record MD5).

    Dry-run unless ``--apply``. Does not touch ``out/``.
    """
    from .cache_cmd import run_cache_clean

    run_cache_clean(console, apply=apply, config=config, fmt=fmt)


@app.command()
def sync(
    full: bool = typer.Option(
        False, "--full", help="Read the whole library, not only what changed."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Count what would change. Reads the library, writes nothing."
    ),
    pdfs: str | None = typer.Option(
        None,
        "--pdfs",
        help="all (copy every library PDF into the mirror), lazy (on first use), or none.",
    ),
    accept_gone: bool = typer.Option(
        False,
        "--accept-gone",
        help="Proceed when most mirrored items are not in this library.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Bring out/ up to date with the library. Reads what changed since the last refresh."""
    from .snapshot import run_snapshot, snapshot_report
    from .sync import run_sync, sync_report

    cfg = _cfg(config)
    _require_manager(cfg)
    try:
        mode = parse_pdfs(pdfs) if pdfs else cfg.mirror_pdfs
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    backend = _live_backend(cfg)
    if not callable(getattr(backend, "changes", None)):
        # No change feed on this manager: read it whole, as snapshot does.
        loaded = _load_scope(
            backend, collection=[], library=True, year_from=None, year_to=None, item_type=[]
        )
        with _item_progress() as progress:
            snap = run_snapshot(
                cfg,
                backend,
                loaded.items,
                pdfs=mode,
                dry_run=dry_run,
                manifest=Manifest(cfg.manifest_path),
                track=_track(progress, "Writing folders"),
            )
        if not dry_run:
            write_run_report(
                cfg,
                snapshot_report(cfg, loaded.label, mode, dry_run, snap),
                as_last_run=False,
            )
        console.print(
            f"[bold]records {snap.records}[/] · pdf exports {snap.pdf_exports} · "
            f"notes {snap.notes}"
        )
        return
    try:
        with _item_progress() as progress:
            stats = run_sync(
                cfg,
                backend,
                full=full,
                dry_run=dry_run,
                pdfs=mode,
                accept_gone=accept_gone,
                track=_track(progress, "Writing items"),
                pdf_track=_track(progress, "Copying PDFs"),
                status=lambda msg: progress.console.print(f"[dim]{msg}[/]"),
            )
    except LibraryError as exc:
        _exit_env(str(exc), cfg)
    if not dry_run:
        write_run_report(
            cfg, sync_report(cfg, stats, dry_run=dry_run, pdfs=mode), as_last_run=False
        )
    _print_sync(stats, dry_run=dry_run)
    if not dry_run:
        # Copies do not go through the manifest, so name the items.
        _rag_auto(cfg, time.time(), keys=stats.pdf_keys)

@app.command()
def restore(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = typer.Option(
        None,
        "--library/--no-library",
        help="Whole out/ tree instead of one collection. --no-library clears a profile.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Stop after N folders."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be created. Does not write the library.",
    ),
    apply: bool | None = typer.Option(
        None,
        "--apply/--no-apply",
        help="Create missing items, attach local PDFs, and add missing notes.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Recreate missing library items from out/. Dry-run unless --apply. Never overwrites fields."""
    from .restore import (
        apply_restore,
        dedupe_restore_records,
        iter_records,
        plan_restore,
        record_in_scope,
    )

    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    bound = _bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        apply=apply,
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    limit = bound.limit
    apply = bound.apply
    if dry_run and apply:
        console.print("[red]Pass either --dry-run or --apply, not both.[/]")
        raise typer.Exit(1)
    if not collection and not library:
        _refuse_missing_scope()
    _require_manager(cfg)
    backend = _live_backend(cfg, quiet=json_out)
    prefixes: list[str] | None = None
    if not library:
        prefixes = []
        for spec in collection:
            try:
                root = backend.resolve_collection(spec)
            except LookupError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1) from exc
            prefixes.append(root.path)
    paths = iter_records(cfg.out_dir, prefixes)
    records = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict):
            records.append((path, data))
    types = _resolve_types(item_type)
    if year_from is not None and year_to is not None and year_from > year_to:
        console.print("[red]--year-from must be ≤ --year-to.[/]")
        raise typer.Exit(1)
    records = [
        pair
        for pair in records
        if record_in_scope(
            pair[1], year_from=year_from, year_to=year_to, item_types=types
        )
    ]
    records = dedupe_restore_records(records)
    if limit:
        records = records[:limit]
    keys, _scope = _scope_keys(backend, collection, library)
    with _spinner("Loading items from library…", json_out=json_out):
        library_items = backend.items_in_scope(keys)
    with _item_progress(json_out=json_out) as progress:
        note_tags: dict[str, set[str]] = {}
        for it in _track(progress, "Reading library notes")(library_items):
            tags: set[str] = set()
            try:
                kids = backend.children(it.key)
            except LibraryError as exc:
                _exit_env(str(exc), cfg)
            for ch in kids:
                data = ch.get("data") or {}
                if data.get("itemType") != "note":
                    continue
                for tag in data.get("tags") or []:
                    if isinstance(tag, dict) and tag.get("tag"):
                        tags.add(str(tag["tag"]))
            if tags:
                note_tags[it.key] = tags
    planned = plan_restore(records, library_items, note_tags_for=note_tags)
    counts = planned.counts()
    from .agent_json import envelope

    if not apply:
        payload = envelope(
            command="restore",
            summary={"folders": len(records), **counts},
            flags={"dry_run": True},
        )

        def _human_restore() -> None:
            console.print(
                f"{len(records)} restore folder(s) · "
                f"create {counts.get('create_item', 0)} · "
                f"exists {counts.get('exists', 0)} · "
                f"skip {counts.get('skip', 0)} · "
                f"attach {counts.get('attach_pdf', 0)} · "
                f"notes {counts.get('create_note', 0)}"
            )
            console.print(
                "[dim]Dry run. Pass --apply to write missing items into the library.[/]"
            )

        _emit_agent(payload, json_out=json_out, human=_human_restore)
        return
    with _item_progress(json_out=json_out) as progress:
        done = apply_restore(
            planned, backend, backend, track=_track(progress, "Restoring items")
        )
    payload = envelope(
        command="restore",
        summary=dict(done),
        flags={"apply": True},
    )

    def _human_restore_done() -> None:
        console.print(
            f"[bold]created {done['create_item']}[/] · "
            f"attached {done['attach_pdf']} · notes {done['create_note']}"
        )

    _emit_agent(payload, json_out=json_out, human=_human_restore_done)
    _flush(backend)

@app.command("import")
def import_library(
    path: Path = typer.Argument(
        ..., exists=True, dir_okay=False, help="RIS, BibTeX, or EndNote XML file."
    ),
    fmt: str | None = typer.Option(
        None,
        "--format",
        help="ris, bibtex, endnote-xml, or json (agent envelope; file type from the suffix).",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write into the current manager. Default is a dry-run count.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Import a bibliography file. Default is a dry-run count; --apply writes the library."""
    from .interop.load import load_records
    from .xfer import apply_import

    cfg = _cfg(config)
    _require_manager(cfg)
    json_out = False
    file_fmt = fmt
    if (fmt or "").strip().lower() == "json":
        json_out = True
        file_fmt = None
    try:
        records = load_records(path, file_fmt)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    n_pdf = sum(1 for r in records if r.get("pdfs"))
    n_notes = sum(len(r.get("notes") or []) for r in records)
    if not apply:
        from .agent_json import envelope

        payload = envelope(
            command="import",
            summary={
                "records": len(records),
                "pdfs": n_pdf,
                "notes": n_notes,
            },
            flags={"dry_run": True},
        )

        def _human_imp() -> None:
            console.print(f"{len(records)} record(s) in {path.name}")
            console.print(
                f"[dim]Dry run. Pass --apply to create {len(records)} items, "
                f"attach {n_pdf} PDF path(s), add {n_notes} note(s).[/]"
            )

        _emit_agent(payload, json_out=json_out, human=_human_imp)
        return
    backend = _connect(cfg, quiet=json_out)
    if not backend.supports_write():
        _exit_env(_no_write(backend), cfg)
    with _item_progress(json_out=json_out) as progress:
        done = apply_import(
            records, backend, dry_run=False, track=_track(progress, "Importing records")
        )
    from .agent_json import envelope

    payload = envelope(
        command="import",
        summary=dict(done),
        flags={"apply": True},
    )

    def _human_imp_done() -> None:
        console.print(
            f"[bold]created {done['create']}[/] · attached {done['attach']} · "
            f"notes {done['notes']}"
            + (f" · missing PDFs {done['skipped_pdf']}" if done.get("skipped_pdf") else "")
        )

    _emit_agent(payload, json_out=json_out, human=_human_imp_done)
    _flush(backend)

@app.command("export")
def export_library(
    dest: Path = typer.Argument(
        ..., help="Output .ris / .bib / .xml file (or a folder for EndNote XML)."
    ),
    fmt: str | None = typer.Option(
        None,
        "--format",
        help="ris, bibtex, or endnote-xml. Default: from the file suffix.",
    ),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool = typer.Option(False, "--library", help="Whole library."),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    pdfs: bool = typer.Option(
        False,
        "--pdfs/--no-pdfs",
        help="Copy PDFs next to the export (needed for EndNote XML).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Export the scoped library to RIS, BibTeX, or EndNote XML."""
    from .export_cmd import run_export_library

    run_export_library(
        console,
        dest=dest,
        fmt=fmt,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        pdfs=pdfs,
        config=config,
    )


@app.command("export-proposals")
def export_proposals(
    pack: Path = typer.Argument(
        ...,
        help=(
            "Snowball run dir, watch dir, authorwatch dir, or a candidates/inbox "
            ".jsonl file under state/."
        ),
    ),
    dest: Path = typer.Argument(..., help="Output .bib or .ris file."),
    fmt: str | None = typer.Option(
        None,
        "--format",
        help="bibtex or ris. Default: from the file suffix.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Export BibTeX or RIS from an on-disk snowball or authorwatch proposal pack."""
    from .pack_bib import export_pack_text

    cfg = _cfg(config)
    kind = (fmt or dest.suffix.lstrip(".") or "").lower().replace("_", "-")
    if kind in {"bib", "biblatex"}:
        kind = "bibtex"
    if kind not in {"ris", "bibtex"}:
        console.print("[red]--format must be bibtex or ris.[/]")
        raise typer.Exit(1)
    path = pack
    if not path.is_absolute():
        path = cfg.state_dir / path
    try:
        text, jsonl, n = export_pack_text(path, kind)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    console.print(
        f"[green]Wrote[/] {dest} ({n} records from {jsonl.name})"
    )


@app.command("run-report-counts")
def run_report_counts_cmd(
    report_file: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        help="paperful run report JSON from state/runs/",
    ),
) -> None:
    """One-line counts summary for Nightshift index lines."""
    import json

    from .runreport import nightshift_counts_line

    payload = json.loads(report_file.read_text(encoding="utf-8"))
    print(nightshift_counts_line(payload))


@app.command("run-report-new-count")
def run_report_new_count_cmd(
    report_file: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        help="paperful summarize run report JSON",
    ),
) -> None:
    """Count new model summaries in a run report (skips do not count)."""
    import json

    from .runreport import nightshift_report_new_count

    payload = json.loads(report_file.read_text(encoding="utf-8"))
    print(nightshift_report_new_count(payload))


@app.command()
def report(
    config: Path | None = ConfigOpt,
    not_found: bool = typer.Option(
        False, "--not-found", help="List not_found items with DOIs."
    ),
    status: str | None = typer.Option(
        None, "--status", help="List items with this status."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Machine-readable summary for agents."
    ),
    last_run: bool = typer.Option(
        False, "--last-run", help="Show only the latest run report summary."
    ),
) -> None:
    """Summarise the manifest and the latest auditable run report."""
    cfg = _cfg(config)
    manifest = Manifest(cfg.manifest_path)
    last = _load_last_run(cfg)
    if as_json:
        payload = manifest.report_payload(last)
        console.print(json.dumps(payload, indent=2))
        raise typer.Exit(0)
    if last and last.get("schema") == "paperful.run_report.v1":
        print_run_summary(console, last, cfg.state_dir / "last-run.json")
        if last_run:
            raise typer.Exit(0)
        console.print()
    elif last_run:
        console.print("No auditable run report yet. Run [bold]paperful run[/] first.")
        raise typer.Exit(1)
    if not manifest.records:
        console.print("Manifest is empty.")
        raise typer.Exit(0)
    table = Table(title=f"{len(manifest.records)} items in manifest (all runs)")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for k, v in sorted(manifest.counts().items(), key=lambda kv: -kv[1]):
        table.add_row(k, str(v))
    console.print(table)
    by_src = manifest.by_source()
    if by_src:
        console.print(
            "PDFs by source: "
            + ", ".join(
                f"{k}={v}" for k, v in sorted(by_src.items(), key=lambda kv: -kv[1])
            )
        )
    want = STATUS_NOT_FOUND if not_found else status
    if want:
        rows = [r for r in manifest.records.values() if r.status == want]
        t = Table(title=f"{len(rows)} items with status {want}")
        t.add_column("Key", style="dim")
        t.add_column("Title")
        t.add_column("DOI")
        t.add_column("Attempts" if want != STATUS_ATTACHED else "Path")
        for r in sorted(rows, key=lambda r: r.title.lower()):
            t.add_row(
                r.itemKey,
                r.title[:70],
                r.doi or "-",
                (
                    (r.path or "")
                    if want == STATUS_ATTACHED
                    else " ".join(r.attempts)[-90:]
                ),
            )
        console.print(t)

@pack_app.command("open")
def pack_open(
    label: str | None = typer.Option(None, "--label", help="Name stored on the pack."),
    config: Path | None = ConfigOpt,
) -> None:
    """Start a pack. Later commands append their run reports until `pack close`."""
    from .pack_cmd import run_pack_open

    run_pack_open(console, label=label, config=config)


@pack_app.command("close")
def pack_close(config: Path | None = ConfigOpt) -> None:
    """Close the open pack and drop the current pointer."""
    from .pack_cmd import run_pack_close

    run_pack_close(console, config=config)


@pack_app.command("show")
def pack_show(
    as_json: bool = typer.Option(
        False, "--json", help="Parent pack plus each step's summary."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Print the open pack, or the latest closed one. Does not open the library."""
    from .pack_cmd import run_pack_show

    run_pack_show(console, as_json=as_json, config=config)


@app.command()
def mirrors(config: Path | None = ConfigOpt) -> None:
    """Ping the configured Sci-Hub mirrors."""
    from .mirrors_cmd import run_mirrors

    run_mirrors(console, config=config)


@session_app.command("login")
def session_login(
    slot: str = typer.Argument(..., help="scholar, ezproxy, or mendeley"),
    config: Path | None = ConfigOpt,
    engine: str = typer.Option(
        "auto",
        "--engine",
        help="Browser for headed login: auto (system Chrome if present), chrome, playwright",
    ),
) -> None:
    """Open a headed browser on the local vault; log in once, reuse on run."""
    from .session_cmd import run_session_login

    run_session_login(console, slot=slot, config=config, engine=engine)


@session_app.command("status")
def session_status(
    config: Path | None = ConfigOpt,
    probe: bool = typer.Option(
        False, "--probe/--no-probe", help="Hit Scholar / EZProxy session_ok (network)"
    ),
) -> None:
    """Show the vault. Default is offline file presence; --probe runs session_ok."""
    from .session_cmd import run_session_status

    run_session_status(console, config=config, probe=probe)


@session_app.command("export")
def session_export(config: Path | None = ConfigOpt) -> None:
    """Refresh storage_state + Netscape from the vault (keeps session tickets)."""
    from .session_cmd import run_session_export

    run_session_export(console, config=config)


@app.command("ezproxy")
def ezproxy_cmd(
    config: Path | None = ConfigOpt,
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open headed Chromium (or the system browser)"
    ),
) -> None:
    """Check / refresh the campus EZProxy session (wrapper for session login ezproxy)."""
    from .session_cmd import run_ezproxy

    run_ezproxy(console, config=config, open_browser=open_browser)


@app.command("scholar")
def scholar_cmd(
    config: Path | None = ConfigOpt,
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open headed Chromium (or the system browser)"
    ),
) -> None:
    """Check / refresh Google Scholar (wrapper for session login scholar)."""
    from .session_cmd import run_scholar

    run_scholar(console, config=config, open_browser=open_browser)


@app.command()
def recover(
    item: list[str] = typer.Option(
        [], "--item", help="Zotero item key to recover (repeatable)."
    ),
    from_last_run: bool = typer.Option(
        False,
        "--from-last-run",
        help="Recover items from state/last-run.json (see --from-last-run-mode).",
    ),
    from_last_run_mode: str = typer.Option(
        "browser_agent_miss",
        "--from-last-run-mode",
        help="browser_agent_miss | missing | browser_agent_not_found",
    ),
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Stop after N items (batch recover)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show start URL only; no browser agent."
    ),
    no_attach: bool = typer.Option(
        False, "--no-attach", help="Download to out/ only; do not attach in Zotero."
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Browser-agent PDF recovery for named items (also auto-fires at the end of run)."""
    from .recover_cmd import run_recover

    run_recover(
        console,
        item=item,
        from_last_run=from_last_run,
        from_last_run_mode=from_last_run_mode,
        limit=limit,
        dry_run=dry_run,
        no_attach=no_attach,
        config=config,
        fmt=fmt,
    )

@app.command()
def ocr(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection scope (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    apply: bool = typer.Option(
        False, "--apply", help="Run OCRmyPDF and replace the on-disk PDF."
    ),
    attach: bool = typer.Option(
        False,
        "--attach",
        help="After --apply, upload the text-layer PDF as a new attachment. The scan stays.",
    ),
    force_retry: bool = typer.Option(
        False,
        "--force-retry",
        help="Run OCR on items in state/ocr-ignore.jsonl (normally skipped).",
    ),
    no_auto_ignore_failures: bool = typer.Option(
        False,
        "--no-auto-ignore-failures",
        help="Do not append failed or missing items to the OCR ignore list after --apply.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    max_minutes: float | None = typer.Option(
        None,
        "--max-minutes",
        min=0,
        help="Stop after this many minutes (finishes the PDF in hand).",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Add a text layer to scanned PDFs on disk. Dry-run unless --apply."""
    from .ocr_cmd import run_ocr

    run_ocr(
        console,
        item=item,
        collection=collection,
        library=library,
        apply=apply,
        attach=attach,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        max_minutes=_typer_opt(max_minutes),
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
        force_retry=force_retry,
        no_auto_ignore_failures=no_auto_ignore_failures,
    )


ocr_ignore_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Skip list for ``paperful ocr`` (failed or missing PDFs). Ledger: state/ocr-ignore.jsonl.",
)
app.add_typer(ocr_ignore_app, name="ocr-ignore")


@ocr_ignore_app.command("list")
def ocr_ignore_list(
    config: Path | None = ConfigOpt,
) -> None:
    """Show ignored item keys."""
    from .ocr_ignore_cmd import run_ocr_ignore_list

    run_ocr_ignore_list(console, config=config)


@ocr_ignore_app.command("add")
def ocr_ignore_add(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    reason: str = typer.Option("", "--reason", help="Why this item is ignored."),
    config: Path | None = ConfigOpt,
) -> None:
    """Add item keys to the OCR ignore list."""
    from .ocr_ignore_cmd import run_ocr_ignore_add

    run_ocr_ignore_add(console, item=item, reason=reason, config=config)


@ocr_ignore_app.command("remove")
def ocr_ignore_remove(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    config: Path | None = ConfigOpt,
) -> None:
    """Remove item keys from the OCR ignore list."""
    from .ocr_ignore_cmd import run_ocr_ignore_remove

    run_ocr_ignore_remove(console, item=item, config=config)


@ocr_ignore_app.command("import-failures")
def ocr_ignore_import_failures(
    report: Path | None = typer.Option(
        None,
        "--report",
        help="OCR run report JSON (default: newest state/runs/*-ocr.json).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Add every failed or missing row from an OCR run report to the ignore list."""
    from .ocr_ignore_cmd import run_ocr_ignore_import_failures

    run_ocr_ignore_import_failures(console, report=report, config=config)


# ---- library index: `paperful rag` and `paperful ask` -------------------------
# These read out_dir and state_dir only. None of them opens the reference manager.

@rag_app.command("ingest")
def rag_ingest(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Collection path under the mirror (repeatable).",
    ),
    library: bool | None = LibraryOpt,
    force: bool = typer.Option(
        False, "--force", help="Re-index items even when nothing changed."
    ),
    retry_failed: bool = typer.Option(
        False,
        "--retry-failed",
        help="Try again the PDFs that failed on an earlier run.",
    ),
    no_ocr: bool = typer.Option(
        False, "--no-ocr", help="Do not run OCR on scans this run."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be indexed. Writes nothing."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Index at most this many items this run."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Index PDFs and abstracts from the mirror. Scans get OCR first; text PDFs do not."""
    from .llm import LLMClientError
    from .rag.index import IndexMismatch, RagUnavailable
    from .rag.ingest import ingest_entries, select_entries

    if not item and _scope_unset(collection, library, profile, run_config):
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    cfg = _cfg(config)
    bound = _bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    limit = bound.limit
    if not item and not collection and not library:
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    _rag_require(cfg)
    types = _resolve_types(item_type)
    embedder = None if dry_run else _rag_embedder(cfg)
    started = time.time()
    with _spinner("Reading the mirror…"):
        entries = select_entries(
            cfg,
            collections=None if library else collection,
            item_keys=item,
            year_from=year_from,
            year_to=year_to,
            item_types=types,
        )
    scope = "library" if library else ", ".join(collection) or f"{len(item)} item(s)"
    whole_mirror = bool(library) and not item and types is None
    whole_mirror = whole_mirror and year_from is None and year_to is None
    try:
        with _item_progress() as progress:
            batch = ingest_entries(
                cfg,
                entries,
                force=force,
                retry_failed=retry_failed,
                ocr=not no_ocr,
                dry_run=dry_run,
                prune=whole_mirror and limit is None,
                limit=limit,
                track=_track(progress, "Indexing"),
                ocr_track=_track(progress, "Running OCR"),
                embedder=embedder,
            )
    except (RagUnavailable, IndexMismatch) as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    except LLMClientError as exc:
        console.print(f"Stopped: {exc}", markup=False, style="red")
        console.print("Items indexed so far are kept. Run again to continue.")
        raise typer.Exit(1) from exc
    changed = [r for r in batch.rows if r.status not in ("unchanged", "nothing")]
    failed = [r for r in changed if r.status == "failed"]
    shown = changed if len(changed) <= 30 else failed[:30]
    if shown:
        table = Table(title="paperful rag ingest" + (" (dry-run)" if dry_run else ""))
        table.add_column("Key")
        table.add_column("Title")
        table.add_column("From")
        table.add_column("Passages", justify="right")
        table.add_column("Why")
        for row in shown:
            title = row.title if len(row.title) <= 60 else row.title[:57] + "…"
            table.add_row(row.key, title, row.status, str(row.chunks or ""), row.reason)
        console.print(table)
    summary = batch.summary()
    write_command_report(
        cfg,
        command="rag-ingest",
        scope=scope,
        summary=dict(summary),
        items=[
            {
                "itemKey": r.key,
                "title": r.title,
                "status": r.status,
                "reason": r.reason,
                "chunks": r.chunks,
            }
            for r in changed
        ],
        flags={
            "force": force,
            "retry_failed": retry_failed,
            "no_ocr": no_ocr,
            "dry_run": dry_run,
            "embed_model": cfg.rag_embed_model,
        },
        started=started,
    )
    lead = "Would index" if dry_run else "Indexed"
    console.print(
        f"{lead} {summary['pdf'] + summary['ocr']} PDFs "
        f"({summary['ocr']} after OCR) and {summary['abstract']} abstracts"
        + ("" if dry_run else f", {summary['chunks']} passages")
        + f". Unchanged {summary['unchanged']}, nothing to index "
        f"{summary['empty']}, removed {summary['removed']}, "
        f"failed {summary['failed']}."
    )
    if dry_run:
        console.print("Run without --dry-run to build the index.")

@rag_app.command("status")
def rag_status(
    json_out: bool = typer.Option(False, "--json", help="Print JSON."),
    config: Path | None = ConfigOpt,
) -> None:
    """What the index holds and how far it is behind the mirror."""
    from .rag.status import index_status
    from .store import mirror_entries

    cfg = _cfg(config)
    with _spinner("Reading the mirror…", json_out=json_out):
        status = index_status(cfg, mirror_entries(cfg.out_dir))
    if json_out:
        console.print(
            json.dumps(status, indent=2), soft_wrap=True, highlight=False, markup=False
        )
        return
    mirror = status["mirror"]
    table = Table(title="paperful rag status")
    table.add_column("What")
    table.add_column("Value")
    rows = [
        ("Enabled", "yes" if status["enabled"] else "no (rag.enabled is false)"),
        ("Embedding model", f"{status['embed_provider']} / {status['embed_model']}"),
        ("Index", status["path"] if status["exists"] else "not built yet"),
        ("Items indexed", str(status["items_pdf"] + status["items_abstract"])),
        ("  from PDF text", str(status["items_pdf"])),
        ("  from abstract only", str(status["items_abstract"])),
        ("Passages", str(status["chunks"])),
        ("Scans waiting for OCR", str(status["items_ocr_pending"])),
        ("PDFs that failed", str(status["items_with_error"])),
        ("Items with several PDFs (newest indexed)", str(status["items_multi_pdf"])),
        ("Mirror items", str(mirror["items"])),
        ("  with a PDF on disk", str(mirror["with_pdf"])),
        ("  PDF held by the manager only", str(mirror["pdf_not_in_mirror"])),
        ("Items a new ingest would touch", str(mirror["stale"])),
    ]
    for name, value in rows:
        table.add_row(name, value)
    console.print(table)
    if status["problem"]:
        console.print(status["problem"], markup=False, style="yellow")
    if mirror["pdf_not_in_mirror"]:
        console.print(
            f"[dim]{mirror['pdf_not_in_mirror']} items have a PDF in the reference "
            "manager that is not in the mirror. `paperful snapshot --pdfs all` "
            "copies them in.[/]"
        )
    if mirror["stale"]:
        console.print(
            "[dim]`paperful rag ingest --library` brings the index up to date.[/]"
        )

@rag_app.command("search")
def rag_search(
    query: str = typer.Argument(..., help="What to look for."),
    top_k: int | None = typer.Option(None, "-k", "--top-k", help="Passages to show."),
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    json_out: bool = typer.Option(False, "--json", help="Print JSON."),
    config: Path | None = ConfigOpt,
) -> None:
    """Show the indexed passages closest to a query. No chat model is used."""
    from dataclasses import asdict

    from .llm import LLMClientError
    from .rag.retrieve import scope_keys, search

    cfg = _cfg(config)
    _rag_require(cfg)
    types = _resolve_types(item_type)
    embedder = _rag_embedder(cfg)
    index, ledger = _rag_open(cfg)
    keys = scope_keys(
        ledger,
        collections=collection,
        item_keys=item,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
    )
    try:
        hits = search(
            cfg, query, k=top_k, keys=keys, embedder=embedder, index=index, ledger=ledger
        )
    except LLMClientError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    if json_out:
        console.print(
            json.dumps([asdict(h) for h in hits], indent=2, ensure_ascii=False),
            soft_wrap=True,
            highlight=False,
            markup=False,
        )
        return
    if not hits:
        console.print("[yellow]No passages match.[/]")
        return
    _print_hits(hits)

@rag_app.command("questions")
def rag_questions(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    library: bool = typer.Option(False, "--library", help="Every indexed item."),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    llm: bool | None = typer.Option(
        None,
        "--llm/--no-llm",
        help="Also run the grounded LLM extract lane. Default is [rag].extract_questions_llm.",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Max items this run."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print counts; do not write state/rag/questions/."
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Extract research questions from indexed papers (rules; optional LLM)."""
    from dataclasses import asdict

    from .agent_json import batch_exit, envelope
    from .llm import get_client
    from .llm.preflight import validate_llm_for_ask
    from .llm.validate import LlmConfigError
    from .rag.questions import extract_scope, write_item

    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    _rag_require(cfg)
    if not (item or collection or library):
        console.print("[red]Pass --item, -C, or --library.[/]")
        raise typer.Exit(1)
    use_llm = cfg.rag_extract_questions_llm if llm is None else llm
    client = None
    if use_llm:
        try:
            validate_llm_for_ask(cfg)
        except LlmConfigError as exc:
            console.print(str(exc), markup=False, style="red")
            raise typer.Exit(1) from exc
        client = get_client(cfg)
    types = _resolve_types(item_type)
    _, ledger = _rag_open(cfg)
    started = time.time()
    items = extract_scope(
        cfg,
        ledger=ledger,
        collections=None if library and not collection else collection,
        item_keys=item,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
        use_llm=use_llm,
        client=client,
        limit=limit,
    )
    total_q = sum(len(it.questions) for it in items)
    if not dry_run:
        for it in items:
            write_item(cfg, it)
    if not json_out:
        action = "Would extract" if dry_run else "Extracted"
        console.print(
            f"{action} {total_q} question(s) from {len(items)} item(s)"
            + (" (LLM on)" if use_llm else "")
            + "."
        )
        for it in items:
            if not it.questions:
                continue
            console.print(f"[bold]{it.item_key}[/] {it.title}", markup=False)
            for q in it.questions:
                console.print(
                    f"  [{q.provenance}] {q.text}", markup=False, highlight=False
                )
    write_command_report(
        cfg,
        command="rag-questions",
        scope=", ".join(collection) or ("library" if library else "items"),
        summary={
            "items": len(items),
            "questions": total_q,
            "dry_run": dry_run,
            "llm": use_llm,
        },
        items=[asdict(it) for it in items],
        flags={"limit": limit, "llm": use_llm},
        started=started,
    )
    code = batch_exit(ok=len(items), failed=0)
    if json_out:
        payload = envelope(
            command="rag-questions",
            summary={"items": len(items), "questions": total_q, "dry_run": dry_run},
            items=[asdict(it) for it in items],
            flags={"read_only": dry_run, "llm": use_llm},
            exit_code=code,
        )
        _emit_agent(payload, json_out=True, human=lambda: None)

@rag_app.command("answered")
def rag_answered(
    from_file: Path | None = typer.Option(
        None, "--from-file", help="Questions file (one per line) or '-'."
    ),
    from_extract: bool = typer.Option(
        False,
        "--from-extract",
        help="Use questions under state/rag/questions/.",
    ),
    after_item: str | None = typer.Option(
        None,
        "--after-item",
        help="Only search items newer than this paper's year; exclude the asker.",
    ),
    item: list[str] = typer.Option(
        [],
        "--item",
        help="With --from-extract: only these asking items. Else: scope keys.",
    ),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    top_k: int | None = typer.Option(None, "-k", "--top-k", help="Passages per question."),
    force: bool = typer.Option(False, "--force", help="Ignore batch answer cache."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Ask whether the corpus already answers research questions."""
    from dataclasses import asdict

    from .agent_json import batch_exit, envelope
    from .llm import get_client, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_ask
    from .llm.validate import LlmConfigError
    from .rag.answered import (
        file_questions,
        questions_from_extract,
        run_answered,
        write_pack,
    )
    from .rag.retrieve import scope_keys
    from .snowball.command import SnowballError

    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    bound = _bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=None,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    if bound.collections:
        collection = list(bound.collections)
    if bound.year_from is not None:
        year_from = bound.year_from
    if bound.year_to is not None:
        year_to = bound.year_to
    if bound.types:
        item_type = list(bound.types)
    _rag_require(cfg)
    if not from_file and not from_extract:
        console.print("[red]Pass --from-file or --from-extract.[/]")
        raise typer.Exit(1)
    try:
        validate_llm_for_ask(cfg)
    except LlmConfigError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    if llm_egress_is_remote(cfg) and not json_out:
        console.print(
            "[yellow]Remote LLM — excerpts from your PDFs leave this machine.[/]"
        )
    types = _resolve_types(item_type)
    embedder = _rag_embedder(cfg)
    index, ledger = _rag_open(cfg)
    keys = scope_keys(
        ledger,
        collections=collection,
        item_keys=[] if from_extract else item,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
    )
    questions: list[tuple[str, str, int | None]] = []
    if from_file is not None:
        try:
            questions.extend(file_questions(str(from_file)))
        except SnowballError as exc:
            console.print(str(exc), markup=False, style="red")
            raise typer.Exit(1) from exc
    if from_extract:
        extract_keys = list(item) if item else None
        questions.extend(questions_from_extract(cfg, item_keys=extract_keys))
    if not questions:
        console.print("[red]No questions to check.[/]")
        raise typer.Exit(1)
    started = time.time()
    client = get_client(cfg)
    pack = run_answered(
        cfg,
        questions,
        keys=keys,
        after_item=after_item,
        k=top_k,
        force=force,
        scope={
            "collections": list(collection),
            "year_from": year_from,
            "year_to": year_to,
            "after_item": after_item,
        },
        client=client,
        embedder=embedder,
        index=index,
        ledger=ledger,
    )
    folder = write_pack(cfg, pack)
    if not json_out:
        console.print(
            f"Answered {pack.answered} · partial {pack.partial} · "
            f"not_found {pack.not_found} · failed {pack.failed} → {folder}"
        )
    write_command_report(
        cfg,
        command="rag-answered",
        scope=", ".join(collection) or "index",
        summary={
            "questions": pack.questions,
            "answered": pack.answered,
            "partial": pack.partial,
            "not_found": pack.not_found,
            "failed": pack.failed,
            "pack": str(folder),
        },
        items=[asdict(r) for r in pack.rows],
        flags={"focus": "answered", "after_item": after_item},
        started=started,
    )
    code = batch_exit(
        ok=pack.answered + pack.partial + pack.not_found, failed=pack.failed
    )
    if json_out:
        payload = envelope(
            command="rag-answered",
            summary={
                "questions": pack.questions,
                "answered": pack.answered,
                "partial": pack.partial,
                "not_found": pack.not_found,
                "pack": str(folder),
            },
            items=[asdict(r) for r in pack.rows],
            flags={"read_only": True, "after_item": after_item},
            exit_code=code,
        )
        _emit_agent(payload, json_out=True, human=lambda: None)
        return
    if pack.failed:
        raise typer.Exit(1)

@app.command()
def ask(
    question: str | None = typer.Argument(
        None, help="The question. Leave out to be prompted for several."
    ),
    top_k: int | None = typer.Option(
        None, "-k", "--top-k", help="Passages sent to the model."
    ),
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Batch: one question per line (file or '-'). Writes state/ask-batch/.",
    ),
    focus: str | None = typer.Option(
        None,
        "--focus",
        help="Prompt preset: default, questions, gaps, methods, answered.",
    ),
    prompt: Path | None = typer.Option(
        None, "--prompt", help="Override system prompt file for this run."
    ),
    force: bool = typer.Option(
        False, "--force", help="Batch: re-answer even when a cached row matches."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Batch: write a Zotero collection note when --to includes zotero.",
    ),
    to: WriteDest | None = typer.Option(
        None,
        "--to",
        help="Batch note destination: disk, zotero, or both. Default is [rag].dest.",
    ),
    no_stream: bool = typer.Option(
        False, "--no-stream", help="Print the answer when it is complete."
    ),
    show_context: bool = typer.Option(
        False, "--show-context", help="List the passages the answer is built from."
    ),
    thread: str | None = typer.Option(
        None,
        "--thread",
        help="Follow-up thread under state/rag/threads/. 'new' starts one; omit for a one-shot.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Answer a question from the indexed library, with sources. Needs `rag ingest` first."""
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    from .ask_cmd import run_ask

    run_ask(
        console,
        cfg,
        question=question,
        top_k=top_k,
        item=item,
        collection=collection,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        from_file=from_file,
        focus=focus,
        prompt=prompt,
        force=force,
        apply=apply,
        to_dest=_typer_enum_value(to),
        no_stream=no_stream,
        show_context=show_context,
        thread=thread,
        profile=profile,
        run_config=run_config,
        json_out=json_out,
    )

@app.command()
def summarize(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection scope (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    apply: bool | None = typer.Option(
        None,
        "--apply/--no-apply",
        help="Require a Zotero child note (conflicts with --to disk). Default dest already includes Zotero.",
    ),
    to: WriteDest | None = typer.Option(
        None,
        "--to",
        help="Where to write: disk, zotero, or both. Default is config, or both.",
    ),
    prompt: Path | None = typer.Option(
        None, "--prompt", help="Override summary prompt file for this run."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Regenerate even when a summary already exists, and summarize when "
            "the gated PDF identity check flags the item."
        ),
    ),
    order: SummarizeOrder | None = typer.Option(
        None,
        "--order",
        help=(
            "Queue order before --limit: newest, oldest, or library (manager "
            "order). Default is summarize.order in config, or library."
        ),
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    max_new: int | None = typer.Option(
        None,
        "--max-new",
        min=1,
        help="Stop after this many new model summaries (skips do not count).",
    ),
    max_minutes: float | None = typer.Option(
        None,
        "--max-minutes",
        min=0,
        help="Stop after this many minutes (finishes the paper in hand).",
    ),
    collections_file: Path | None = typer.Option(
        None,
        "--collections-file",
        exists=True,
        dir_okay=False,
        help="Text file: one collection path per line (appended to --collection).",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Grounded LLM summary from local PDF text. Default writes disk and a Zotero note."""
    from .completeness_cmd import run_summarize

    run_summarize(
        console,
        item=item,
        collection=collection,
        library=library,
        apply=apply,
        to_dest=_typer_enum_value(to),
        prompt=prompt,
        force=force,
        order_value=_typer_enum_value(order),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        max_new=_typer_opt(max_new),
        max_minutes=_typer_opt(max_minutes),
        collections_file=collections_file,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("extract-sections")
def extract_sections(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    library: bool = typer.Option(False, "--library", help="Every item in the mirror."),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    llm: bool | None = typer.Option(
        None,
        "--llm/--no-llm",
        help="Fill missing MVP fields with a grounded LLM pass. Default is [extract_sections].llm.",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Max items this run."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print counts; do not write state/sections/.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-extract even when state/sections/<key>.json already exists.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Extract IMRaD-style sections to disk (rules; optional LLM)."""
    from .agent_json import batch_exit, envelope
    from .llm import get_client
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError
    from .sections.command import extract_scope, item_to_dict, write_item

    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    if not (item or collection or library):
        console.print("[red]Pass --item, -C, or --library.[/]")
        raise typer.Exit(1)
    use_llm = cfg.extract_sections_llm if llm is None else llm
    client = None
    if use_llm:
        try:
            validate_llm_for_verb(cfg)
        except LlmConfigError as exc:
            console.print(str(exc), markup=False, style="red")
            raise typer.Exit(1) from exc
        client = get_client(cfg)
    types = _resolve_types(item_type)
    started = time.time()
    items = extract_scope(
        cfg,
        collections=collection or None,
        item_keys=item,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
        use_llm=use_llm,
        client=client,
        limit=limit,
        force=force,
        skip_existing=not force,
    )
    filled = sum(
        1
        for it in items
        for name in cfg.extract_sections_fields
        if it.fields.get(name) is not None
    )
    if not dry_run:
        for it in items:
            write_item(cfg, it)
    scope = ", ".join(collection) or ("library" if library else "items")
    if not json_out:
        action = "Would extract" if dry_run else "Extracted"
        console.print(
            f"{action} sections for {len(items)} item(s)"
            + (f" ({filled} field(s) present)" if items else "")
            + (" (LLM on)" if use_llm else "")
            + "."
        )
    write_command_report(
        cfg,
        command="extract-sections",
        scope=scope,
        summary={
            "items": len(items),
            "fields_present": filled,
            "dry_run": dry_run,
            "llm": use_llm,
        },
        items=[item_to_dict(it) for it in items],
        flags={"limit": limit, "llm": use_llm, "force": force},
        started=started,
    )
    code = batch_exit(ok=len(items), failed=0)
    if json_out:
        payload = envelope(
            command="extract-sections",
            summary={
                "items": len(items),
                "fields_present": filled,
                "dry_run": dry_run,
            },
            items=[item_to_dict(it) for it in items],
            flags={"read_only": dry_run, "llm": use_llm, "force": force},
            exit_code=code,
        )
        _emit_agent(payload, json_out=True, human=lambda: None)


@app.command()
def synthesize(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection scope (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    to: WriteDest | None = typer.Option(
        None,
        "--to",
        help="Where to write the report: disk, zotero, or both. Default is config, or both.",
    ),
    report_collection: str | None = typer.Option(
        None,
        "--report-collection",
        help="Collection that receives the Zotero report note. Defaults to each -C root.",
    ),
    prompt: Path | None = typer.Option(
        None, "--prompt", help="Override the report prompt file for this run."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show source counts and the chunk plan. No model call."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate even when the saved report used the same summary notes.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Literature review from summary notes already saved by summarize."""
    from .completeness_cmd import run_synthesize

    run_synthesize(
        console,
        item=item,
        collection=collection,
        library=library,
        to_dest=_typer_enum_value(to),
        report_collection=report_collection,
        prompt=prompt,
        dry_run=dry_run,
        force=force,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )

@app.command("all")
def all_cmd(
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Collection path/name/key (repeatable). Subcollections included.",
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Stop after N items in each step."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="gaps, run --dry-run, lint, and fix-metadata without --apply. Skips summarize.",
    ),
    try_all: bool | None = TryAllOpt,
    retry_failed: bool | None = RetryFailedOpt,
    upgrade_linked: bool | None = UpgradeLinkedOpt,
    no_attach: bool | None = NoAttachOpt,
    strict_pdf_doi: bool | None = StrictPdfDoiOpt,
    scihub: bool | None = SciHubOpt,
    browser_agent: bool | None = BrowserAgentOpt,
    camofox: bool | None = CamofoxOpt,
    sources: str | None = typer.Option(
        None,
        "--sources",
        help="Comma-separated source order override for the run step.",
    ),
    preset: str | None = typer.Option(
        None, "--preset", help="Named source preset for the run step (eoi)."
    ),
    apply: bool | None = ApplyOpt,
    overwrite: bool | None = OverwriteOpt,
    steps: str | None = StepsOpt,
    skip: list[str] = SkipOpt,
    require_summarize: bool | None = typer.Option(
        None,
        "--require-summarize/--no-require-summarize",
        help="Exit 1 instead of skipping summarize when llm.enabled is false.",
    ),
    serpapi_max: int | None = typer.Option(
        None,
        "--serpapi-max",
        help="Cap paid SerpApi Scholar searches on the run step (0 = unlimited).",
    ),
    label: str | None = typer.Option(
        None, "--label", help="Pack label when this command opens a pack."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Run gaps, then fetch, lint, fix-metadata --apply, and summarize --apply.

    Stops on the first failing step, same as chaining the commands with ``&&``.
    """
    from .all_cmd import run_all

    run_all(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        dry_run=dry_run,
        try_all=try_all,
        retry_failed=retry_failed,
        upgrade_linked=upgrade_linked,
        no_attach=no_attach,
        strict_pdf_doi=strict_pdf_doi,
        scihub=scihub,
        browser_agent=browser_agent,
        camofox=camofox,
        sources=sources,
        preset=preset,
        apply=apply,
        overwrite=overwrite,
        steps=steps,
        skip=skip,
        require_summarize=require_summarize,
        serpapi_max=serpapi_max,
        label=label,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )

def _dispatch_all_step(*args, **kwargs):
    from .all_cmd import _dispatch_all_step as _impl
    return _impl(*args, **kwargs)

def _profile_bind_kwargs(
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    try_all: bool | None,
    retry_failed: bool | None,
    upgrade_linked: bool | None,
    no_attach: bool | None,
    strict_pdf_doi: bool | None,
    scihub: bool | None,
    sources: str | None,
    preset: str | None,
    apply: bool | None,
    overwrite: bool | None,
    steps: str | None,
    skip: list[str],
    require_summarize: bool | None,
    profile: str | None,
    run_config: Path | None,
) -> dict[str, Any]:
    return {
        "profile": profile,
        "run_config": run_config,
        "collection": collection,
        "library": library,
        "year_from": year_from,
        "year_to": year_to,
        "item_type": item_type,
        "limit": limit,
        "try_all": try_all,
        "retry_failed": retry_failed,
        "upgrade_linked": upgrade_linked,
        "no_attach": no_attach,
        "strict_pdf_doi": strict_pdf_doi,
        "scihub": scihub,
        "sources": sources,
        "preset": preset,
        "apply": apply,
        "overwrite": overwrite,
        "steps": steps,
        "skip": skip,
        "require_summarize": require_summarize,
    }

@playbooks_app.command("probe")
def playbooks_probe(
    corpus: Path = typer.Option(
        ...,
        "--corpus",
        help="TOML file of [[targets]] (playbook, url or extra, note).",
        exists=True,
        dir_okay=False,
    ),
    config: Path | None = ConfigOpt,
    examples: bool = typer.Option(
        True,
        "--examples/--no-examples",
        help="Merge paperful/data/grey_playbooks_examples/ under the config playbooks.",
    ),
    check: int = typer.Option(
        3, "--check", help="How many extracted links to download per landing."
    ),
    min_bytes: int = typer.Option(
        10_000, "--min-bytes", help="Smallest body that counts as a PDF."
    ),
    delay: float = typer.Option(
        0.4, "--delay", help="Seconds to wait between targets."
    ),
    save: Path | None = typer.Option(
        None,
        "--save",
        help="Write one JSON per target plus index.json. Pass rows include the links needed to replay offline.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the rows as JSON."),
) -> None:
    """Fetch each corpus landing and require the first candidate to be a PDF.

    Exit 0 when every target passes. A pass is a %PDF body of at least
    --min-bytes. It does not prove the file is the record a listing page
    describes. This command talks to the network.
    """
    import httpx

    from .grey_probe import load_corpus, playbooks_for_probe, probe_corpus, save_recorded

    if check < 1:
        console.print("[red]--check must be >= 1[/]")
        raise typer.Exit(2)
    if min_bytes < 1:
        console.print("[red]--min-bytes must be >= 1[/]")
        raise typer.Exit(2)
    try:
        targets = load_corpus(corpus)
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    cfg = _cfg(config)
    books = playbooks_for_probe(cfg.grey_playbooks, examples=examples)
    timeout = httpx.Timeout(20.0, connect=15.0)
    with httpx.Client(
        headers={"User-Agent": cfg.user_agent, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        rows = probe_corpus(
            targets,
            books,
            client,
            check=check,
            min_bytes=min_bytes,
            delay_s=max(0.0, delay),
        )
    if save is not None:
        path = save_recorded(save, rows)
        console.print(f"Wrote {path}")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    if as_json:
        console.print(
            json.dumps(
                {
                    "counts": counts,
                    "rows": [row.to_dict() for row in rows],
                },
                indent=2,
            )
        )
    else:
        table = Table(title="Grey playbook probe")
        table.add_column("Status")
        table.add_column("Playbook")
        table.add_column("Landing")
        table.add_column("Chosen")
        table.add_column("Detail")
        for row in rows:
            table.add_row(
                row.status,
                row.playbook,
                row.url or row.extra,
                row.chosen,
                row.detail,
            )
        console.print(table)
        summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        console.print(summary)
    if any(row.status != "pass" for row in rows):
        raise typer.Exit(1)

@playbooks_app.command("propose")
def playbooks_propose(
    config: Path | None = ConfigOpt,
    to: Path | None = typer.Option(
        None,
        "--to",
        help="Write the draft TOML here (default: state/playbooks-proposed.toml).",
    ),
    min_hits: int = typer.Option(
        1, "--min-hits", help="Cluster size required in the draft (default 1)."
    ),
) -> None:
    """Draft learned playbooks from state/fetch-wins.jsonl. Does not install them."""
    from .fetch_wins import load_wins, proposed_path, propose_toml, wins_path

    cfg = _cfg(config)
    if min_hits < 1:
        console.print("[red]--min-hits must be >= 1[/]")
        raise typer.Exit(2)
    rows = load_wins(wins_path(cfg))
    text = propose_toml(rows, min_hits=min_hits)
    dest = to if to is not None else proposed_path(cfg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    if text.strip():
        console.print(text)
    else:
        console.print("[dim]No promotable wins yet.[/]")
    console.print(f"Wrote {dest}")

@playbooks_app.command("promote")
def playbooks_promote(
    config: Path | None = ConfigOpt,
    source: Path | None = typer.Option(
        None,
        "--from",
        help="Proposed TOML (default: state/playbooks-proposed.toml).",
    ),
) -> None:
    """Install proposed learned playbooks into grey_playbooks_dir/learned.toml."""
    from .fetch_wins import proposed_path, write_learned
    from .playbooks import load_pack_file

    cfg = _cfg(config)
    if cfg.grey_playbooks_dir is None:
        console.print(
            "[red]grey_playbooks_dir is unset.[/] "
            'Set grey_playbooks_dir = "packs" in config.toml.'
        )
        raise typer.Exit(2)
    path = source if source is not None else proposed_path(cfg)
    if not path.is_file():
        console.print(
            f"[red]No proposal file at {path}.[/] Run playbooks propose first."
        )
        raise typer.Exit(2)
    books = [pb for pb in load_pack_file(path) if pb.name.startswith("learned-")]
    if not books:
        console.print("[yellow]Proposal has no learned- playbooks.[/]")
        raise typer.Exit(1)
    changed = write_learned(cfg.grey_playbooks_dir, books)
    dest = cfg.grey_playbooks_dir / "learned.toml"
    if changed:
        console.print(f"[green]Promoted[/] {len(books)} playbook(s) to {dest}")
    else:
        console.print(f"[dim]Unchanged[/] {dest}")

@profile_app.command("list")
def profile_list(config: Path | None = ConfigOpt) -> None:
    """List saved run configs. The builtin ``all`` policy is not a named profile."""
    cfg = _cfg(config)
    rows: list[ProfileListing] = list_profiles(cfg)
    if not rows:
        console.print("No saved profiles.")
        console.print(
            "[dim]Builtin all: gaps → run → lint → fix-metadata → summarize. "
            "Save one with[/] [bold]paperful profile save NAME -C …[/]"
        )
        return
    table = Table(title="Run profiles")
    table.add_column("Name")
    table.add_column("Source")
    table.add_column("Description")
    for row in rows:
        table.add_row(row.name, row.source, row.description)
    console.print(table)
    console.print(
        "[dim]paperful profile show NAME[/] prints the merge [bold]paperful all[/] would use."
    )

@profile_app.command("show")
def profile_show(
    name: str | None = typer.Argument(
        None, help="Profile name. Omit to show builtin all defaults."
    ),
    collection: list[str] = typer.Option([], "--collection", "-C"),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Note that summarize would be skipped."
    ),
    try_all: bool | None = TryAllOpt,
    retry_failed: bool | None = RetryFailedOpt,
    upgrade_linked: bool | None = UpgradeLinkedOpt,
    no_attach: bool | None = NoAttachOpt,
    strict_pdf_doi: bool | None = StrictPdfDoiOpt,
    scihub: bool | None = SciHubOpt,
    sources: str | None = typer.Option(None, "--sources"),
    preset: str | None = typer.Option(None, "--preset"),
    apply: bool | None = ApplyOpt,
    overwrite: bool | None = OverwriteOpt,
    steps: str | None = StepsOpt,
    skip: list[str] = SkipOpt,
    require_summarize: bool | None = typer.Option(
        None, "--require-summarize/--no-require-summarize"
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Print the effective ``paperful all`` config after profile and flag merge."""
    chosen = name or profile
    if name and profile and name != profile:
        console.print(
            "[red]Pass the profile name once, as an argument or --profile.[/]"
        )
        raise typer.Exit(1)
    cfg = _cfg(config)
    bound = _bind_run(
        cfg,
        for_all=True,
        **_profile_bind_kwargs(
            collection=collection,
            library=library,
            year_from=year_from,
            year_to=year_to,
            item_type=item_type,
            limit=limit,
            try_all=try_all,
            retry_failed=retry_failed,
            upgrade_linked=upgrade_linked,
            no_attach=no_attach,
            strict_pdf_doi=strict_pdf_doi,
            scihub=scihub,
            sources=sources,
            preset=preset,
            apply=apply,
            overwrite=overwrite,
            steps=steps,
            skip=skip,
            require_summarize=require_summarize,
            profile=chosen,
            run_config=run_config,
        ),
    )
    where = ", ".join(bound.origins) or "builtin all"
    console.print(f"[dim]Effective paperful all configuration ({where})[/]")
    console.print(format_effective(bound), markup=False, highlight=False)
    if dry_run and "summarize" in bound.steps:
        console.print("[yellow]dry-run skips summarize.[/]")

@profile_app.command("save")
def profile_save(
    name: str = typer.Argument(
        ..., help="Profile name. Written to profiles/<name>.toml."
    ),
    collection: list[str] = typer.Option([], "--collection", "-C"),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    try_all: bool | None = TryAllOpt,
    retry_failed: bool | None = RetryFailedOpt,
    upgrade_linked: bool | None = UpgradeLinkedOpt,
    no_attach: bool | None = NoAttachOpt,
    strict_pdf_doi: bool | None = StrictPdfDoiOpt,
    scihub: bool | None = SciHubOpt,
    sources: str | None = typer.Option(None, "--sources"),
    preset: str | None = typer.Option(None, "--preset"),
    apply: bool | None = ApplyOpt,
    overwrite: bool | None = OverwriteOpt,
    steps: str | None = StepsOpt,
    skip: list[str] = SkipOpt,
    require_summarize: bool | None = typer.Option(
        None, "--require-summarize/--no-require-summarize"
    ),
    description: str | None = typer.Option(
        None, "--description", help="One-line note stored in the file."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing profile file."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Write profiles/<name>.toml beside config.toml. Does not edit config.toml."""
    cfg = _cfg(config)
    try:
        body = collect_save_body(
            cfg,
            description=description,
            **_profile_bind_kwargs(
                collection=collection,
                library=library,
                year_from=year_from,
                year_to=year_to,
                item_type=item_type,
                limit=limit,
                try_all=try_all,
                retry_failed=retry_failed,
                upgrade_linked=upgrade_linked,
                no_attach=no_attach,
                strict_pdf_doi=strict_pdf_doi,
                scihub=scihub,
                sources=sources,
                preset=preset,
                apply=apply,
                overwrite=overwrite,
                steps=steps,
                skip=skip,
                require_summarize=require_summarize,
                profile=profile,
                run_config=run_config,
            ),
        )
        path = save_profile(cfg, name, body, force=force)
    except RunConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"Wrote [bold]{path}[/]")

def _snowball_request(
    cfg: Config,
    *,
    gate: str | None,
    collection: str | None,
    fetch_pdfs: str | bool | None,
    depth: int | None,
    max_candidates: str | int | None,
    per_hop_limit: str | int | None = None,
    per_hop_rank: str | None = None,
    year_from: int | None,
    year_to: int | None,
    direction: str | None = None,
    keyword_limit: str | int | None = None,
    keyword_hop_limit: str | int | None = None,
    keyword_min_score: float | None = None,
    cites_query: str | None = None,
    languages: str | None = None,
    study_designs: list[str] | str | None = None,
    min_seed_citations: int | None = None,
    note_provenance: bool | None = None,
    backends: str | None = None,
    hybrid_seeds: int | None = None,
    refine: bool | None = None,
    tags: list[str] | None = None,
    dedupe_scope: str | None = None,
    dedupe_after: str | None = None,
    author_site_preflight: bool | None = None,
    twenty_writeback: bool | None = None,
    stop_rule: str | None = None,
    stop_eps: float | None = None,
    stop_k: int | None = None,
    stop_max_screened: int | None = None,
) -> Any:
    from .snowball.command import SnowballRequest
    from .snowball.expand import parse_study_designs

    if twenty_writeback is not None:
        cfg.twenty_writeback_listings = twenty_writeback
    designs = None
    if study_designs:
        try:
            designs = parse_study_designs(study_designs)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(2) from exc
    return SnowballRequest(
        gate=gate or cfg.snowball_gate,
        collection=(collection or cfg.snowball_target_collection or ""),
        fetch_pdfs=cfg.snowball_fetch_pdfs if fetch_pdfs is None else fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction or cfg.snowball_direction or "refs",
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=(cites_query or "").strip(),
        languages=_csv(languages) if languages else None,
        study_designs=designs,
        min_seed_citations=min_seed_citations,
        note_provenance=note_provenance,
        backends=_csv(backends) if backends else None,
        hybrid_seeds=hybrid_seeds,
        refine=refine,
        link_versions=True,
        tags=tuple(str(t).strip() for t in (tags or []) if str(t).strip()),
        dedupe_scope=(dedupe_scope or "").strip() or None,
        dedupe_after=(dedupe_after or "").strip() or None,
        author_site_preflight=author_site_preflight,
        stop_rule=(stop_rule or "").strip() or None,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )

def _csv(raw: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (raw or "").split(",") if part.strip())

def _compose_keywords(queries: list[str], *, or_mode: bool) -> str:
    from .snowball.expand import compose_keyword_query

    notices: list[str] = []
    query = compose_keyword_query(queries, op="or" if or_mode else "and", notices=notices)
    for note in notices:
        console.print(f"[yellow]{note}[/]")
    return query

def _doi_seeds(dois: list[str] | None, seeds_file: str | Path | None) -> list[str]:
    from .snowball.seeds import dois_from_seeds, merge_tokens, parse_seed_lines, read_seeds_text

    extra: list[str] = []
    if seeds_file is not None:
        extra = parse_seed_lines(read_seeds_text(str(seeds_file)))
    merged = merge_tokens(list(dois or []), extra)
    if not merged:
        from .snowball.command import SnowballError

        raise SnowballError("Pass one or more DOIs or --seeds-file.")
    return dois_from_seeds(merged)

def _orcid_seeds(orcids: list[str] | None, seeds_file: str | Path | None) -> list[str]:
    from .snowball.seeds import merge_tokens, orcids_from_seeds, parse_seed_lines, read_seeds_text

    extra: list[str] = []
    if seeds_file is not None:
        extra = parse_seed_lines(read_seeds_text(str(seeds_file)))
    merged = merge_tokens(list(orcids or []), extra)
    if not merged:
        from .snowball.command import SnowballError

        raise SnowballError("Pass one or more ORCID iDs or --seeds-file.")
    return orcids_from_seeds(merged)

def _profile_queries(body: dict[str, Any], queries: list[str], *, or_mode: bool) -> None:
    """Persist one ``query`` or a ``queries`` array (+ optional ``query_op``)."""
    if len(queries) == 1:
        body["query"] = queries[0]
    else:
        body["queries"] = list(queries)
    if or_mode:
        body["query_op"] = "or"

def _snowball_console(*, json_out: bool) -> Console:
    if json_out:
        # Live E2E babysits long snowball phases; keep progress on stderr.
        quiet = os.environ.get("PAPERFUL_E2E") != "1"
        return Console(file=sys.stderr, highlight=False, quiet=quiet)
    return console

def _run_snowball(
    cfg: Config,
    action: Any,
    *,
    json_out: bool = False,
    command: str = "snowball",
) -> None:
    from .snowball.command import SnowballError
    from .agent_ops import snowball_result_envelope

    snowball_started = time.time()
    try:
        result = action(cfg)
    except SnowballError as exc:
        if json_out:
            Console(stderr=True, highlight=False).print(f"[red]{exc}[/]")
        else:
            console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _rag_auto(cfg, snowball_started)
    # Writing gates join the run-report / witness trail (dry-run crawls stay queue-only).
    if command in {"snowball apply"}:
        summary = dict(getattr(result, "summary", None) or {})
        summary.setdefault("write_api", None)
        run_dir = getattr(result, "run_dir", None)
        write_command_report(
            cfg,
            command=command,
            scope=str(run_dir or ""),
            summary=summary,
            items=[],
            flags={"run_dir": str(run_dir or "")},
            started=snowball_started,
            extra_paths={"run": str(run_dir)} if run_dir else None,
        )
    if json_out:
        payload = snowball_result_envelope(command, result)
        _emit_agent(payload, json_out=True, human=lambda: None)
        return
    if result.exit_code:
        raise typer.Exit(result.exit_code)

@snowball_app.command("search")
def snowball_search(
    queries: list[str] = typer.Argument(..., help="One or more keyword terms."),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    depth: int | None = typer.Option(
        None, "--depth", help="0 = hits only. Expand hits when >= 1."
    ),
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    direction: str | None = typer.Option(
        None, "--direction", help=DIRECTION_HELP + " Used when depth >= 1."
    ),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    or_mode: bool = typer.Option(
        False, "--or", help="Match any keyword (default: all)."
    ),
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="dry-run, approve-each, approve-batch, or auto. Default: config, else dry-run.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Target collection for --gate auto."
    ),
    fetch_pdfs: str | None = FetchPdfsOpt,
    languages: str | None = typer.Option(
        None, "--languages", help="Comma-separated language codes."
    ),
    min_seed_citations: int | None = typer.Option(None, "--min-seed-citations"),
    note_provenance: bool | None = typer.Option(
        None, "--note-provenance/--no-note-provenance"
    ),
    backends: str | None = typer.Option(
        None, "--backends", help="Comma-separated backend names."
    ),
    refine: bool | None = typer.Option(
        None, "--refine/--no-refine", help="Ask the LLM for query suggestions."
    ),
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Search OpenAlex and write a candidate queue. Creates items only with --gate auto."""
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=(cites_query or "").strip(),
        languages=languages,
        study_designs=study_design,
        min_seed_citations=min_seed_citations,
        note_provenance=note_provenance,
        backends=backends,
        refine=refine,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )
    from .snowball.command import run_search

    try:
        query = _compose_keywords(queries, or_mode=or_mode)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    _run_snowball(
        cfg,
        lambda c: run_search(c, query, request, console=out),
        json_out=json_out,
        command="snowball search",
    )

@snowball_app.command("hybrid")
def snowball_hybrid(
    queries: list[str] = typer.Argument(
        ..., help="One or more keyword terms. Top hits then get one hop."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    hybrid_seeds: int | None = typer.Option(
        None, "--hybrid-seeds", help="How many top DOI hits to expand."
    ),
    direction: str | None = typer.Option(None, "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    or_mode: bool = typer.Option(
        False, "--or", help="Match any keyword (default: all)."
    ),
    gate: str | None = typer.Option(
        None, "--gate", help="dry-run, approve-each, approve-batch, or auto."
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Target collection for a writing gate."
    ),
    fetch_pdfs: str | None = FetchPdfsOpt,
    languages: str | None = typer.Option(None, "--languages"),
    min_seed_citations: int | None = typer.Option(None, "--min-seed-citations"),
    refine: bool | None = typer.Option(None, "--refine/--no-refine"),
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Keyword hits, then one hop from the top DOIs. Not a separate harvest command."""
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=None,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=(cites_query or "").strip(),
        languages=languages,
        study_designs=study_design,
        min_seed_citations=min_seed_citations,
        hybrid_seeds=hybrid_seeds,
        refine=refine,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )
    from .snowball.command import run_hybrid

    try:
        query = _compose_keywords(queries, or_mode=or_mode)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    _run_snowball(
        cfg,
        lambda c: run_hybrid(c, query, request, console=out),
        json_out=json_out,
        command="snowball hybrid",
    )

@snowball_app.command("doi")
def snowball_doi(
    dois: list[str] | None = typer.Argument(
        None, help="One or more seed DOIs. Optional when --seeds-file is set."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    depth: int | None = typer.Option(
        None, "--depth", help="Graph hops. Default: [snowball] depth, else 1."
    ),
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    direction: str | None = typer.Option(None, "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="dry-run, approve-each, approve-batch, or auto. Default: config, else dry-run.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Target collection for --gate auto."
    ),
    fetch_pdfs: str | None = FetchPdfsOpt,
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    seeds_file: str | None = SeedsFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Bibliography and/or citing works of each DOI. Creates items only with --gate auto."""
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=(cites_query or "").strip(),
        study_designs=study_design,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )
    from .snowball.command import SnowballError, run_doi

    try:
        seeds = _doi_seeds(dois, seeds_file)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _run_snowball(
        cfg,
        lambda c: run_doi(c, seeds, request, console=out),
        json_out=json_out,
        command="snowball doi",
    )

@snowball_app.command("orcid")
def snowball_orcid(
    orcids: list[str] | None = typer.Argument(
        None, help="One or more ORCID iDs. Optional when --seeds-file is set."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    depth: int | None = typer.Option(
        None, "--depth", help="Graph hops. Default: [snowball] depth, else 1."
    ),
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    direction: str | None = typer.Option(None, "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="dry-run, approve-each, approve-batch, or auto. Default: config, else dry-run.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Target collection for --gate auto."
    ),
    fetch_pdfs: str | None = FetchPdfsOpt,
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    seeds_file: str | None = SeedsFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """People's works (ORCID + OpenAlex), then references/citations those works expand to."""
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=(cites_query or "").strip(),
        study_designs=study_design,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )
    from .snowball.command import SnowballError, run_orcid

    try:
        seeds = _orcid_seeds(orcids, seeds_file)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _run_snowball(
        cfg, lambda c: run_orcid(c, seeds, request, console=out), json_out=json_out, command="snowball orcid"
    )

@snowball_app.command("collection")
def snowball_collection(
    seed_collection: str = typer.Argument(
        ..., help="Existing library collection whose DOIs seed the crawl."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    depth: int | None = typer.Option(
        None, "--depth", help="Graph hops. Default: [snowball] depth, else 1."
    ),
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    direction: str | None = typer.Option(None, "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="dry-run, approve-each, approve-batch, or auto. Default: config, else dry-run.",
    ),
    collection: str = typer.Option(
        "",
        "--collection",
        "-C",
        help="Target collection for --gate auto (defaults to the seed collection).",
    ),
    fetch_pdfs: str | None = FetchPdfsOpt,
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Expand DOIs already in a collection. Creates items only with --gate auto."""
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    target = collection or seed_collection
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=target,
        fetch_pdfs=fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=(cites_query or "").strip(),
        study_designs=study_design,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )
    from .snowball.command import run_collection

    _run_snowball(
        cfg,
        lambda c: run_collection(c, seed_collection, request, console=out),
        json_out=json_out,
        command="snowball collection",
    )

def _print_briefing(briefing: Any, *, apply: bool, collection: str, cfg: Config) -> None:
    counts = briefing.counts
    order = ("new", "exists", "deferred", "inbox")
    summary = " · ".join(f"{key} {counts[key]}" for key in order if key in counts)
    console.print(summary)
    console.print(f"Wrote [bold]{briefing.path}[/]")
    if not apply:
        return
    if not collection.strip():
        console.print("[red]--apply needs -C so the note has a collection.[/]")
        raise typer.Exit(1)
    backend = _connect(cfg)
    if not backend.supports_write():
        _exit_env("A briefing note needs library write support.", cfg)
    try:
        col = backend.resolve_collection(collection.strip())
        key = backend.create_or_update_collection_note(
            col.key, briefing.html, ["paperful:frontier-briefing"]
        )
    except LibraryError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    _flush(backend)
    console.print(f"Note [bold]{key}[/] in {col.path or collection}")

@snowball_app.command("trends")
def snowball_trends(
    query: str | None = typer.Argument(
        None, help="OpenAlex search string (or use --profile)."
    ),
    profile: str | None = ProfileOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Publication-year counts for a query or saved search/hybrid profile. Read-only."""
    from .snowball.trends_cmd import run_trends

    run_trends(
        console,
        query=query,
        profile=profile,
        year_from=year_from,
        year_to=year_to,
        config=config,
        fmt=fmt,
    )

@snowball_app.command("briefing")
def snowball_briefing(
    run_id: str = typer.Option(
        ..., "--run-id", help="Queue under state/snowball/<run-id>/."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Also file a collection note tagged paperful:frontier-briefing. Needs -C.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Collection for the note when --apply."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write markdown for a saved snowball queue. Does not create items."""
    from .snowball.briefing import write_run_briefing
    from .snowball.command import SnowballError

    cfg = _cfg(config)
    try:
        briefing = write_run_briefing(cfg, run_id)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _print_briefing(briefing, apply=apply, collection=collection, cfg=cfg)

@snowball_app.command("digest")
def snowball_digest(
    run_id: str = typer.Option(
        ..., "--run-id", help="Queue under state/snowball/<run-id>/."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Also file a collection note tagged paperful:frontier-briefing. Needs -C.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Collection for the note when --apply."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write a ranked frontier digest for a saved queue. Does not create items."""
    from .snowball.command import SnowballError
    from .snowball.digest import write_run_digest

    cfg = _cfg(config)
    try:
        digest = write_run_digest(cfg, run_id)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _print_briefing(digest, apply=apply, collection=collection, cfg=cfg)

@snowball_app.command("resume")
def snowball_resume(
    run_id: str = typer.Argument(
        ..., help="Run id under state/snowball/<run-id>/ with deferred.json."
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Target collection when the saved gate is auto."
    ),
    gate: str | None = typer.Option(
        None, "--gate", help="dry-run or auto. Default: config."
    ),
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Continue OpenAlex work saved when the daily budget was spent. Same API key."""
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=None,
        depth=None,
        max_candidates=None,
        year_from=None,
        year_to=None,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
    )
    from .snowball.command import run_resume

    _run_snowball(
        cfg,
        lambda c: run_resume(c, run_id, request, console=out),
        json_out=json_out,
        command="snowball resume",
    )

@snowball_app.command("continue")
def snowball_continue_cmd(
    run_id: str = typer.Argument(..., help="Run id under state/snowball/<run-id>/ with stop.json."),
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="auto marks unlabeled new rows as Keep. Default: the gate saved with the run.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Score Keep/Skip on the latest hop, then walk one more hop unless a stopping rule fires."""
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    from .snowball.command import run_continue

    _run_snowball(
        cfg,
        lambda c: run_continue(c, run_id, console=out, gate=gate),
        json_out=json_out,
        command="snowball continue",
    )

@snowball_app.command("apply")
def snowball_apply(
    run_id: str = typer.Argument(..., help="Run id under state/snowball/<run-id>/."),
    collection: str = typer.Option("", "--collection", "-C", help="Target collection."),
    fetch_pdfs: str | None = FetchPdfsOpt,
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Create keep=true rows from a prior queue (approve-batch or edited dry-run)."""
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate="auto",
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=None,
        max_candidates=None,
        year_from=None,
        year_to=None,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
    )
    from .snowball.command import run_apply

    _run_snowball(
        cfg,
        lambda c: run_apply(c, run_id, request, console=out),
        json_out=json_out,
        command="snowball apply",
    )

@snowball_app.command("run")
def snowball_run(
    profile: str = typer.Option(
        ..., "--profile", help="profiles/<name>.toml with kind = snowball."
    ),
    direction: str = typer.Option("", "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Run a saved snowball profile (keyword, DOI, ORCID, or collection)."""
    cfg = _cfg(config)
    if twenty_writeback is not None:
        cfg.twenty_writeback_listings = twenty_writeback
    json_out = _agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    from .snowball.command import (
        SnowballError,
        run_collection,
        run_doi,
        run_hybrid,
        run_orcid,
        run_search,
    )
    from .snowball.profile import composed_query_from_profile, load_profile, request_from_profile

    try:
        raw = load_profile(cfg, profile)
        request = request_from_profile(raw, cfg)
        if tag:
            from .identity import merge_tags

            request.tags = tuple(merge_tags(request.tags, tag))
        if direction.strip():
            request.direction = direction.strip()
        if keyword_limit is not None:
            request.keyword_limit = keyword_limit
        if keyword_hop_limit is not None:
            request.keyword_hop_limit = keyword_hop_limit
        if keyword_min_score is not None:
            request.keyword_min_score = keyword_min_score
        if cites_query is not None and cites_query.strip():
            request.cites_query = cites_query.strip()
        if dedupe_scope:
            request.dedupe_scope = dedupe_scope.strip()
        if dedupe_after:
            request.dedupe_after = dedupe_after.strip()
        if author_site_preflight is not None:
            request.author_site_preflight = author_site_preflight
        if stop_rule:
            request.stop_rule = stop_rule.strip()
        if stop_eps is not None:
            request.stop_eps = stop_eps
        if stop_k is not None:
            request.stop_k = stop_k
        if stop_max_screened is not None:
            request.stop_max_screened = stop_max_screened
        description = str(raw.get("description") or "").strip()
        if description and not json_out:
            console.print(description)
        mode = str(raw.get("mode") or "")
        if mode == "search":
            query = composed_query_from_profile(raw)

            def action(c):
                return run_search(c, query, request, console=out)
        elif mode == "hybrid":
            query = composed_query_from_profile(raw)

            def action(c):
                return run_hybrid(c, query, request, console=out)
        elif mode == "doi":
            dois = [str(item) for item in (raw.get("dois") or [])]

            def action(c):
                return run_doi(c, dois, request, console=out)
        elif mode == "orcid":
            from .snowball.profile import orcids_from_profile

            orcids = orcids_from_profile(raw)
            if not orcids:
                raise SnowballError(f"Profile {profile!r} needs orcid or orcids.")

            def action(c):
                return run_orcid(c, orcids, request, console=out)
        elif mode == "collection":
            seed = str(
                raw.get("seed_collection") or raw.get("collection") or ""
            ).strip()
            if not seed:
                raise SnowballError(f"Profile {profile!r} needs seed_collection.")
            if not request.collection.strip():
                request.collection = seed

            def action(c):
                return run_collection(c, seed, request, console=out)
        else:
            raise SnowballError(
                f"Profile {profile!r} mode must be search, hybrid, doi, orcid, or collection."
            )
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _run_snowball(cfg, action, json_out=json_out, command="snowball run")

snowball_profile_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Save a snowball profile beside config.toml. Seeds and knobs only.",
)
snowball_app.add_typer(snowball_profile_app, name="profile")

@snowball_profile_app.command("save")
def snowball_profile_save(
    name: str = typer.Argument(..., help="Profile name (profiles/<name>.toml)."),
    query: list[str] | None = typer.Option(
        None, "--query", help="Keyword seed. Repeat for several."
    ),
    doi: list[str] | None = typer.Option(
        None, "--doi", help="DOI seed. Repeat for several."
    ),
    orcid: list[str] | None = typer.Option(
        None, "--orcid", help="ORCID seed. Repeat for several."
    ),
    seed_collection: str = typer.Option(
        "", "--seed-collection", help="Collection whose DOIs seed the crawl."
    ),
    description: str = typer.Option("", "--description"),
    gate: str = typer.Option("dry-run", "--gate"),
    collection: str = typer.Option("", "--collection", "-C", help="Target collection."),
    fetch_pdfs: str = typer.Option("", "--fetch-pdfs", help="off, fast, or full."),
    depth: int | None = typer.Option(None, "--depth"),
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    direction: str = typer.Option("", "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    dedupe_scope: str = typer.Option("", "--dedupe-scope"),
    dedupe_after: str = typer.Option("", "--dedupe-after"),
    oa_only: bool = typer.Option(False, "--oa-only"),
    or_mode: bool = typer.Option(
        False, "--or", help="With several --query, match any (default: all)."
    ),
    hybrid: bool = typer.Option(
        False, "--hybrid", help="With --query, save mode = hybrid."
    ),
    languages: str = typer.Option("", "--languages"),
    min_seed_citations: int | None = typer.Option(None, "--min-seed-citations"),
    note_provenance: bool | None = typer.Option(
        None, "--note-provenance/--no-note-provenance"
    ),
    backends: str = typer.Option("", "--backends"),
    hybrid_seeds: int | None = typer.Option(None, "--hybrid-seeds"),
    refine: bool = typer.Option(False, "--refine"),
    author_site_preflight: bool = typer.Option(False, "--author-site-preflight"),
    stop_rule: str = typer.Option("", "--stop-rule", help="off, marginal_yield, asymptotic_coverage, budget, or any."),
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    seeds_file: str | None = SeedsFileOpt,
    force: bool = typer.Option(
        False, "--force", help="Overwrite, or save a writing gate."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write seeds and knobs. Refuses API keys. A writing gate needs --force."""
    cfg = _cfg(config)
    from .snowball.command import SnowballError
    from .snowball.profile import save_profile as save_snowball_profile

    queries = [part.strip() for part in (query or []) if part and part.strip()]
    from .snowball.command import SnowballError as _SB
    from .snowball.seeds import parse_seed_lines, read_seeds_text

    file_tokens: list[str] = []
    if seeds_file:
        try:
            file_tokens = parse_seed_lines(read_seeds_text(str(seeds_file)))
        except _SB as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(exc.code) from exc
        if doi:
            doi = list(doi) + file_tokens
        elif orcid:
            orcid = list(orcid) + file_tokens
        else:
            console.print("[red]--seeds-file needs --doi or --orcid.[/]")
            raise typer.Exit(2)
    seeds = [
        bool(queries),
        bool(doi),
        bool(orcid),
        bool(seed_collection.strip()),
    ]
    if sum(seeds) != 1:
        console.print(
            "[red]Pass exactly one of --query, --doi, --orcid, or --seed-collection.[/]"
        )
        raise typer.Exit(2)
    body: dict[str, Any] = {"gate": gate}
    if queries and hybrid:
        body["mode"] = "hybrid"
        _profile_queries(body, queries, or_mode=or_mode)
    elif queries:
        body["mode"] = "search"
        _profile_queries(body, queries, or_mode=or_mode)
    elif doi:
        body["mode"] = "doi"
        body["dois"] = list(doi)
    elif orcid:
        body["mode"] = "orcid"
        body["orcids"] = list(orcid)
    else:
        body["mode"] = "collection"
        body["seed_collection"] = seed_collection.strip()
    if description.strip():
        body["description"] = description.strip()
    if collection.strip():
        body["target_collection"] = collection.strip()
    if fetch_pdfs.strip():
        from .config import parse_fetch_pdfs

        try:
            body["fetch_pdfs"] = parse_fetch_pdfs(fetch_pdfs)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if depth is not None:
        body["depth"] = depth
    if max_candidates is not None:
        from .config import parse_cap

        try:
            body["max_candidates"] = parse_cap(max_candidates)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if per_hop_limit is not None:
        from .config import parse_cap

        try:
            body["per_hop_limit"] = parse_cap(per_hop_limit)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if per_hop_rank:
        from .config import parse_per_hop_rank

        try:
            body["per_hop_rank"] = parse_per_hop_rank(per_hop_rank)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if direction.strip():
        body["direction"] = direction.strip()
    if keyword_limit is not None:
        from .snowball.expand import parse_keyword_limit

        try:
            body["keyword_limit"] = parse_keyword_limit(keyword_limit)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if keyword_hop_limit is not None:
        from .snowball.expand import parse_keyword_hop_limit

        try:
            body["keyword_hop_limit"] = parse_keyword_hop_limit(keyword_hop_limit)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if keyword_min_score is not None:
        body["keyword_min_score"] = keyword_min_score
    if cites_query and cites_query.strip():
        body["cites_query"] = cites_query.strip()
    if study_design:
        from .snowball.expand import parse_study_designs

        try:
            body["study_designs"] = list(parse_study_designs(study_design))
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if year_from is not None:
        body["year_from"] = year_from
    if year_to is not None:
        body["year_to"] = year_to
    if dedupe_scope.strip():
        body["dedupe_scope"] = dedupe_scope.strip()
    if oa_only:
        body["oa_only"] = True
    if languages.strip():
        body["languages"] = _csv(languages)
    if min_seed_citations is not None:
        body["min_seed_citations"] = min_seed_citations
    if note_provenance is not None:
        body["note_provenance"] = note_provenance
    if backends.strip():
        body["backends"] = _csv(backends)
    if hybrid_seeds is not None:
        body["hybrid_seeds"] = hybrid_seeds
    if refine:
        body["refine"] = True
    if stop_rule.strip():
        body["stop_rule"] = stop_rule.strip()
    if stop_eps is not None:
        body["stop_eps"] = stop_eps
    if stop_k is not None:
        body["stop_k"] = stop_k
    if stop_max_screened is not None:
        body["stop_max_screened"] = stop_max_screened
    try:
        path = save_snowball_profile(cfg, name, body, force=force)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    console.print(f"Wrote [bold]{path}[/]")

snowball_packs_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Proposed field author packs from snowball preflight. Promote before fetch uses them.",
)
snowball_app.add_typer(snowball_packs_app, name="packs")

@snowball_packs_app.command("promote")
def snowball_packs_promote(
    slug: str = typer.Argument(..., help="Pack slug (state/author-packs/<slug>.proposed.toml)."),
    config: Path | None = ConfigOpt,
) -> None:
    """Copy a proposed author pack to the promoted file used by the author_site lane."""
    cfg = _cfg(config)
    from .snowball.command import SnowballError
    from .snowball.preflight import promote_pack

    try:
        path = promote_pack(cfg, slug)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    console.print(f"Promoted [bold]{path}[/]")

snowball_watch_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Pull-only watch: re-run a snowball profile, remember seen works, "
        "propose new arrivals on disk. Never creates library items. "
        "Paperful does not schedule watches; call watch run yourself."
    ),
)
snowball_app.add_typer(snowball_watch_app, name="watch")

@snowball_watch_app.command("save")
def snowball_watch_save(
    name: str = typer.Argument(
        ..., help="Watch name under state/snowball/watches/<name>/."
    ),
    profile: str = typer.Option(
        ..., "--profile", help="Existing kind=snowball profile."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Point a watch at a saved snowball profile. No API keys."""
    cfg = _cfg(config)
    from .snowball.command import SnowballError
    from .snowball.watch import save_watch

    try:
        path = save_watch(cfg, name, profile)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    console.print(f"Wrote [bold]{path}[/] · profile {profile}")

@snowball_watch_app.command("run")
def snowball_watch_run(
    name: str = typer.Argument(..., help="Watch name."),
    dedupe_scope: str | None = DedupeScopeOpt,
    digest: bool = typer.Option(
        False,
        "--digest",
        help="Also write watches/<name>/digest.md after a successful run.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Baseline on first run; later runs write only unseen new works to the inbox."""
    cfg = _cfg(config)
    from .snowball.digest import write_watch_digest
    from .snowball.watch import run_watch

    def _run(c: Config):
        result = run_watch(c, name, console=console, dedupe_scope=dedupe_scope)
        if digest and not result.exit_code:
            written = write_watch_digest(c, name)
            _print_briefing(written, apply=False, collection="", cfg=c)
        return result

    _run_snowball(cfg, _run)

@snowball_watch_app.command("show")
def snowball_watch_show(
    name: str = typer.Argument(..., help="Watch name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Inbox count and latest run id. Does not open the library."""
    cfg = _cfg(config)
    from .snowball.command import SnowballError
    from .snowball.watch import show_watch

    try:
        show_watch(cfg, name, console=console)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc

@snowball_watch_app.command("briefing")
def snowball_watch_briefing(
    name: str = typer.Argument(..., help="Watch name."),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Also file a collection note tagged paperful:frontier-briefing. Needs -C.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Collection for the note when --apply."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write markdown for a watch inbox. Does not create items."""
    from .snowball.briefing import write_watch_briefing
    from .snowball.command import SnowballError

    cfg = _cfg(config)
    try:
        briefing = write_watch_briefing(cfg, name)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _print_briefing(briefing, apply=apply, collection=collection, cfg=cfg)

@snowball_watch_app.command("digest")
def snowball_watch_digest(
    name: str = typer.Argument(..., help="Watch name."),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Also file a collection note tagged paperful:frontier-briefing. Needs -C.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Collection for the note when --apply."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write a ranked frontier digest for a watch. Does not create items."""
    from .snowball.command import SnowballError
    from .snowball.digest import write_watch_digest

    cfg = _cfg(config)
    try:
        digest = write_watch_digest(cfg, name)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _print_briefing(digest, apply=apply, collection=collection, cfg=cfg)

def _authorwatch_call(action: Callable[[], Any]) -> Any:
    from .authorwatch import AuthorwatchError

    try:
        return action()
    except AuthorwatchError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc

@authorwatch_app.command("save")
def authorwatch_save(
    name: str = typer.Argument(..., help="List name under state/authorwatch/<name>/."),
    config: Path | None = ConfigOpt,
) -> None:
    """Create an empty people list. No API keys."""
    from .authorwatch import save_list

    cfg = _cfg(config)
    path = _authorwatch_call(lambda: save_list(cfg, name))
    console.print(f"Wrote [bold]{path}[/]")

@authorwatch_app.command("add")
def authorwatch_add(
    name: str = typer.Argument(..., help="List name."),
    orcid: str = typer.Option("", "--orcid", help="ORCID iD (URL or XXXX-XXXX-XXXX-XXXX)."),
    display_name: str = typer.Option("", "--name", help="Display name when ORCID is unknown."),
    affiliation: str = typer.Option(
        "", "--affiliation", help="Host or institution hint for resolve."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Append a person. --orcid is enough; --name stays unresolved until resolve."""
    from .authorwatch import add_person

    cfg = _cfg(config)
    person = _authorwatch_call(
        lambda: add_person(
            cfg,
            name,
            orcid=orcid,
            display_name=display_name,
            affiliation_host=affiliation,
        )
    )
    console.print(
        f"Added {person.display_name or person.id} · {person.status} · {person.identity()}"
    )

@authorwatch_app.command("remove")
def authorwatch_remove(
    name: str = typer.Argument(..., help="List name."),
    orcid: str = typer.Option("", "--orcid", help="ORCID iD to drop."),
    person_id: str = typer.Option("", "--id", help="Person id from people.jsonl."),
    config: Path | None = ConfigOpt,
) -> None:
    """Drop a member by ORCID or id."""
    from .authorwatch import remove_person

    cfg = _cfg(config)
    person = _authorwatch_call(
        lambda: remove_person(cfg, name, orcid=orcid, person_id=person_id)
    )
    console.print(f"Removed {person.display_name or person.id}")

@authorwatch_app.command("show")
def authorwatch_show(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
) -> None:
    """People counts, held candidates, baseline, next step. Does not open the library."""
    from .authorwatch import show_list

    cfg = _cfg(config)
    _authorwatch_call(lambda: show_list(cfg, name, console=console))

@authorwatch_app.command("resolve")
def authorwatch_resolve(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Fill missing ORCID/OpenAlex ids. Ambiguous names stay held."""
    from .authorwatch import resolve_people

    cfg = _cfg(config)
    people = _authorwatch_call(lambda: resolve_people(cfg, name))
    ok = sum(1 for row in people if row.is_ok())
    held = sum(1 for row in people if row.status == "held")
    unresolved = sum(1 for row in people if row.status == "unresolved")
    console.print(f"ok {ok} · held {held} · unresolved {unresolved}")

@authorwatch_app.command("suggest")
def authorwatch_suggest_cmd(
    name: str = typer.Argument(..., help="List name."),
    collection: str = typer.Option(
        ..., "--collection", "-C", help="Collection scope for ranking."
    ),
    method: str = typer.Option(
        "corpus",
        "--method",
        help="corpus, most_cited, coauthor, or mix.",
    ),
    limit: int = typer.Option(15, "--limit", help="Max new suggestions this call."),
    config: Path | None = ConfigOpt,
) -> None:
    """Propose people to follow from a collection (local corpus / OpenAlex)."""
    from .authorwatch_suggest import suggest_people

    cfg = _cfg(config)
    rows = _authorwatch_call(
        lambda: suggest_people(
            cfg,
            name,
            collection=collection,
            method=method,
            limit=limit,
        )
    )
    console.print(f"Added {len(rows)} suggestion(s)")

@authorwatch_app.command("accept")
def authorwatch_accept_cmd(
    name: str = typer.Argument(..., help="List name."),
    suggestion_id: list[str] = typer.Option(
        [], "--id", help="Suggestion id from suggestions.jsonl (repeatable)."
    ),
    all_pending: bool = typer.Option(
        False, "--all-pending", help="Accept every pending suggestion."
    ),
    dismiss_rest: bool = typer.Option(
        False, "--dismiss-rest", help="Mark unselected pending rows dismissed."
    ),
    seed_from: str | None = typer.Option(
        None,
        "--seed-from",
        help="After accept, run authorwatch with --backfill-from (YYYY-MM-DD).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Move checked suggestions onto the people list."""
    from .authorwatch import accept_suggestions, run_list

    cfg = _cfg(config)
    accepted = _authorwatch_call(
        lambda: accept_suggestions(
            cfg,
            name,
            ids=set(suggestion_id),
            all_pending=all_pending,
            dismiss_rest=dismiss_rest,
        )
    )
    console.print(f"Accepted {len(accepted)} person(s)")
    if seed_from:
        _authorwatch_call(
            lambda: run_list(
                cfg,
                name,
                console=console,
                backfill_from=seed_from,
            )
        )

@authorwatch_app.command("delete")
def authorwatch_delete_cmd(
    name: str = typer.Argument(..., help="List name."),
    yes: bool = typer.Option(False, "--yes", help="Remove state/authorwatch/<name>/."),
    config: Path | None = ConfigOpt,
) -> None:
    """Delete a list and its ledger."""
    from .authorwatch import delete_list

    cfg = _cfg(config)
    _authorwatch_call(lambda: delete_list(cfg, name, yes=yes))
    console.print(f"Deleted list {name}")

@authorwatch_app.command("import")
def authorwatch_import(
    name: str = typer.Argument(..., help="List name."),
    path: Path | None = typer.Option(None, "--file", help="CSV, JSON, or ORCID list."),
    source: str = typer.Option(
        "csv",
        "--source",
        help="csv, json, orcid; rg/linkedin/academia need --file (no scrape).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Import people from a file. Social --source without --file prints the export recipe."""
    from .authorwatch import import_file

    cfg = _cfg(config)
    added = _authorwatch_call(
        lambda: import_file(cfg, name, path=path, source=source)
    )
    console.print(f"Imported {len(added)} row(s)")

@authorwatch_app.command("run")
def authorwatch_run(
    name: str = typer.Argument(..., help="List name."),
    backfill_from: str | None = typer.Option(
        None,
        "--backfill-from",
        help="YYYY-MM-DD publication date; propose recent works on this run.",
    ),
    max_authors: int = typer.Option(50, "--max-authors", help="Cap OpenAlex author polls."),
    per_author_limit: int = typer.Option(
        200, "--per-author-limit", help="Max works per author this run."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Cursor baseline (proposes 0) unless --backfill-from. Never creates library items."""
    from .authorwatch import run_list

    cfg = _cfg(config)
    _authorwatch_call(
        lambda: run_list(
            cfg,
            name,
            console=console,
            backfill_from=backfill_from,
            max_authors=max_authors,
            per_author_limit=per_author_limit,
        )
    )

@authorwatch_app.command("briefing")
def authorwatch_briefing(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Write markdown from the inbox plus OpenAlex people context. Does not create items."""
    from .agent_json import envelope
    from .authorwatch import gather_briefing, write_briefing

    cfg = _cfg(config)
    json_out = _agent_json(fmt)

    def _run() -> None:
        data = gather_briefing(cfg, name)
        path = write_briefing(cfg, name, data=data)

        def _human() -> None:
            console.print(f"Wrote [bold]{path}[/]")
            console.print(
                f"People enriched: {data.get('enriched_people', 0)} "
                f"(of {data.get('ok_people', 0)} ok)"
            )

        payload = envelope(
            command="authorwatch briefing",
            summary={
                "list": name,
                "proposed": len(data.get("proposed") or []),
                "ok_people": data.get("ok_people", 0),
                "enriched_people": data.get("enriched_people", 0),
                "people": data.get("people") or [],
            },
            paths={"briefing": str(path)},
            flags={"read_only": True},
        )
        _emit_agent(payload, json_out=json_out, human=_human)

    _authorwatch_call(_run)

@authorwatch_app.command("apply")
def authorwatch_apply_cmd(
    name: str = typer.Argument(..., help="List name."),
    collection: str = typer.Option(
        ..., "--collection", "-C", help="Target collection path."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create metadata parents. Default is dry-run. PDFs stay paperful run.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Create inbox rows in -C. Independent of [snowball] enabled."""
    from .authorwatch import apply_list

    cfg = _cfg(config)
    backend = None
    if apply:
        _require_manager(cfg)
        backend = _connect(cfg)
        if not backend.supports_write():
            _exit_env(_no_write(backend), cfg)

    def _go() -> Any:
        return apply_list(
            cfg,
            name,
            collection,
            console=console,
            apply=apply,
            backend=backend,
        )

    result = _authorwatch_call(_go)
    if result.failed and result.created:
        raise typer.Exit(3)


def _reconcile_jobs() -> None:
    """Keep JOBS aligned with registered top-level Typer commands.

    Curated categories stay as written. Any command missing from JOBS is
    appended to utility so ``paperful jobs`` and CI cannot drift when a new
    ``@app.command`` is added. Stale JOBS entries (listed but not registered)
    raise so typos surface at import time.
    """
    from typer.main import get_command

    registered = set(get_command(app).commands)
    listed = [verb for verbs in JOBS.values() for verb in verbs]
    if len(listed) != len(set(listed)):
        dupes = sorted({v for v in listed if listed.count(v) > 1})
        raise RuntimeError(f"JOBS has duplicate verbs: {dupes}")
    listed_set = set(listed)
    orphans = sorted(registered - listed_set)
    if orphans:
        JOBS["utility"] = tuple((*JOBS["utility"], *orphans))
    stale = sorted(listed_set - registered)
    if stale:
        raise RuntimeError(
            f"JOBS lists commands that are not registered: {stale}. "
            "Remove them from JOBS or restore the @app.command."
        )


_reconcile_jobs()

if __name__ == "__main__":
    app()
