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
        "keepup",
    ),
    "find": ("run", "attach", "recover", "gaps", "inbox", "capture", "urls", "htmlpdf"),
    "completeness": (
        "lint",
        "screen",
        "critique",
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
        "glossary",
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
SearchKeywordsOpt = typer.Option(
    None,
    "--search-keywords/--no-search-keywords",
    help=(
        "On keyword search/hybrid, also pull works tagged with matching OpenAlex keywords "
        "(union with full-text hits). Default: config, else on."
    ),
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
    allow_remote_bind: bool = typer.Option(
        False,
        "--allow-remote-bind",
        help=(
            "Allow binding a non-loopback address (e.g. 0.0.0.0). "
            "The workbench has no HTTP auth."
        ),
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Localhost workbench and JSON API. Needs paperful[serve]."""
    from .serve import SERVE_HINT, fastapi_available, run_server

    if not fastapi_available():
        console.print(f"[red]{SERVE_HINT}[/]")
        raise typer.Exit(1)
    try:
        run_server(
            _cfg(config),
            host=host,
            port=port,
            allow_remote_bind=allow_remote_bind,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


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
    as_json: bool = typer.Option(
        False, "--json", help="Legacy findings array. Prefer --format json."
    ),
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
    as_json: bool = typer.Option(
        False, "--json", help="Legacy findings array. Prefer --format json."
    ),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any finding."),
    apply: bool = typer.Option(
        False, "--apply", help="Write parent tag and child note for flagged items."
    ),
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


@critique_app.callback(invoke_without_command=True)
def critique(
    ctx: typer.Context,
    item: list[str] = typer.Option(
        [], "--item", help="Library item key already in the mirror."
    ),
    file_path: Path | None = typer.Option(
        None,
        "--file",
        help="Manuscript on disk (pdf, txt, md, html, rtf, docx, odt, pptx; .doc if a converter is on PATH).",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print findings; do not write state/critiques/."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write a child note. Needs --item (not --file)."
    ),
    llm: bool | None = typer.Option(
        None,
        "--llm/--no-llm",
        help="Alias for --lane reviewers (compat). Adds or removes that suggested review lane.",
    ),
    ai_model: bool = typer.Option(
        False,
        "--ai-model",
        help="Optional Binoculars-style AI-text extra (suggested lane; not installed by default).",
    ),
    vale: bool = typer.Option(
        False,
        "--vale",
        help="Optional Vale house-style pass (checked lane). Needs vale on PATH and a .vale.ini.",
    ),
    advanced: bool | None = typer.Option(
        None,
        "--advanced/--no-advanced",
        help="Alias for --lane marg (compat). MARG-S-style multi-agent comments.",
    ),
    lane: list[str] = typer.Option(
        [],
        "--lane",
        help="Suggested review lane (repeatable): reviewers, marg, context, context-web.",
    ),
    grobid: bool | None = typer.Option(
        None,
        "--grobid/--no-grobid",
        help="Use the GROBID sidecar for MARG-S chunking. Default is [grobid].enabled. Only used with --lane marg / --advanced.",
    ),
    reviewer: list[str] = typer.Option(
        [],
        "--reviewer",
        help="Run a subset of critique.reviewers ids (repeatable). Default: all.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Run the LLM lane even when identity lint flagged the PDF.",
    ),
    show_dismissed: bool = typer.Option(
        False,
        "--show-dismissed",
        help="Include dismissed findings in the table and Markdown.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Local manuscript critique pack. Checked findings always; suggested review lanes optional. Not a grade."""
    if ctx.invoked_subcommand is not None:
        return
    from .critique_cmd import run_critique

    run_critique(
        console,
        item=item,
        file_path=file_path,
        collection=collection,
        library=library,
        dry_run=dry_run,
        apply=apply,
        llm=llm,
        ai_model=ai_model,
        vale=vale,
        advanced=advanced,
        lane=lane,
        grobid=grobid,
        reviewer=reviewer,
        force=force,
        show_dismissed=show_dismissed,
        config=config,
        fmt=fmt,
    )


@critique_app.command("dismiss")
def critique_dismiss(
    finding_id: str = typer.Argument(
        ..., help="Finding id from pack.json / the critique table."
    ),
    critique_id: str | None = typer.Option(
        None,
        "--critique-id",
        help="Pack folder name (item key or file-<stem>). Default: newest.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Omit a finding from later pack.md (id stays in JSON). Re-runs keep the dismissal."""
    from .critique_cmd import run_dismiss

    run_dismiss(
        console,
        finding_id=finding_id,
        critique_id=critique_id,
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
    from .acronyms_cmd import run_acronyms

    run_acronyms(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        min_count=min_count,
        apply=apply,
        profile=profile,
        run_config=run_config,
        config=config,
    )


@glossary_app.command("validate")
def glossary_validate(
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Check state/glossary/*.json (paperful.glossary.v1)."""
    from .glossary_cmd import run_glossary_validate

    run_glossary_validate(console, config=config, fmt=fmt)


@glossary_app.command("export-vale")
def glossary_export_vale(
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Write YAML here. Default prints a Substitution style fragment.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Write Vale swap rules from glossary aliases (exact forms only)."""
    from .glossary_cmd import run_glossary_export_vale

    run_glossary_export_vale(console, config=config, fmt=fmt, out=out)


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
    offset: int = typer.Option(
        0,
        "--offset",
        help="Skip the first N items in library/collection order before applying --limit.",
        min=0,
    ),
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
        offset=offset,
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
    from .urls_cmd import run_urls

    run_urls(
        console,
        collection=collection,
        library=library,
        apply=apply,
        limit=limit,
        config=config,
        fmt=fmt,
    )


@htmlpdf_proposals_app.command("list")
def htmlpdf_proposals_list(
    status: str = typer.Option(
        "pending", "--status", help="pending, applied, rejected, or all."
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .htmlpdf_cmd import run_htmlpdf_proposals_list

    run_htmlpdf_proposals_list(console, status=status, config=config, fmt=fmt)


@htmlpdf_proposals_app.command("apply")
def htmlpdf_proposals_apply(
    proposal_id: str = typer.Argument(..., help="Proposal id."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .htmlpdf_cmd import run_htmlpdf_proposals_apply

    run_htmlpdf_proposals_apply(
        console, proposal_id=proposal_id, config=config, fmt=fmt
    )


@htmlpdf_proposals_app.command("reject")
def htmlpdf_proposals_reject(
    proposal_id: str = typer.Argument(..., help="Proposal id."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .htmlpdf_cmd import run_htmlpdf_proposals_reject

    run_htmlpdf_proposals_reject(
        console, proposal_id=proposal_id, config=config, fmt=fmt
    )


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
    as_json: bool = typer.Option(
        False, "--json", help="Legacy counts JSON. Prefer --format json."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Count items with no stored PDF, a linked PDF URL only, or no DOI.

    Points at `run` (PDFs) and `lint` (identifiers). Does not write the library
    unless ``--handoff walk`` or ``--handoff watch`` attaches files.
    """
    from .gaps_cmd import run_gaps_command

    run_gaps_command(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        list_missing=list_missing,
        handoff=handoff,
        include_doi_tabs=include_doi_tabs,
        downloads_dir=downloads_dir,
        request_rg=request_rg,
        re_request=re_request,
        to=to,
        as_json=as_json,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
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
    from .run_cmd import run_run_command

    run_run_command(
        console,
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
        ezproxy_relogin=ezproxy_relogin,
        browser_agent=browser_agent,
        camofox=camofox,
        upgrade_linked=upgrade_linked,
        upgrade_snapshot=upgrade_snapshot,
        keep_snapshot=keep_snapshot,
        htmlpdf_mode=htmlpdf_mode,
        serpapi_max=serpapi_max,
        strict_pdf_doi=strict_pdf_doi,
        handoff=handoff,
        include_doi_tabs=include_doi_tabs,
        downloads_dir=downloads_dir,
        request_rg=request_rg,
        re_request=re_request,
        twenty_writeback=twenty_writeback,
        promote=promote,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
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
    status: str = typer.Option(
        "pending", "--status", help="pending, applied, rejected, or all."
    ),
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
    proposal_id: str = typer.Argument(
        ..., help="Proposal id from inbox proposals list."
    ),
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
    proposal_id: str = typer.Argument(
        ..., help="Proposal id from inbox proposals list."
    ),
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
    from .twenty_cmd import run_twenty_lookup

    run_twenty_lookup(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        apply=apply,
        profile=profile,
        run_config=run_config,
        config=config,
    )


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
    from .twenty_cmd import run_twenty_sync

    run_twenty_sync(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        apply=apply,
        limit=limit,
        yes=yes,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("ingest-dois")
def ingest_dois_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Target collection for new parents."
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Text file: one DOI per line.",
        exists=True,
        dir_okay=False,
    ),
    from_pack: Path | None = typer.Option(
        None,
        "--from-pack",
        help="refs_gap or coverage pack.json (or its parent folder).",
        exists=True,
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Create parents. Default is dry-run."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify only (default)."),
    tag: list[str] = typer.Option(
        [], "--tag", help="Extra tags on created parents (repeatable)."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Create metadata parents from a DOI list. Dry-run unless --apply. Then run fills PDFs."""
    from .ingest_cmd import run_ingest_dois

    run_ingest_dois(
        console,
        collection=collection,
        from_file=from_file,
        from_pack=from_pack,
        apply=apply,
        dry_run=dry_run,
        tag=tag,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


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
    from .snapshot_cmd import run_snapshot_cmd

    run_snapshot_cmd(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        dry_run=dry_run,
        pdfs=pdfs,
        profile=profile,
        run_config=run_config,
        config=config,
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


@openalex_store_app.command("build-cites")
def openalex_store_build_cites(
    out: str = typer.Option(
        "",
        "--out",
        help=(
            "Directory for the inverted cites parquet tree. "
            "Default: directory implied by [openalex_store].cites_index_glob."
        ),
    ),
    timeout_s: float | None = typer.Option(
        None,
        "--timeout-s",
        help=(
            "Per-partition DuckDB timeout in seconds "
            "(default: build_timeout_s or 7200)."
        ),
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Invert works.referenced_works into a cites index for store-backed citing.

    Needs [openalex_store] with a works parquet_glob. Point cites_index_glob at
    ``<out>/**/*.parquet`` afterward (or use --out that matches that glob).

    Builds one works ``updated_date`` partition at a time and writes
    ``.done/<date>`` markers — safe to re-run after a crash. Full OpenAlex
    dumps can take many hours; for a remote host prefer a nohup'd build on
    that machine so a laptop disconnect does not stop the job.
    """
    from .sync_cmd import run_openalex_store_build_cites

    run_openalex_store_build_cites(
        console,
        out=out,
        timeout_s=timeout_s,
        config=config,
    )


@app.command()
def sync(
    full: bool = typer.Option(
        False, "--full", help="Read the whole library, not only what changed."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Count what would change. Reads the library, writes nothing.",
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
    from .sync_cmd import run_sync_command

    run_sync_command(
        console,
        full=full,
        dry_run=dry_run,
        pdfs=pdfs,
        accept_gone=accept_gone,
        config=config,
    )


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
    from .restore_cmd import run_restore

    run_restore(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        dry_run=dry_run,
        apply=apply,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


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
    from .sync_cmd import run_import_library

    run_import_library(
        console,
        path=path,
        fmt=fmt,
        apply=apply,
        config=config,
    )


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
    from .report_cmd import run_export_proposals

    run_export_proposals(
        console,
        pack=pack,
        dest=dest,
        fmt=fmt,
        config=config,
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
    from .report_cmd import run_report_counts

    run_report_counts(
        console,
        report_file=report_file,
    )


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
    from .report_cmd import run_report_new_count

    run_report_new_count(
        console,
        report_file=report_file,
    )


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
    from .report_cmd import run_report

    run_report(
        console,
        config=config,
        not_found=not_found,
        status=status,
        as_json=as_json,
        last_run=last_run,
    )


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
    from .rag_cmd import run_rag_ingest

    run_rag_ingest(
        console,
        item=item,
        collection=collection,
        library=library,
        force=force,
        retry_failed=retry_failed,
        no_ocr=no_ocr,
        dry_run=dry_run,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        profile=profile,
        run_config=run_config,
        config=config,
    )


@rag_app.command("status")
def rag_status(
    json_out: bool = typer.Option(False, "--json", help="Print JSON."),
    config: Path | None = ConfigOpt,
) -> None:
    """What the index holds and how far it is behind the mirror."""
    from .rag_cmd import run_rag_status

    run_rag_status(
        console,
        json_out=json_out,
        config=config,
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
    from .rag_cmd import run_rag_search

    run_rag_search(
        console,
        query=query,
        top_k=top_k,
        item=item,
        collection=collection,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        json_out=json_out,
        config=config,
    )


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
    from .rag_cmd import run_rag_questions

    run_rag_questions(
        console,
        item=item,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        llm=llm,
        limit=limit,
        dry_run=dry_run,
        config=config,
        fmt=fmt,
    )


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
    top_k: int | None = typer.Option(
        None, "-k", "--top-k", help="Passages per question."
    ),
    ask_mode: str | None = typer.Option(
        None,
        "--ask-mode",
        help="simple or advanced. Default is [rag].ask_mode.",
    ),
    force: bool = typer.Option(False, "--force", help="Ignore batch answer cache."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Ask whether the corpus already answers research questions."""
    from .rag_cmd import run_rag_answered

    run_rag_answered(
        console,
        from_file=from_file,
        from_extract=from_extract,
        after_item=after_item,
        item=item,
        collection=collection,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        top_k=top_k,
        ask_mode=ask_mode,
        force=force,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


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
        help="Prompt preset: default, questions, gaps, methods, answered, conflict.",
    ),
    prompt: Path | None = typer.Option(
        None, "--prompt", help="Override system prompt file for this run."
    ),
    ask_mode: str | None = typer.Option(
        None,
        "--ask-mode",
        help="simple (raw excerpts) or advanced (score then answer). Default is [rag].ask_mode.",
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
        ask_mode=ask_mode,
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
    grobid: bool | None = typer.Option(
        None,
        "--grobid/--no-grobid",
        help="Use the GROBID sidecar when available. Default is [grobid].enabled.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Extract IMRaD-style sections to disk (rules; optional GROBID / LLM)."""
    from .sections_cmd import run_extract_sections

    run_extract_sections(
        console,
        item=item,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        llm=llm,
        limit=limit,
        dry_run=dry_run,
        force=force,
        grobid=grobid,
        config=config,
        fmt=fmt,
    )


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
    upgrade_snapshot: bool | None = UpgradeSnapshotOpt,
    keep_snapshot: bool = typer.Option(
        False,
        "--keep-snapshot",
        help="With --upgrade-snapshot on the run step, leave the HTML print beside the new PDF.",
    ),
    htmlpdf: str | None = typer.Option(
        None,
        "--htmlpdf",
        help="Academic HTML snapshot on the run step: off, gated, or auto.",
    ),
    handoff: str | None = typer.Option(
        None,
        "--handoff",
        help=(
            "After the run step: list|tabs|walk|watch for soft-blocked openable PDF URLs. "
            "watch = tabs then poll the inbox.dir folder."
        ),
    ),
    gaps_handoff: str | None = typer.Option(
        None,
        "--gaps-handoff",
        help=(
            "Handoff mode for the optional gaps_handoff step (defaults to --handoff). "
            "list|tabs|walk|watch."
        ),
    ),
    include_doi_tabs: bool = typer.Option(
        False,
        "--include-doi-tabs",
        help="With run or gaps_handoff handoff tabs|watch, also open doi.org for doi_only rows.",
    ),
    downloads_dir: Path | None = typer.Option(
        None,
        "--downloads-dir",
        help="Downloads dir for run/gaps_handoff --handoff walk (default ~/Downloads).",
    ),
    ezproxy_relogin: bool | None = EzproxyReloginOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    request_rg: bool | None = RequestRgOpt,
    re_request: bool = ReRequestOpt,
    promote: str | None = typer.Option(
        None,
        "--promote",
        help="Override [playbooks].promote on the run step: gated or auto.",
    ),
    after_handoff_gaps: bool = typer.Option(
        False,
        "--after-handoff-gaps",
        help=(
            "Append a gaps_handoff step after the chain when --handoff or --gaps-handoff is set: "
            "gaps --list-missing with the same handoff options."
        ),
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
        handoff=_typer_opt(handoff),
        gaps_handoff=_typer_opt(gaps_handoff),
        include_doi_tabs=include_doi_tabs,
        downloads_dir=_typer_opt(downloads_dir),
        promote=_typer_opt(promote),
        htmlpdf=_typer_opt(htmlpdf),
        keep_snapshot=keep_snapshot,
        ezproxy_relogin=_typer_opt(ezproxy_relogin),
        twenty_writeback=_typer_opt(twenty_writeback),
        request_rg=_typer_opt(request_rg),
        re_request=re_request,
        after_handoff_gaps=after_handoff_gaps,
    )


def _dispatch_all_step(*args, **kwargs):
    from .all_cmd import _dispatch_all_step as _impl

    return _impl(*args, **kwargs)


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
    from .playbooks_cmd import run_playbooks_probe

    run_playbooks_probe(
        console,
        corpus=corpus,
        config=config,
        examples=examples,
        check=check,
        min_bytes=min_bytes,
        delay=delay,
        save=save,
        as_json=as_json,
    )


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
    from .playbooks_cmd import run_playbooks_propose

    run_playbooks_propose(
        console,
        config=config,
        to=to,
        min_hits=min_hits,
    )


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
    from .playbooks_cmd import run_playbooks_promote

    run_playbooks_promote(
        console,
        config=config,
        source=source,
    )


@profile_app.command("list")
def profile_list(config: Path | None = ConfigOpt) -> None:
    """List saved run configs. The builtin ``all`` policy is not a named profile."""
    from .profile_cmd import run_profile_list

    run_profile_list(
        console,
        config=config,
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
    from .profile_cmd import run_profile_show

    run_profile_show(
        console,
        name=name,
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
        sources=sources,
        preset=preset,
        apply=apply,
        overwrite=overwrite,
        steps=steps,
        skip=skip,
        require_summarize=require_summarize,
        profile=profile,
        run_config=run_config,
        config=config,
    )


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
    from .profile_cmd import run_profile_save

    run_profile_save(
        console,
        name=name,
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
        description=description,
        force=force,
        profile=profile,
        run_config=run_config,
        config=config,
    )


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
    search_keywords: bool | None = SearchKeywordsOpt,
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
    from .snowball_cmd import run_snowball_search

    run_snowball_search(
        console,
        queries=queries,
        year_from=year_from,
        year_to=year_to,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        search_keywords=search_keywords,
        cites_query=cites_query,
        study_design=study_design,
        or_mode=or_mode,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        languages=languages,
        min_seed_citations=min_seed_citations,
        note_provenance=note_provenance,
        backends=backends,
        refine=refine,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        config=config,
        fmt=fmt,
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
    search_keywords: bool | None = SearchKeywordsOpt,
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
    from .snowball_cmd import run_snowball_hybrid

    run_snowball_hybrid(
        console,
        queries=queries,
        year_from=year_from,
        year_to=year_to,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        hybrid_seeds=hybrid_seeds,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        search_keywords=search_keywords,
        cites_query=cites_query,
        study_design=study_design,
        or_mode=or_mode,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        languages=languages,
        min_seed_citations=min_seed_citations,
        refine=refine,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        config=config,
        fmt=fmt,
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
    from .snowball_cmd import run_snowball_doi

    run_snowball_doi(
        console,
        dois=dois,
        year_from=year_from,
        year_to=year_to,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=cites_query,
        study_design=study_design,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        seeds_file=seeds_file,
        config=config,
        fmt=fmt,
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
    from .snowball_cmd import run_snowball_orcid

    run_snowball_orcid(
        console,
        orcids=orcids,
        year_from=year_from,
        year_to=year_to,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=cites_query,
        study_design=study_design,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        seeds_file=seeds_file,
        config=config,
        fmt=fmt,
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
    from .snowball_cmd import run_snowball_collection

    run_snowball_collection(
        console,
        seed_collection=seed_collection,
        year_from=year_from,
        year_to=year_to,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=cites_query,
        study_design=study_design,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        config=config,
        fmt=fmt,
    )


def _print_briefing(
    briefing: Any, *, apply: bool, collection: str, cfg: Config
) -> None:
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
    from .snowball_cmd import run_snowball_trends

    run_snowball_trends(
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
    from .snowball_cmd import run_snowball_briefing

    run_snowball_briefing(
        console,
        run_id=run_id,
        apply=apply,
        collection=collection,
        config=config,
    )


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
    from .snowball_cmd import run_snowball_digest

    run_snowball_digest(
        console,
        run_id=run_id,
        apply=apply,
        collection=collection,
        config=config,
    )


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
    from .snowball_cmd import run_snowball_resume

    run_snowball_resume(
        console,
        run_id=run_id,
        collection=collection,
        gate=gate,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        config=config,
        fmt=fmt,
    )


@snowball_app.command("continue")
def snowball_continue_cmd(
    run_id: str = typer.Argument(
        ..., help="Run id under state/snowball/<run-id>/ with stop.json."
    ),
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="auto marks unlabeled new rows as Keep. Default: the gate saved with the run.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Score Keep/Skip on the latest hop, then walk one more hop unless a stopping rule fires."""
    from .snowball_cmd import run_snowball_continue

    run_snowball_continue(
        console,
        run_id=run_id,
        gate=gate,
        config=config,
        fmt=fmt,
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
    from .snowball_cmd import run_snowball_apply

    run_snowball_apply(
        console,
        run_id=run_id,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        config=config,
        fmt=fmt,
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
    from .snowball_cmd import run_snowball_run

    run_snowball_run(
        console,
        profile=profile,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=cites_query,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        config=config,
        fmt=fmt,
    )


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
    search_keywords: bool | None = SearchKeywordsOpt,
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
    stop_rule: str = typer.Option(
        "",
        "--stop-rule",
        help="off, marginal_yield, asymptotic_coverage, budget, or any.",
    ),
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
    from .snowball_cmd import run_snowball_profile_save

    run_snowball_profile_save(
        console,
        name=name,
        query=query,
        doi=doi,
        orcid=orcid,
        seed_collection=seed_collection,
        description=description,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        search_keywords=search_keywords,
        cites_query=cites_query,
        study_design=study_design,
        year_from=year_from,
        year_to=year_to,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        oa_only=oa_only,
        or_mode=or_mode,
        hybrid=hybrid,
        languages=languages,
        min_seed_citations=min_seed_citations,
        note_provenance=note_provenance,
        backends=backends,
        hybrid_seeds=hybrid_seeds,
        refine=refine,
        author_site_preflight=author_site_preflight,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        seeds_file=seeds_file,
        force=force,
        config=config,
    )


snowball_packs_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Proposed field author packs from snowball preflight. Promote before fetch uses them.",
)
snowball_app.add_typer(snowball_packs_app, name="packs")


@snowball_packs_app.command("promote")
def snowball_packs_promote(
    slug: str = typer.Argument(
        ..., help="Pack slug (state/author-packs/<slug>.proposed.toml)."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Copy a proposed author pack to the promoted file used by the author_site lane."""
    from .snowball_cmd import run_snowball_packs_promote

    run_snowball_packs_promote(
        console,
        slug=slug,
        config=config,
    )


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
    from .snowball_cmd import run_snowball_watch_save

    run_snowball_watch_save(
        console,
        name=name,
        profile=profile,
        config=config,
    )


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
    from .snowball_cmd import run_snowball_watch_run

    run_snowball_watch_run(
        console,
        name=name,
        dedupe_scope=dedupe_scope,
        digest=digest,
        config=config,
    )


@snowball_watch_app.command("rebaseline")
def snowball_watch_rebaseline(
    name: str = typer.Argument(
        "", help="Watch name. Leave empty with --all to check every watch."
    ),
    all_watches: bool = typer.Option(False, "--all", help="Every saved watch."),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write the reset. Without it this only reports what would change.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reset even if the watch was already reset or baselined after the change.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Re-baseline keyword watches once after OpenAlex's Oct 2026 topic change.

    The next `watch run` then absorbs reassigned works as seen instead of
    proposing them as new. Does not touch the inbox or open the library.
    """
    from .snowball_cmd import run_snowball_watch_rebaseline

    run_snowball_watch_rebaseline(
        console,
        name=name,
        all_watches=all_watches,
        apply=apply,
        force=force,
        config=config,
    )


@snowball_watch_app.command("show")
def snowball_watch_show(
    name: str = typer.Argument(..., help="Watch name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Inbox count and latest run id. Does not open the library."""
    from .snowball_cmd import run_snowball_watch_show

    run_snowball_watch_show(
        console,
        name=name,
        config=config,
    )


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
    from .snowball_cmd import run_snowball_watch_briefing

    run_snowball_watch_briefing(
        console,
        name=name,
        apply=apply,
        collection=collection,
        config=config,
    )


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
    from .snowball_cmd import run_snowball_watch_digest

    run_snowball_watch_digest(
        console,
        name=name,
        apply=apply,
        collection=collection,
        config=config,
    )


@snowball_watch_app.command("apply")
def snowball_watch_apply(
    name: str = typer.Argument(..., help="Watch name."),
    collection: str = typer.Option(
        ..., "--collection", "-C", help="Target collection path."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create metadata parents from the watch inbox. Default is dry-run.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Create parents from watches/<name>/inbox.jsonl. PDFs stay paperful run."""
    from .snowball_cmd import run_snowball_watch_apply

    run_snowball_watch_apply(
        console,
        name=name,
        collection=collection,
        apply=apply,
        config=config,
    )


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
    from .authorwatch_cmd import run_authorwatch_save

    run_authorwatch_save(
        console,
        name=name,
        config=config,
    )


@authorwatch_app.command("add")
def authorwatch_add(
    name: str = typer.Argument(..., help="List name."),
    orcid: str = typer.Option(
        "", "--orcid", help="ORCID iD (URL or XXXX-XXXX-XXXX-XXXX)."
    ),
    display_name: str = typer.Option(
        "", "--name", help="Display name when ORCID is unknown."
    ),
    affiliation: str = typer.Option(
        "", "--affiliation", help="Host or institution hint for resolve."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Append a person. --orcid is enough; --name stays unresolved until resolve."""
    from .authorwatch_cmd import run_authorwatch_add

    run_authorwatch_add(
        console,
        name=name,
        orcid=orcid,
        display_name=display_name,
        affiliation=affiliation,
        config=config,
    )


@authorwatch_app.command("remove")
def authorwatch_remove(
    name: str = typer.Argument(..., help="List name."),
    orcid: str = typer.Option("", "--orcid", help="ORCID iD to drop."),
    person_id: str = typer.Option("", "--id", help="Person id from people.jsonl."),
    config: Path | None = ConfigOpt,
) -> None:
    """Drop a member by ORCID or id."""
    from .authorwatch_cmd import run_authorwatch_remove

    run_authorwatch_remove(
        console,
        name=name,
        orcid=orcid,
        person_id=person_id,
        config=config,
    )


@authorwatch_app.command("show")
def authorwatch_show(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
) -> None:
    """People counts, held candidates, baseline, next step. Does not open the library."""
    from .authorwatch_cmd import run_authorwatch_show

    run_authorwatch_show(
        console,
        name=name,
        config=config,
    )


@authorwatch_app.command("resolve")
def authorwatch_resolve(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Fill missing ORCID/OpenAlex ids. Ambiguous names stay held."""
    from .authorwatch_cmd import run_authorwatch_resolve

    run_authorwatch_resolve(
        console,
        name=name,
        config=config,
    )


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
    from .authorwatch_cmd import run_authorwatch_suggest

    run_authorwatch_suggest(
        console,
        name=name,
        collection=collection,
        method=method,
        limit=limit,
        config=config,
    )


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
    from .authorwatch_cmd import run_authorwatch_accept

    run_authorwatch_accept(
        console,
        name=name,
        suggestion_id=suggestion_id,
        all_pending=all_pending,
        dismiss_rest=dismiss_rest,
        seed_from=seed_from,
        config=config,
    )


@authorwatch_app.command("delete")
def authorwatch_delete_cmd(
    name: str = typer.Argument(..., help="List name."),
    yes: bool = typer.Option(False, "--yes", help="Remove state/authorwatch/<name>/."),
    config: Path | None = ConfigOpt,
) -> None:
    """Delete a list and its ledger."""
    from .authorwatch_cmd import run_authorwatch_delete

    run_authorwatch_delete(
        console,
        name=name,
        yes=yes,
        config=config,
    )


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
    from .authorwatch_cmd import run_authorwatch_import

    run_authorwatch_import(
        console,
        name=name,
        path=path,
        source=source,
        config=config,
    )


@authorwatch_app.command("run")
def authorwatch_run(
    name: str = typer.Argument(..., help="List name."),
    backfill_from: str | None = typer.Option(
        None,
        "--backfill-from",
        help="YYYY-MM-DD publication date; propose recent works on this run.",
    ),
    max_authors: int = typer.Option(
        50, "--max-authors", help="Cap OpenAlex author polls."
    ),
    per_author_limit: int = typer.Option(
        200, "--per-author-limit", help="Max works per author this run."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Cursor baseline (proposes 0) unless --backfill-from. Never creates library items."""
    from .authorwatch_cmd import run_authorwatch_run

    run_authorwatch_run(
        console,
        name=name,
        backfill_from=backfill_from,
        max_authors=max_authors,
        per_author_limit=per_author_limit,
        config=config,
    )


@authorwatch_app.command("briefing")
def authorwatch_briefing(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Write markdown from the inbox plus OpenAlex people context. Does not create items."""
    from .authorwatch_cmd import run_authorwatch_briefing

    run_authorwatch_briefing(
        console,
        name=name,
        config=config,
        fmt=fmt,
    )


@authorwatch_app.command("digest")
def authorwatch_digest_cmd(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Write digest.md from the inbox. Does not create items."""
    from .authorwatch_cmd import run_authorwatch_digest

    run_authorwatch_digest(
        console,
        name=name,
        config=config,
    )


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
    from .authorwatch_cmd import run_authorwatch_apply

    run_authorwatch_apply(
        console,
        name=name,
        collection=collection,
        apply=apply,
        config=config,
    )


def _keepup_call(action: Callable[[], Any]) -> Any:
    from .keepup import KeepupError
    from .snowball.command import SnowballError

    try:
        return action()
    except (KeepupError, SnowballError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(getattr(exc, "code", 2) or 2) from exc


@keepup_app.command("save")
def keepup_save(
    name: str = typer.Argument(..., help="Job name under state/keepup/<name>/."),
    collection: str = typer.Option(
        ..., "--collection", "-C", help="Target Zotero collection path."
    ),
    watch: list[str] = typer.Option(
        [], "--watch", help="Snowball watch name (repeatable)."
    ),
    authorwatch: list[str] = typer.Option(
        [], "--authorwatch", help="Authorwatch list name (repeatable)."
    ),
    source: list[str] = typer.Option(
        [],
        "--source",
        help="Built-in source type. Use cites for what-cites-my-collection.",
    ),
    interval_days: int | None = typer.Option(
        None,
        "--interval-days",
        help="Days between polls (default [keepup].interval_days or 7).",
    ),
    per_seed_limit: int = typer.Option(
        20, "--per-seed-limit", help="OpenAlex citing works per seed paper."
    ),
    max_candidates: int = typer.Option(
        100, "--max-candidates", help="Cap proposed rows per cites poll (0 = no cap)."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Create or update a keepup job. No API keys."""
    from .keepup_cmd import run_keepup_save

    run_keepup_save(
        console,
        name=name,
        collection=collection,
        watch=watch,
        authorwatch=authorwatch,
        source=source,
        interval_days=interval_days,
        per_seed_limit=per_seed_limit,
        max_candidates=max_candidates,
        config=config,
    )


@keepup_app.command("list")
def keepup_list_cmd(config: Path | None = ConfigOpt) -> None:
    """List keepup jobs."""
    from .keepup_cmd import run_keepup_list

    run_keepup_list(
        console,
        config=config,
    )


@keepup_app.command("show")
def keepup_show(
    name: str = typer.Argument(..., help="Job name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Show job ledger. Does not open the library."""
    from .keepup_cmd import run_keepup_show

    run_keepup_show(
        console,
        name=name,
        config=config,
    )


@keepup_app.command("delete")
def keepup_delete(
    name: str = typer.Argument(..., help="Job name."),
    yes: bool = typer.Option(False, "--yes", help="Remove state/keepup/<name>/."),
    config: Path | None = ConfigOpt,
) -> None:
    """Delete a keepup job ledger."""
    from .keepup_cmd import run_keepup_delete

    run_keepup_delete(
        console,
        name=name,
        yes=yes,
        config=config,
    )


@keepup_app.command("run")
def keepup_run(
    name: str = typer.Argument(..., help="Job name."),
    force: bool = typer.Option(
        False, "--force", help="Ignore interval_days and poll now."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="After polling, create parents in the job collection.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Poll sources (respecting interval). Baseline proposes nothing."""
    from .keepup_cmd import run_keepup_run

    run_keepup_run(
        console,
        name=name,
        force=force,
        apply=apply,
        config=config,
    )


@keepup_app.command("digest")
def keepup_digest(
    name: str = typer.Argument(..., help="Job name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Rebuild digest.md from the keepup inbox. Does not create items."""
    from .keepup_cmd import run_keepup_digest

    run_keepup_digest(
        console,
        name=name,
        config=config,
    )


@keepup_app.command("apply")
def keepup_apply_cmd(
    name: str = typer.Argument(..., help="Job name."),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create metadata parents. Default is dry-run.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Create parents from the keepup inbox into the job collection."""
    from .keepup_cmd import run_keepup_apply

    run_keepup_apply(
        console,
        name=name,
        apply=apply,
        config=config,
    )


@keepup_app.command("dismiss")
def keepup_dismiss(
    name: str = typer.Argument(..., help="Job name."),
    doi: str = typer.Option("", "--doi", help="DOI to mute."),
    identity: str = typer.Option(
        "", "--identity", help="Identity key (doi:… or openalex:…)."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Mute a work so keepup never re-proposes it."""
    from .keepup_cmd import run_keepup_dismiss

    run_keepup_dismiss(
        console,
        name=name,
        doi=doi,
        identity=identity,
        config=config,
    )


@capture_app.callback(invoke_without_command=True)
def capture_main(
    ctx: typer.Context,
    stdio: bool = typer.Option(
        False, "--stdio", help="Native messaging loop for the Firefox add-on."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Mirror capture. ``--stdio`` speaks Firefox native messaging."""
    if ctx.invoked_subcommand is not None:
        return
    if not stdio:
        console.print(ctx.get_help())
        raise typer.Exit(0)
    from .capture_host import serve_stdio

    serve_stdio(_cfg(config))


@capture_app.command("plan")
def capture_plan(
    doi: str = typer.Option("", "--doi"),
    url: str = typer.Option("", "--url"),
    title: str = typer.Option("", "--title"),
    year: int | None = typer.Option(None, "--year"),
    pdf_url: str = typer.Option("", "--pdf-url"),
    config: Path | None = ConfigOpt,
) -> None:
    """Dry-run identity: create, update, blocked, or ambiguous. Writes nothing."""
    from .capture import as_year, plan_page

    result = plan_page(
        _cfg(config),
        doi=doi,
        url=url,
        title=title,
        year=year if year is not None else as_year(year),
        pdf_url=pdf_url,
    )
    console.print_json(json.dumps(result))


@capture_app.command("apply")
def capture_apply(config: Path | None = ConfigOpt) -> None:
    """Read one JSON object on stdin and write the mirror."""
    from .capture import apply_page

    try:
        body = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        console.print_json(json.dumps({"ok": False, "reason": "invalid"}))
        raise typer.Exit(2)
    if not isinstance(body, dict):
        console.print_json(json.dumps({"ok": False, "reason": "invalid"}))
        raise typer.Exit(2)
    result = apply_page(_cfg(config), body)
    code = int(result.pop("code", 0 if result.get("ok") else 2))
    console.print_json(json.dumps(result))
    if code:
        raise typer.Exit(code)


@capture_app.command("session")
def capture_session(config: Path | None = ConfigOpt) -> None:
    """Print the open handoff tab list, or an empty list."""
    from .capture import read_session

    console.print_json(json.dumps(read_session(_cfg(config))))


@capture_app.command("install-host")
def capture_install_host(config: Path | None = ConfigOpt) -> None:
    """Install the user-level Firefox native messaging host (macOS, Linux, Windows)."""
    from .capture_host import install_host

    line = install_host(_cfg(config), config)
    console.print(line)


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
