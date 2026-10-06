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
        "snowball",
        "ingest-dois",
        "twenty",
        "reachout",
        "authorwatch",
    ),
    "find": ("run", "attach", "recover", "gaps", "inbox", "urls", "htmlpdf"),
    "completeness": (
        "lint",
        "fix-metadata",
        "dedupe",
        "attachments",
        "versions",
        "ocr",
        "summarize",
        "synthesize",
        "rag",
        "ask",
        "refs",
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
    ),
    "utility": ("report", "version", "jobs"),
}

console = Console(highlight=False)


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()

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


def _bind_run(cfg: Config, **kwargs: Any) -> ResolvedRunConfig:
    try:
        return resolve_run_config(cfg, **kwargs)
    except RunConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


def _scope_unset(
    collection: list[str],
    library: bool | None,
    profile: str | None,
    run_config: Path | None,
) -> bool:
    return not profile and run_config is None and not collection and library is None


def _refuse_missing_scope() -> None:
    console.print("[red]Give --collection PATH (repeatable) or --library.[/]")
    raise typer.Exit(1)


def _inbox_library_when_unscoped(
    collection: list[str],
    library: bool | None,
    profile: str | None,
    run_config: Path | None,
) -> bool | None:
    """Shared drop folder: default to whole-library DOI match when scope is omitted."""
    if _scope_unset(collection, library, profile, run_config):
        return True
    return library


def _take_scope(
    bound: ResolvedRunConfig,
) -> tuple[list[str], bool, int | None, int | None, list[str]]:
    return (
        bound.collections,
        bound.library,
        bound.year_from,
        bound.year_to,
        bound.types,
    )


class WriteDest(str, Enum):
    disk = "disk"
    zotero = "zotero"
    both = "both"


class SummarizeOrder(str, Enum):
    newest = "newest"
    oldest = "oldest"
    library = "library"


def _item_progress(*, json_out: bool = False, transient: bool = False):
    """Live bar that stays below scrolling per-item logs.

    ``json_out`` keeps stdout pure: the bar moves to stderr, and only on a
    terminal.
    """
    live = Console(stderr=True, highlight=False) if json_out else console
    # Off a terminal a spinner has nothing to show, and JSON runs stay quiet.
    quiet = (json_out or transient) and not live.is_terminal
    return item_progress(live, disable=quiet, transient=transient)


def _track(progress, description: str) -> Track:
    return tracker(progress, description)


@contextmanager
def _spinner(
    text: str, *, json_out: bool = False
) -> Iterator[Callable[[str], None]]:
    """Spinner and clock for one slow call that has no item count.

    Yields a function that replaces the text. The line clears when done.
    """
    with _item_progress(json_out=json_out, transient=True) as progress:
        task_id = progress.add_task(text, total=None)
        yield lambda msg: progress.update(task_id, description=msg)


def _load_scope(backend: LibraryBackend, *, json_out: bool = False, **scope: Any):
    """``_loaded_scope`` behind a spinner that shows the loader's own status."""
    with _spinner("Connecting to library scope…", json_out=json_out) as say:
        return _loaded_scope(backend, status=say, **scope)


def _cfg(path: Path | None) -> Config:
    try:
        cfg = load_config(path)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def _resolve_source_names(sources: str | None, preset: str | None) -> list[str] | None:
    """Return explicit source names from --sources or --preset, or None to use config."""
    if preset:
        key = preset.strip().lower()
        if key not in SOURCE_PRESETS:
            console.print(
                f"[red]Unknown preset '{preset}'.[/] Known: {', '.join(sorted(SOURCE_PRESETS))}"
            )
            raise typer.Exit(1)
        return list(SOURCE_PRESETS[key])
    if not sources:
        return None
    token = sources.strip().lower()
    if token in SOURCE_PRESETS:
        return list(SOURCE_PRESETS[token])
    return [s.strip() for s in sources.split(",") if s.strip()]


def _source_list(
    cfg: Config, sources: str | None, enable_scihub: bool, preset: str | None = None
) -> list[str]:
    """Configured order, optional --sources/--preset override, then optional --scihub append."""
    resolved = _resolve_source_names(sources, preset)
    listed = resolved if resolved is not None else list(cfg.sources)
    if enable_scihub and "scihub" not in listed:
        listed.append("scihub")
    return listed


def _zotero(*, quiet: bool = False) -> ZoteroLocal:
    zl = ZoteroLocal()
    try:
        info = zl.ping()
    except ConnectionError as exc:
        _exit_env(str(exc))
    except Exception as exc:  # Zotero not running
        from .zot import zotero_local_label

        _exit_env(f"Cannot reach Zotero local API at {zotero_local_label()}: {exc}")
    if not quiet:
        console.print(
            f"[dim]Zotero {info.get('zotero_version') or '?'}, local API v{info['api_version']}, write support: "
            f"{'yes' if info['supports_write'] else 'no (Zotero 10+ needed)'}[/]"
        )
    return zl


def _env_code(message: str) -> str:
    low = message.lower()
    if "no write support" in low or "needs zotero 10" in low:
        return "zotero_no_write"
    if "local api is disabled" in low or "allow other applications" in low:
        return "zotero_api_off"
    if "400" in low and "host" in low:
        return "zotero_bad_host"
    if any(
        token in low
        for token in ("nodename", "name or service not known", "name resolution")
    ):
        return "zotero_host_unresolved"
    if any(
        token in low
        for token in (
            "cannot reach",
            "connection refused",
            "unreachable",
            "timed out",
            "connect",
        )
    ):
        return "zotero_down"
    return ""


def _zotero_next_steps(code: str, *, in_doctor: bool) -> list[str]:
    host = os.environ.get("PAPERFUL_ZOTERO_HOST", "").strip()
    host_tip = (
        "Host Zotero must be running on this machine. The Host header is always "
        "localhost:23119; PAPERFUL_ZOTERO_HOST is only the TCP address. "
        "See docs/zotero.md."
    )
    if code == "zotero_api_off":
        steps = [
            "Settings → Advanced → enable “Allow other applications on this computer to communicate with Zotero”.",
            "See docs/zotero.md.",
        ]
    elif code == "zotero_no_write":
        steps = [
            "Attach needs Zotero 10+. This build can still download PDFs to out/.",
            "Upgrade, then run paperful attach. See docs/zotero.md.",
        ]
    elif code == "zotero_host_unresolved":
        configured = host or "the configured host"
        steps = [
            f"{configured} does not resolve on this machine. Unset PAPERFUL_ZOTERO_HOST when running outside Docker.",
            "The Host header is always localhost:23119. See docs/zotero.md.",
        ]
    elif code in {"zotero_down", "zotero_bad_host"}:
        steps = [
            "The local mirror does not need Zotero. This command reads the live library, which is not reachable.",
        ]
        if host or code == "zotero_bad_host":
            steps.append(host_tip)
        steps.append(
            "When you want this command to use the library, start Zotero and enable the local API."
        )
    else:
        steps = [
            "The local mirror does not need Zotero. This command reads the live library, which is not reachable.",
            "When you want this command to use the library, start Zotero and enable the local API.",
        ]
        if host:
            steps.append(host_tip)
    if not in_doctor and code != "zotero_no_write":
        steps.append("Run paperful doctor for a full check.")
    if code not in {"zotero_no_write", "zotero_api_off"}:
        steps.append(
            "If you have no config yet: cp config.example.toml config.toml and set email."
        )
    return steps


def _print_exit_ladder(
    cfg: Config | None = None, *, code: str = "", in_doctor: bool = False
) -> None:
    manager = (cfg.manager if cfg else "zotero") or "zotero"
    manager = manager.strip().lower()
    if manager == "mendeley":
        console.print(
            "\n[bold]Next steps[/]\n"
            "  1. Register an app at https://dev.mendeley.com/myapps.html\n"
            "     (redirect http://127.0.0.1:8765/callback).\n"
            "  2. Set [mendeley] client_id / client_secret in config.toml.\n"
            "  3. Run [bold]paperful session login mendeley[/].\n"
            "  4. Run [bold]paperful doctor[/].\n"
        )
        return
    if manager == "endnote":
        console.print(
            "\n[bold]Next steps[/]\n"
            '  1. Set [endnote] library = "/path/to/Library.enl".\n'
            "  2. Confirm the matching .Data folder (sdb/sdb.eni, PDF/) is beside it.\n"
            "  3. Run [bold]paperful doctor[/].\n"
        )
        return
    steps = _zotero_next_steps(code, in_doctor=in_doctor)
    body = "\n".join(f"  {i}. {step}" for i, step in enumerate(steps, start=1))
    console.print(f"\n[bold]Next steps[/]\n{body}\n")


def _exit_env(message: str, cfg: Config | None = None, *, code: str = "") -> None:
    console.print(f"[red]{message}[/]")
    _print_exit_ladder(cfg, code=code or _env_code(message))
    raise typer.Exit(2)


def _warn_if_scihub(source_list: list[str]) -> None:
    if "scihub" in source_list:
        console.print(f"[red]{SCIHUB_DISCLAIMER}[/]")


def _warn_if_recover(source_list: list[str]) -> None:
    if "browser_agent" in source_list:
        console.print(f"[orange3]{RECOVER_DISCLAIMER}[/]")


def _require_manager(cfg: Config) -> None:
    manager = (cfg.manager or "zotero").strip().lower()
    if manager not in KNOWN_MANAGERS:
        console.print(
            f"[red]Unknown manager={manager!r}.[/] Known: zotero, mendeley, endnote."
        )
        raise typer.Exit(1)


def _manager_name(cfg: Config) -> str:
    return (cfg.manager or "zotero").strip().lower() or "zotero"


_OFFLINE = False


def _offline() -> bool:
    """``--offline`` or ``PAPERFUL_OFFLINE=1``: leave the manager alone."""
    return _OFFLINE or os.environ.get("PAPERFUL_OFFLINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _try_live(cfg: Config, *, quiet: bool = False) -> tuple[LibraryBackend | None, str]:
    """The manager itself, or (None, reason) when it is not reachable."""
    manager = _manager_name(cfg)
    try:
        if manager == "zotero":
            zl = ZoteroLocal()
            info = zl.ping()
            if not quiet:
                console.print(
                    f"[dim]Zotero {info.get('zotero_version') or '?'}, "
                    f"local API v{info.get('api_version')}, write support: "
                    f"{'yes' if info.get('supports_write') else 'no'}[/]"
                )
            return mirrored(cfg, get_backend(cfg, zl)), ""
        backend = mirrored(cfg, get_backend(cfg))
        info = backend.ping()
        if not quiet and manager == "mendeley":
            console.print(
                f"[dim]Mendeley {info.get('display_name') or '?'}, write support: yes[/]"
            )
        elif not quiet and manager == "endnote":
            console.print(
                f"[dim]EndNote {info.get('library') or '?'}, "
                f"{info.get('refs', '?')} refs, writes via import bundle[/]"
            )
        return backend, ""
    except Exception as exc:
        return None, str(exc)


def _mirror_first(cfg: Config, live: LibraryBackend, *, quiet: bool) -> LibraryBackend:
    """Refresh the mirror from ``live`` and read from it."""

    def say(msg: str) -> None:
        if not quiet:
            console.print(f"[dim]{msg}[/]")

    try:
        return open_library(cfg, live=live, status=say)
    except LibraryError as exc:
        _exit_env(str(exc), cfg)


def _open_library(cfg: Config, *, quiet: bool = False) -> tuple[LibraryBackend | None, str]:
    """The library, or (None, reason) when the manager is not reachable.

    A missing manager does not stop work that can stay on the local mirror.
    """
    if _offline():
        return None, "offline was asked for"
    live, reason = _try_live(cfg, quiet=quiet)
    if live is None:
        return None, reason
    return _mirror_first(cfg, live, quiet=quiet), ""


def _live_backend(cfg: Config, *, quiet: bool = False) -> LibraryBackend:
    """The manager itself, for verbs that compare it with the mirror. Exits 2 when it is down."""
    manager = (cfg.manager or "zotero").strip().lower()
    if _offline():
        _exit_env(f"This command reads {manager} directly and cannot run offline.", cfg)
    if manager == "zotero":
        zl = _zotero(quiet=quiet)
        return mirrored(cfg, get_backend(cfg, zl))
    try:
        backend = mirrored(cfg, get_backend(cfg))
        info = backend.ping()
    except LibraryError as exc:
        _exit_env(str(exc), cfg)
    except Exception as exc:
        _exit_env(f"Cannot reach {manager}: {exc}", cfg)
    if not quiet:
        if manager == "mendeley":
            who = info.get("display_name") or "?"
            console.print(f"[dim]Mendeley {who}, write support: yes[/]")
        elif manager == "endnote":
            console.print(
                f"[dim]EndNote {info.get('library') or '?'}, "
                f"{info.get('refs', '?')} refs, writes via import bundle[/]"
            )
    return backend


def _connect(cfg: Config, *, quiet: bool = False) -> LibraryBackend:
    """The library for a command: the mirror, refreshed when the manager answers.

    With the manager down and a mirror on disk, reads carry on from the mirror
    and writes are refused. With neither, exits 2.
    """
    catalogue = MirrorCatalogue(cfg.out_dir)
    if _offline():
        if not catalogue.usable():
            _exit_env("Offline, and there is no mirror under out/ to work from.", cfg)
        if not quiet:
            console.print(f"[dim]Offline. Working from {catalogue.age_line()}.[/]")
        return MirrorFirstBackend(cfg, catalogue, None)
    if not catalogue.usable():
        # Nothing on disk yet: the manager has to be there. Exits 2 with next steps.
        return _mirror_first(cfg, _live_backend(cfg, quiet=quiet), quiet=quiet)
    live, reason = _try_live(cfg, quiet=quiet)
    if live is None:
        if not quiet:
            console.print(
                f"[yellow]{_manager_name(cfg)} is not reachable ({reason}). "
                f"Working from {catalogue.age_line()}. Nothing will be written to it.[/]"
            )
        return MirrorFirstBackend(cfg, catalogue, None)
    return _mirror_first(cfg, live, quiet=quiet)


def _no_write(backend: LibraryBackend) -> str:
    if getattr(backend, "live", backend) is None:
        return "The library is not reachable, so nothing can be written to it."
    return "This library has no write support."


def _flush(backend: LibraryBackend) -> None:
    behind = getattr(backend, "unrefreshed", None)
    err = Console(stderr=True, highlight=False)
    if behind:
        err.print(
            f"[yellow]{len(behind)} item(s) changed in the library but not yet in "
            f"the mirror. paperful snapshot brings them in.[/]"
        )
    fn = getattr(backend, "flush_writes", None)
    if not callable(fn):
        return
    path = fn()
    if path is None:
        return
    err.print(f"[green]EndNote import bundle[/] {path}")
    err.print(
        "[dim]In EndNote: File → Import → File → paperful.xml "
        "(import option: EndNote Generated XML).[/]"
    )


def _scope_error(exc: ScopeError) -> None:
    console.print(f"[red]{exc}[/]")
    raise typer.Exit(1) from exc


def _scope_keys(
    backend: LibraryBackend, collection: list[str], library: bool
) -> tuple[list[str] | None, str]:
    try:
        return resolve_keys(backend, collection, library)
    except ScopeError as exc:
        _scope_error(exc)


def _resolve_types(item_type: list[str]) -> frozenset[str] | None:
    try:
        return resolve_item_types(item_type)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)


def _apply_item_filters(
    items: list,
    scope: str,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    item_types: frozenset[str] | None = None,
    label: bool = True,
) -> tuple[list, str]:
    """Filter by year and/or item type; optionally append labels to scope."""
    try:
        return filter_scope_items(
            items,
            scope,
            year_from=year_from,
            year_to=year_to,
            item_types=item_types,
            annotate=label,
        )
    except ScopeError as exc:
        _scope_error(exc)


def _loaded_scope(
    backend: LibraryBackend,
    *,
    collection: list[str],
    library: bool,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    item_keys: list[str] | None = None,
    pdfs_only: bool = False,
    status: Callable[[str], None] | None = None,
):
    try:
        return load_scope(
            backend,
            item_keys=item_keys,
            collections=collection,
            library=library,
            year_from=year_from,
            year_to=year_to,
            item_types=_resolve_types(item_type),
            pdfs_only=pdfs_only,
            status=status,
        )
    except ScopeError as exc:
        _scope_error(exc)


@app.callback()
def _main(
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Do not contact the reference manager. Work from the mirror as it is.",
    ),
) -> None:
    """paperful."""
    global _OFFLINE
    _OFFLINE = offline


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
    """Optional stdio MCP: refs_gap (dry-run) and ask (index read-only). Prefer --format json."""
    from .mcp_server import serve_stdio

    serve_stdio(_cfg(config))


@app.command()
def version() -> None:
    console.print(__version__)


def _collect_doctor_checks(cfg: Config, *, probe: bool = False) -> list[Check]:
    try:
        return run_checks(cfg, ZoteroLocal(), probe=probe)
    except Exception:
        return run_checks(cfg, None, probe=probe)


def _print_doctor_table(checks: list[Check]) -> None:
    table = Table(title="paperful doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    colour = {"green": "green", "amber": "yellow", "red": "red"}
    for ch in checks:
        table.add_row(ch.name, f"[{colour[ch.status]}]{ch.status}[/]", ch.detail)
    console.print(table)


def _wait_doctor_continue() -> bool:
    """Wait for Enter. Return False if the user stops (EOF / interrupt)."""
    console.print("[dim]Press Enter when done (Ctrl-C to stop guide)…[/]")
    try:
        input()
        return True
    except EOFError:
        return False
    except KeyboardInterrupt:
        console.print("\n[dim]Guide stopped.[/]")
        return False


def _guide_doctor(
    cfg: Config, checks: list[Check], *, probe: bool = False
) -> list[Check]:
    """Walk amber/red remediations interactively; re-check after each step."""
    docker = in_docker()
    pending = actionable_checks(checks, cfg, docker=docker)
    if not pending:
        return checks

    console.print(
        "\n[bold]Guide[/] — fix the checks below one at a time. "
        "Sessions need a headed browser"
        + (" on the host" if docker else "")
        + "; this process only re-checks.\n"
    )
    for check, _text in pending:
        name = check.name
        checks = _collect_doctor_checks(cfg, probe=probe)
        current = next((c for c in checks if c.name == name), None)
        if current is None or current.status == "green":
            if current is not None:
                console.print(f"[green]✓ {name}[/] already green — skipping.")
            continue
        text = remediation_text(current, cfg, docker=docker)
        if not text:
            continue
        colour = "red" if current.status == "red" else "yellow"
        console.print(f"\n[{colour}]• {current.name}[/] ({current.status})")
        console.print(f"[dim]{current.detail}[/]")
        console.print(text)
        if not _wait_doctor_continue():
            break
        # Reload config so email / path edits are picked up mid-guide.
        cfg = _cfg(cfg.config_path)
        checks = _collect_doctor_checks(cfg, probe=probe)
        updated = next((c for c in checks if c.name == name), None)
        if updated is None:
            continue
        if updated.status == "green":
            console.print(f"[green]✓ {name} is green[/]")
        else:
            console.print(f"[yellow]Still {updated.status}:[/] {updated.detail}")

    console.print()
    _print_doctor_table(checks)
    return checks


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
    cfg = _cfg(config)
    checks = _collect_doctor_checks(cfg, probe=probe)
    if as_json:
        payload = [
            {
                "name": c.name,
                "status": c.status,
                "code": c.code,
                "detail": c.detail,
            }
            for c in checks
        ]
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        if has_red(checks):
            raise typer.Exit(2)
        return
    _print_doctor_table(checks)

    actionable = actionable_checks(checks, cfg)
    if guide is None:
        # Compose/Docker often reports isatty() False even with a real terminal.
        want_guide = sys.stdin.isatty() or in_docker()
    else:
        want_guide = guide
    if want_guide and actionable:
        checks = _guide_doctor(cfg, checks, probe=probe)
    elif actionable and not want_guide:
        console.print(
            "\n[dim]Amber/red fixes available — re-run with[/] "
            "[bold]paperful doctor --guide[/]"
            + (" [dim](or omit --no-guide / -T)[/]" if in_docker() else "")
        )

    if has_red(checks):
        code = next((c.code for c in checks if c.status == "red" and c.code), "")
        _print_exit_ladder(cfg, code=code, in_doctor=True)
        raise typer.Exit(2)


def _print_collections_table(cfg: Config, backend: LibraryBackend) -> None:
    with _spinner("Counting collections…"):
        cols = backend.collections()
        counts = backend.collection_counts()
    table = Table(title=f"{cfg.manager} collections (counts include subcollections)")
    table.add_column("Path")
    table.add_column("Items", justify="right")
    table.add_column("No PDF", justify="right")
    table.add_column("Key", style="dim")
    for c in sorted(cols.values(), key=lambda c: c.path.lower()):
        n, missing = counts.get(c.key, (0, 0))
        depth = c.path.count("/")
        table.add_row(("  " * depth) + c.name, str(n), str(missing), c.key)
    console.print(table)


@collections_app.callback(invoke_without_command=True)
def collections_root(
    ctx: typer.Context,
    config: Path | None = ConfigOpt,
) -> None:
    """Show the collection tree with item counts and how many lack a PDF."""
    if ctx.invoked_subcommand is not None:
        return
    cfg = _cfg(config)
    _require_manager(cfg)
    backend = _connect(cfg)
    _print_collections_table(cfg, backend)


@collections_app.command("list")
def collections_list(config: Path | None = ConfigOpt) -> None:
    """Show the collection tree with item counts and how many lack a PDF."""
    cfg = _cfg(config)
    _require_manager(cfg)
    backend = _connect(cfg)
    _print_collections_table(cfg, backend)


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
    from dataclasses import asdict as _asdict

    from .agent_json import envelope
    from .agent_ops import collections_add_exit
    from .collections_add import apply_adds, classify_rows, keys_from_file, write_summary

    if apply and dry_run:
        console.print("[red]Pass either --dry-run or --apply, not both.[/]")
        raise typer.Exit(1)
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    bound = _bind_run(cfg, profile=profile, run_config=run_config, collection=collection)
    collection, _library, _yf, _yt, _types = _take_scope(bound)
    if not collection:
        _refuse_missing_scope()
    keys = keys_from_file(keys_file)
    if not keys:
        console.print("No keys to add.")
        raise typer.Exit(0)
    backend = _connect(cfg, quiet=json_out)
    try:
        target = backend.resolve_collection(collection[0])
    except LookupError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    batch = classify_rows(
        keys,
        backend,
        collection_key=target.key,
        collection_path=target.path,
    )
    if apply:
        _require_manager(cfg)
        if not backend.supports_write():
            _exit_env("collections add --apply needs library write support.", cfg)
        apply_adds(backend, batch, target.key)
        _flush(backend)
    folder = write_summary(cfg.state_dir, target.path, batch)
    counts = batch.counts()
    payload = envelope(
        command="collections add",
        summary=counts,
        items=[_asdict(row) for row in batch.rows],
        paths={"summary": str(folder)},
        flags={"apply": apply, "dry_run": not apply},
        exit_code=collections_add_exit(
            apply=apply, added=int(counts["added"]), failed=int(counts["failed"])
        ),
    )

    def _human_add() -> None:
        table = Table(title="collections add")
        table.add_column("Key")
        table.add_column("Status")
        table.add_column("Title")
        table.add_column("Detail")
        for row in batch.rows:
            table.add_row(row.key, row.status, (row.title or "")[:50], row.detail)
        console.print(table)
        pending = int(counts["add"])
        console.print(
            f"added {counts['added']} · already-in {counts['already_in']} · "
            f"not-found {counts['not_found']}"
            + (f" · would-add {pending}" if not apply else "")
            + (f" · failed {counts['failed']}" if counts["failed"] else "")
            + (" (dry-run)" if not apply else "")
        )
        console.print(f"Summary: {folder}")

    _emit_agent(payload, json_out=json_out, human=_human_add)


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
    from rich.markup import escape

    from .lint import Finding, lint_items
    from .pipeline import make_client
    from .zot import Item

    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
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
        limit=limit,
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    limit = bound.limit
    if not collection and not library:
        _refuse_missing_scope()
    _require_manager(cfg)
    quiet = as_json or json_out
    backend = _connect(cfg, quiet=quiet)
    manifest = Manifest(cfg.manifest_path)
    partial: list[Finding] = []
    done = 0
    interrupted = False
    loaded = _load_scope(
        backend,
        json_out=quiet,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    if limit:
        items = items[:limit]
    if not quiet:
        console.print(f"Scope: [bold]{scope}[/] — linting {len(items)} items")
    with _item_progress(json_out=quiet) as progress:
        lint_id = progress.add_task("Linting", total=len(items))

        def _describe(current: str = "") -> str:
            n = len(partial)
            text = f"Linting [dim]· {n} finding{'' if n == 1 else 's'}"
            if current:
                text += f" · {escape(current)}"
            return text + "[/]"

        def _lint_start(item: Item) -> None:
            progress.update(lint_id, description=_describe(item.label[:48]))

        def _lint_done(item: Item, found: list[Finding]) -> None:
            nonlocal done
            done += 1
            partial.extend(found)
            progress.update(lint_id, advance=1, description=_describe())

        started = time.time()
        try:
            findings = lint_items(
                make_client(cfg),
                cfg,
                items,
                backend=backend,
                manifest=manifest,
                on_start=_lint_start,
                on_item=_lint_done,
            )
            partial[:] = findings
            progress.update(lint_id, completed=len(items), description=_describe())
        except KeyboardInterrupt:
            interrupted = True
            findings = partial
    if interrupted:
        progress.console.print(
            f"\n[yellow]Interrupted after {done}/{len(items)} items.[/] "
            "Findings so far:"
        )
    by_code: dict[str, int] = {}
    for finding in findings:
        by_code[finding.code] = by_code.get(finding.code, 0) + 1
    write_command_report(
        cfg,
        command="lint",
        scope=scope,
        summary={"findings": len(findings), "findings_by_code": by_code},
        items=[
            {
                "itemKey": finding.itemKey,
                "title": finding.title,
                "status": finding.code,
                "reason": finding.detail,
            }
            for finding in findings
        ],
        flags={"strict": strict, "interrupted": interrupted},
        started=started,
    )
    from .agent_json import envelope

    payload = envelope(
        command="lint",
        summary={"findings": len(findings), "findings_by_code": by_code},
        items=[
            {
                "itemKey": finding.itemKey,
                "title": finding.title,
                "status": finding.code,
                "reason": finding.detail,
            }
            for finding in findings
        ],
        flags={"strict": strict, "interrupted": interrupted},
        exit_code=130 if interrupted else (1 if strict and findings else 0),
    )

    def _human_lint() -> None:
        if not findings:
            console.print("[green]No findings.[/]")
            return
        table = Table(title=f"{len(findings)} findings")
        table.add_column("Code")
        table.add_column("Key", style="dim")
        table.add_column("Title")
        table.add_column("Detail")
        for f in findings:
            table.add_row(f.code, f.itemKey, f.title[:50], f.detail[:80])
        console.print(table)

    if json_out:
        _emit_agent(payload, json_out=True, human=_human_lint)
        return
    if as_json:
        console.print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        _human_lint()
    if interrupted:
        raise typer.Exit(130)
    if strict and findings:
        raise typer.Exit(1)


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
    from .agent_json import envelope
    from .authors_report import (
        harvest,
        scope_slug,
        seed_proposed_pack,
        write_report,
    )
    from .snowball.authors import pack_slug

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
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    if not collection and not library:
        _refuse_missing_scope()
    backend = _connect(cfg, quiet=json_out)
    loaded = _load_scope(
        backend,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        json_out=json_out,
    )
    report = harvest(loaded.items, min_count=min_count)
    slug = scope_slug(collection, library=library or not collection)
    pack_collection = (
        collection[0]
        if collection
        else (loaded.label if library or not collection else "library")
    )
    report_file: Path | None = None
    pack_file: Path | None = None
    if apply:
        report_file = write_report(
            cfg,
            slug,
            scope=loaded.label,
            report=report,
            min_count=min_count,
            n_items=len(loaded.items),
        )
        pack_file = seed_proposed_pack(
            cfg,
            collection=pack_collection,
            authors=report.authors,
            max_authors=max_authors,
        )

    def _human() -> None:
        console.print(
            f"Scope: [bold]{loaded.label}[/] — {len(loaded.items)} items, "
            f"{len(report.authors)} author{'s' if len(report.authors) != 1 else ''}, "
            f"{len(report.orgs)} org{'s' if len(report.orgs) != 1 else ''}"
        )
        if report.authors:
            table = Table(title="Authors")
            table.add_column("Name")
            table.add_column("Fingerprint")
            table.add_column("Items", justify="right")
            for row in report.authors:
                table.add_row(row.name, row.key, str(row.count))
            console.print(table)
        else:
            console.print("[green]No authors at this count.[/]")
        if report.orgs:
            table = Table(title="Orgs")
            table.add_column("Name")
            table.add_column("Items", justify="right")
            for row in report.orgs:
                table.add_row(row.name, str(row.count))
            console.print(table)
        else:
            console.print("[green]No orgs at this count.[/]")
        if not apply:
            console.print(
                "[dim]Dry-run. Pass --apply to write the report and proposed pack.[/]"
            )
            return
        if report_file is not None:
            console.print(f"Wrote report [bold]{report_file}[/]")
        if pack_file is not None:
            console.print(f"Proposed pack [bold]{pack_file}[/]")
            console.print(
                f"Next: paperful twenty lookup -C {pack_collection} --apply"
            )
            console.print(
                f"Next: paperful snowball packs promote {pack_slug(pack_collection)}"
            )
        elif report.authors:
            console.print("[dim]No pack seeded (empty top list).[/]")
        else:
            console.print("[dim]No authors to seed into a pack.[/]")

    agent_items = [
        {
            "kind": row.kind,
            "name": row.name,
            "key": row.key,
            "frequency": row.count,
        }
        for row in [*report.authors, *report.orgs]
    ]
    payload = envelope(
        command="authors",
        summary={
            "items": len(loaded.items),
            "authors": len(report.authors),
            "orgs": len(report.orgs),
            "min_count": min_count,
            "max_authors": max_authors,
        },
        items=agent_items,
        paths={
            "report": str(report_file) if report_file else "",
            "pack": str(pack_file) if pack_file else "",
        },
        flags={
            "apply": apply,
            "dry_run": not apply,
            "min_count": min_count,
            "max_authors": max_authors,
        },
    )
    _emit_agent(payload, json_out=json_out, human=_human)


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
    from .metadata import apply_patches, collect_patches, write_patches
    from .pipeline import make_client

    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    bound = _bind_run(
        cfg,
        use_apply=True,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        apply=apply,
        overwrite=overwrite,
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    limit = bound.limit
    apply = bound.apply
    overwrite = bound.overwrite
    if not collection and not library:
        _refuse_missing_scope()
    _require_manager(cfg)
    backend = _connect(cfg, quiet=json_out)
    manifest = Manifest(cfg.manifest_path)
    client = make_client(cfg)
    loaded = _load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    if limit:
        items = items[:limit]
    started = time.time()
    with _item_progress(json_out=json_out) as progress:
        patches = collect_patches(
            client,
            cfg,
            items,
            backend=backend,
            manifest=manifest,
            overwrite=overwrite,
            track=_track(progress, "Checking metadata"),
        )
    write_patches(cfg.patches_path, patches)
    field_counts: dict[str, int] = {}
    for p in patches:
        for key in p.after:
            field_counts[key] = field_counts.get(key, 0) + 1
    applied_n: int | None = None
    errors: list[str] = []
    if apply:
        if not backend.supports_write():
            _exit_env(_no_write(backend), cfg)
        try:
            with _item_progress(json_out=json_out) as progress:
                applied_n, errors = apply_patches(
                    backend, patches, track=_track(progress, "Applying patches")
                )
        except LibraryError as exc:
            _exit_env(str(exc), cfg)
        _flush(backend)
    _write_fix_report(
        cfg,
        scope,
        patches,
        field_counts,
        applied=applied_n,
        errors=errors,
        apply=bool(apply),
        started=started,
    )
    from .agent_json import batch_exit, envelope

    code = 0
    if apply:
        code = batch_exit(ok=int(applied_n or 0), failed=len(errors))
    payload = envelope(
        command="fix-metadata",
        summary={
            "patches_proposed": len(patches),
            "fields_corrected_by_kind": field_counts,
            **({"patches_applied": applied_n} if applied_n is not None else {}),
            "errors": len(errors),
        },
        items=[
            {
                "itemKey": p.itemKey,
                "title": p.title,
                "status": "patched",
                "after": p.after,
            }
            for p in patches
        ],
        paths={"patches": str(cfg.patches_path)},
        flags={"apply": bool(apply), "overwrite": bool(overwrite)},
        exit_code=code,
    )

    def _human_fix() -> None:
        console.print(f"Scope: [bold]{scope}[/] — {len(patches)} proposed patches")
        if patches:
            table = Table(title="Proposed patches")
            table.add_column("Key", style="dim")
            table.add_column("Title")
            table.add_column("After")
            for p in patches:
                table.add_row(
                    p.itemKey,
                    p.title[:40],
                    ", ".join(f"{k}={v}" for k, v in p.after.items())[:80],
                )
            console.print(table)
        console.print(f"[dim]Wrote {len(patches)} lines to {cfg.patches_path}[/]")
        _print_fix_summary(len(patches), field_counts, applied=applied_n, errors=errors)
        if not apply:
            console.print(
                "Dry-run. Pass [bold]--apply[/] to write these fields into the library."
            )

    _emit_agent(payload, json_out=json_out, human=_human_fix)


def _print_fix_summary(
    proposed: int,
    field_counts: dict[str, int],
    *,
    applied: int | None,
    errors: list[str],
) -> None:
    kinds = ", ".join(f"{k}={v}" for k, v in sorted(field_counts.items())) or "none"
    console.print("\n[bold]Fix-metadata summary[/]")
    console.print(f"Fields corrected (proposed): {proposed} patches  ({kinds})")
    if applied is not None:
        console.print(f"Applied: {applied}/{proposed}")
    if errors:
        console.print(f"Errors: {len(errors)}")
        for err in errors[:20]:
            console.print(f"[yellow]{err}[/]")
        if len(errors) > 20:
            console.print(f"[dim]… and {len(errors) - 20} more[/]")


def _write_fix_report(
    cfg: Config,
    scope: str,
    patches: list,
    field_counts: dict[str, int],
    *,
    applied: int | None,
    errors: list[str],
    apply: bool,
    started: float | None = None,
) -> None:
    summary: dict = {
        "fields_corrected": sum(field_counts.values()),
        "fields_corrected_by_kind": field_counts,
        "patches_proposed": len(patches),
        "errors_by_type": {"apply_failed": len(errors)} if errors else {},
        "pdfs_downloaded": 0,
        "sources_checked": {},
    }
    if applied is not None:
        summary["patches_applied"] = applied
    write_command_report(
        cfg,
        command="fix-metadata",
        scope=scope,
        summary=summary,
        items=[
            {
                "itemKey": p.itemKey,
                "title": p.title,
                "status": "patched",
                "fields_corrected": list(p.after.keys()),
                "after": p.after,
                "before": p.before,
            }
            for p in patches
        ],
        flags={"apply": apply},
        started=started,
        errors=errors,
        extra_paths={"patches": str(cfg.patches_path)},
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
    from .dedupe import (
        PHASES,
        apply_merge,
        attach_merge_previews,
        classify,
        merge_apply_total,
        merge_preview_total,
        pack_counts,
        write_pack,
    )

    phase_name = phase.strip().lower()
    if phase_name not in PHASES:
        console.print(f"[red]Unknown phase '{phase}'.[/] Known: {', '.join(PHASES)}")
        raise typer.Exit(1)
    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
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
    quiet = as_json or json_out
    backend = _connect(cfg, quiet=quiet)
    items: list
    scope: str
    groups: list
    if quiet:
        loaded = _loaded_scope(
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
        try:
            groups = classify(items, phase_name)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1)
        attach_merge_previews(backend, groups)
    else:
        with _item_progress() as progress:
            load_id = progress.add_task("Connecting to Zotero scope…", total=None)

            def _load_status(msg: str) -> None:
                progress.update(load_id, description=msg)

            loaded = _loaded_scope(
                backend,
                collection=collection,
                library=library,
                year_from=year_from,
                year_to=year_to,
                item_type=item_type,
                status=_load_status,
            )
            items, scope = loaded.items, loaded.label
            if limit:
                items = items[:limit]
            progress.update(
                load_id,
                description=f"Scope: {scope} — {len(items)} items",
                total=1,
                completed=1,
            )
            class_id = progress.add_task("Classifying duplicates…", total=1)
            try:
                groups = classify(items, phase_name)
            except ValueError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1)
            progress.advance(class_id)
            preview_n = merge_preview_total(groups)
            preview_id = progress.add_task(
                "Previewing merges…", total=preview_n or 1
            )

            def _preview_status(keep: str, drop: str) -> None:
                progress.update(
                    preview_id, description=f"Preview merge {drop} → keep {keep}"
                )

            def _preview_advance() -> None:
                progress.advance(preview_id)

            attach_merge_previews(
                backend,
                groups,
                on_preview=_preview_status if preview_n else None,
                on_advance=_preview_advance if preview_n else None,
            )
            if not preview_n:
                progress.advance(preview_id)
            progress.update(
                preview_id,
                description=f"Found {len(groups)} duplicate group(s)",
                completed=preview_n or 1,
            )
    json_path, md_path = write_pack(
        cfg.state_dir, scope, groups, phase=phase_name, n_items=len(items)
    )
    counts = pack_counts(groups, len(items))
    applied = 0
    errors: list[str] = []
    if apply:
        if not backend.supports_write():
            _exit_env(_no_write(backend), cfg)
        from .remarks import remark_duplicates

        remark_duplicates(backend, groups, items, surface=cfg.remarks_surface)
        merge_n = merge_apply_total(groups, apply_medium=apply_medium)
        try:
            if quiet:
                applied, errors = apply_merge(
                    backend,
                    groups,
                    apply_medium=apply_medium,
                    audit_path=cfg.dedupe_applied_path,
                    scope=scope,
                    pack=json_path,
                )
            else:
                with _item_progress() as progress:
                    merge_id = progress.add_task("Merging duplicates…", total=merge_n or 1)

                    def _merge_status(keep: str, drop: str, phase: str) -> None:
                        progress.update(
                            merge_id,
                            description=f"[{phase}] merge {drop} → keep {keep}",
                        )

                    def _merge_advance() -> None:
                        progress.advance(merge_id)

                    applied, errors = apply_merge(
                        backend,
                        groups,
                        apply_medium=apply_medium,
                        audit_path=cfg.dedupe_applied_path,
                        scope=scope,
                        pack=json_path,
                        on_merge=_merge_status if merge_n else None,
                        on_advance=_merge_advance if merge_n else None,
                    )
                    if not merge_n:
                        progress.advance(merge_id)
        except LibraryError as exc:
            _exit_env(str(exc))
    payload = {
        "pack": str(json_path),
        "markdown": str(md_path),
        "counts": counts,
        "applied": applied,
        "errors": errors,
    }
    from .agent_json import batch_exit, envelope

    code = batch_exit(ok=applied, failed=len(errors)) if apply else 0
    agent = envelope(
        command="dedupe",
        summary={
            **counts,
            "applied": applied,
            "errors": len(errors),
        },
        paths={"pack": str(json_path), "markdown": str(md_path)},
        flags={"apply": bool(apply), "apply_medium": apply_medium, "phase": phase_name},
        exit_code=code,
    )

    def _human_dedupe() -> None:
        console.print(f"Scope: [bold]{scope}[/] — {len(items)} items")
        _print_dedupe_table(groups)
        console.print(f"[dim]Wrote {json_path}[/]")
        console.print(f"[dim]Wrote {md_path}[/]")
        if apply:
            console.print(f"Merged: {applied}")
            if apply_medium:
                console.print("[dim]Included medium_title_year groups.[/]")
            elif any(g.phase == "medium_title_year" and g.trash for g in groups):
                console.print(
                    "Title+year groups were not merged. Pass [bold]--apply-medium[/] to include them."
                )
        else:
            console.print(
                "Dry-run. Pass [bold]--apply[/] to merge high_doi extras onto the keeper "
                "(title+year needs [bold]--apply-medium[/])."
            )
        if errors:
            console.print(f"Errors: {len(errors)}")
            for err in errors[:20]:
                console.print(f"[yellow]{err}[/]")

    if json_out:
        _emit_agent(agent, json_out=True, human=_human_dedupe)
        return
    if as_json:
        console.print(
            json.dumps(payload, indent=2), soft_wrap=True, highlight=False, markup=False
        )
        if errors:
            raise typer.Exit(1)
        return
    _human_dedupe()
    if errors:
        raise typer.Exit(1)


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
    from .attachments import (
        SurgeryFlags,
        apply_actions,
        apply_refusal,
        mirror_pdfs_for,
        pdf_children,
        plan_actions,
        stem_filename,
        summarize,
    )

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
    if dry_run and apply:
        console.print("[red]Pass either --dry-run or --apply, not both.[/]")
        raise typer.Exit(1)
    if not collection and not library:
        _refuse_missing_scope()
    flags = SurgeryFlags(
        fix_broken=_opt_bool(fix_broken, cfg.attachments_fix_broken),
        merge_files=_opt_bool(merge_files, cfg.attachments_merge_files),
        rename=_opt_bool(rename, cfg.attachments_rename),
        link=_opt_bool(link, cfg.attachments_link),
    )
    _require_manager(cfg)
    backend = _live_backend(cfg, quiet=as_json)
    loaded = _load_scope(
        backend,
        json_out=as_json,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    if limit:
        items = items[:limit]
    started = time.time()
    children = []
    mirrors: dict = {}
    stems: dict = {}
    unread: list[str] = []
    with _item_progress(json_out=as_json) as progress:
        for item in _track(progress, "Scanning attachments")(items):
            try:
                raw = backend.children(item.key) or []
            except LibraryError:
                # Not the same as an item with no attachments. Leave it out.
                unread.append(item.key)
                continue
            present = {
                str(ch.get("key") or (ch.get("data") or {}).get("key") or ""): _child_bytes(
                    backend, ch
                )
                for ch in raw
                if isinstance(ch, dict)
            }
            kids = pdf_children(item.key, raw, present=present)
            children.extend(kids)
            mirrors[item.key] = mirror_pdfs_for(cfg.out_dir, item)
            stems[item.key] = stem_filename(item)
    scan = plan_actions(
        children,
        mirrors,
        stems,
        flags,
        out_dir=cfg.out_dir,
        library_type=str(getattr(backend, "library_type", "user")),
    )
    applied = 0
    errors: list[str] = list(scan.refusals)
    if unread:
        errors.append(f"{len(unread)} item(s) could not be read and were skipped")
    if apply and flags.any:
        refusal = apply_refusal(
            manager=cfg.manager,
            library_type=str(getattr(backend, "library_type", "user")),
            link=flags.link,
        )
        if refusal:
            errors.append(refusal)
        elif not backend.supports_write():
            _exit_env(_no_write(backend), cfg)
        else:
            try:
                with _item_progress(json_out=as_json) as progress:
                    applied, apply_errors = apply_actions(
                        backend,
                        scan.actions,
                        out_dir=cfg.out_dir,
                        track=_track(progress, "Applying changes"),
                    )
            except LibraryError as exc:
                _exit_env(str(exc))
            errors.extend(apply_errors)
    counts = summarize(scan.findings)
    report_items = [
        {
            "kind": f.kind,
            "parent": f.parent_key,
            "attachment": f.attachment_key,
            "detail": f.detail,
            "md5": f.md5,
        }
        for f in scan.findings
        if f.kind != "ok"
    ]
    write_command_report(
        cfg,
        command="attachments",
        scope=scope,
        summary={
            "items": len(items),
            "findings": counts,
            "actions": len(scan.actions) if apply and flags.any else 0,
            "applied": applied,
        },
        items=report_items,
        flags={
            "apply": apply,
            "dry_run": dry_run or not apply,
            "fix_broken": flags.fix_broken,
            "merge_files": flags.merge_files,
            "rename": flags.rename,
            "link": flags.link,
        },
        started=started,
        errors=errors,
    )
    payload = {
        "scope": scope,
        "items": len(items),
        "findings": counts,
        "actions": [
            {"op": a.op, "parent": a.parent_key, "attachment": a.attachment_key}
            for a in scan.actions
        ],
        "applied": applied,
        "errors": errors,
    }
    if as_json:
        console.print(
            json.dumps(payload, indent=2), soft_wrap=True, highlight=False, markup=False
        )
    else:
        console.print(f"Scope: [bold]{scope}[/] — {len(items)} items")
        _print_attachment_table(counts)
        if apply and flags.any and not errors:
            console.print(f"Applied: {applied}")
        elif flags.any and not apply:
            console.print(
                f"Would apply {len(scan.actions)} change(s). Pass [bold]--apply[/] to write them."
            )
        else:
            console.print(
                "Report only. Pass [bold]--fix-broken[/], [bold]--merge-files[/], "
                "[bold]--rename[/], or [bold]--link[/] with [bold]--apply[/] to change Zotero."
            )
        if errors:
            console.print(f"Errors: {len(errors)}")
            for err in errors[:20]:
                console.print(f"[yellow]{err}[/]")
    if errors and apply:
        raise typer.Exit(1)


def _opt_bool(flag: bool | None, configured: bool) -> bool:
    return configured if flag is None else flag


def _child_bytes(backend: Any, child: dict[str, Any]) -> bool:
    data = child.get("data") or {}
    key = str(child.get("key") or data.get("key") or "")
    if data.get("linkMode") == "linked_file":
        path = data.get("path")
        return bool(path) and Path(str(path)).is_file()
    probe = getattr(backend, "attachment_has_bytes", None)
    if probe is None or not key:
        return True
    try:
        return bool(probe(key))
    except Exception:
        return False


def _print_attachment_table(counts: dict[str, int]) -> None:
    table = Table(title="Attachments")
    table.add_column("Finding")
    table.add_column("Count", justify="right")
    order = (
        "ok",
        "ghost",
        "broken_link",
        "unrepairable",
        "duplicate_file",
        "cross_parent",
        "rename_drift",
        "stored",
    )
    shown = set()
    for kind in order:
        if kind in counts:
            table.add_row(kind, str(counts[kind]))
            shown.add(kind)
    for kind, count in sorted(counts.items()):
        if kind not in shown:
            table.add_row(kind, str(count))
    console.print(table)


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
    matches are listed and not applied.
    """
    import httpx

    from .versions import (
        apply_versions,
        classify_versions,
        http_fetch_published,
        pack_counts,
        resolver_for,
        write_pack,
    )

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
    backend = _connect(cfg, quiet=as_json)
    loaded = _load_scope(
        backend,
        json_out=as_json,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    if limit:
        items = items[:limit]
    client = httpx.Client(follow_redirects=True, timeout=30)
    errors: list[str] = []
    try:
        try:
            with _item_progress(json_out=as_json) as progress:
                proposals = classify_versions(
                    items,
                    resolver_for(client, cfg.email),
                    track=_track(progress, "Checking versions"),
                )
        except Exception as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1)
        json_path, md_path = write_pack(
            cfg.state_dir, scope, proposals, n_items=len(items)
        )
        counts = pack_counts(proposals, len(items))
        applied = 0
        if apply:
            if not backend.supports_write():
                _exit_env(_no_write(backend), cfg)
            try:
                with _item_progress(json_out=as_json) as progress:
                    applied, errors = apply_versions(
                        backend,
                        proposals,
                        fetch_published=http_fetch_published(client, cfg.email),
                        audit_path=cfg.versions_applied_path,
                        scope=scope,
                        pack=json_path,
                        track=_track(progress, "Linking versions"),
                    )
            except LibraryError as exc:
                _exit_env(str(exc))
        payload = {
            "pack": str(json_path),
            "markdown": str(md_path),
            "counts": counts,
            "applied": applied,
            "errors": errors,
        }
        if as_json:
            console.print(
                json.dumps(payload, indent=2),
                soft_wrap=True,
                highlight=False,
                markup=False,
            )
        else:
            console.print(f"Scope: [bold]{scope}[/] — {len(items)} items")
            _print_version_table(proposals)
            console.print(f"[dim]Wrote {json_path}[/]")
            console.print(f"[dim]Wrote {md_path}[/]")
            if apply:
                console.print(f"Updated: {applied}")
            else:
                console.print(
                    "Dry-run. Pass [bold]--apply[/] to keep the published citation and PDF "
                    "on the existing item. The preprint stays as a version."
                )
            if errors:
                console.print(f"Errors: {len(errors)}")
                for err in errors[:20]:
                    console.print(f"[yellow]{err}[/]")
    finally:
        client.close()
    if errors:
        raise typer.Exit(1)


def _print_version_table(proposals: list) -> None:
    if not proposals:
        console.print("[green]No preprint / published pairs.[/]")
        return
    table = Table(title=f"{len(proposals)} version pairs")
    table.add_column("Keep", style="dim")
    table.add_column("Published DOI")
    table.add_column("Sibling")
    table.add_column("Note")
    for row in proposals:
        note = "needs review" if row.needs_review else row.source
        table.add_row(
            row.item_key,
            row.published_doi,
            row.sibling_key or "-",
            note,
        )
    console.print(table)


def _print_dedupe_table(groups: list) -> None:
    if not groups:
        console.print("[green]No duplicate groups.[/]")
        return
    table = Table(title=f"{len(groups)} duplicate groups")
    table.add_column("Phase")
    table.add_column("Keep", style="dim")
    table.add_column("Merge")
    table.add_column("Note")
    for group in groups:
        if group.held:
            note = group.reason
            keep = "-"
            trash = "-"
        else:
            note = "needs review" if group.needs_review else group.reason
            keep = group.keep or "-"
            trash = ", ".join(group.trash)
        table.add_row(group.phase, keep, trash, note)
    console.print(table)


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
    from .dedupe import summarize_gaps
    from .handoff import (
        list_missing_pdfs,
        open_tabs,
        parse_handoff,
        walk_missing,
        write_missing_export,
    )

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
    items, scope = loaded.items, loaded.label
    started = time.time()
    counts = summarize_gaps(items)
    payload = {
        "scope": scope,
        "items": counts.items,
        "no_stored_pdf": counts.no_stored_pdf,
        "linked_url_only": counts.linked_url_only,
        "missing_doi": counts.missing_doi,
        "snapshot_only": counts.snapshot_only,
    }
    rows = []
    for it in items:
        codes: list[str] = []
        if not it.has_pdf:
            codes.append("no_stored_pdf")
        if it.has_linked_url and not it.has_pdf:
            codes.append("linked_url_only")
        if not it.doi:
            codes.append("missing_doi")
        if it.pdf_tier == "snapshot":
            codes.append("snapshot_only")
        if codes:
            rows.append(
                {"itemKey": it.key, "title": it.title, "status": ",".join(codes)}
            )
    write_command_report(
        cfg,
        command="gaps",
        scope=scope,
        summary={
            "items": counts.items,
            "no_stored_pdf": counts.no_stored_pdf,
            "linked_url_only": counts.linked_url_only,
            "missing_doi": counts.missing_doi,
            "snapshot_only": counts.snapshot_only,
            "handoff": mode if list_missing else "",
        },
        items=rows,
        started=started,
    )
    from .agent_json import envelope

    def _human_gaps_counts() -> None:
        console.print(f"Scope: [bold]{scope}[/]")
        table = Table(title="Gaps")
        table.add_column("Count", justify="right")
        table.add_column("Gap")
        table.add_column("Next")
        table.add_row(str(counts.items), "items in scope", "")
        table.add_row(
            str(counts.no_stored_pdf),
            "no stored PDF",
            "paperful run (or --upgrade-linked)",
        )
        table.add_row(
            str(counts.linked_url_only),
            "linked PDF URL only",
            "paperful run --upgrade-linked",
        )
        table.add_row(str(counts.missing_doi), "missing DOI", "paperful lint")
        table.add_row(
            str(counts.snapshot_only),
            "HTML snapshot only",
            "paperful run --upgrade-snapshot",
        )
        console.print(table)

    agent_payload = envelope(
        command="gaps",
        summary={
            "items": counts.items,
            "no_stored_pdf": counts.no_stored_pdf,
            "linked_url_only": counts.linked_url_only,
            "missing_doi": counts.missing_doi,
            "snapshot_only": counts.snapshot_only,
        },
        items=rows,
        flags={"list_missing": list_missing, "handoff": mode if list_missing else ""},
    )
    if json_out and not list_missing:
        _emit_agent(agent_payload, json_out=True, human=_human_gaps_counts)
        return
    if as_json and not list_missing:
        console.print(
            json.dumps(payload, indent=2), soft_wrap=True, highlight=False, markup=False
        )
        return
    if not as_json and not json_out:
        _human_gaps_counts()

    if not list_missing:
        return

    manifest = Manifest(cfg.manifest_path)
    missing = list_missing_pdfs(items, manifest, cfg=cfg, re_request=re_request)
    if to is not None:
        path = write_missing_export(missing, to)
        console.print(f"Wrote {len(missing)} rows to {path}")
    if as_json:
        console.print(
            json.dumps(
                {
                    **payload,
                    "missing": [
                        {
                            "itemKey": r.key,
                            "title": r.title,
                            "doi": r.doi,
                            "url": r.url,
                            "hint": r.hint,
                            "miss_surface": r.miss_surface,
                            "miss_plain": r.miss_plain,
                            "miss_detail": r.miss_detail,
                            "oa_status": r.oa_status,
                            "license": r.license,
                            "version": r.version,
                            "scholar_url": r.scholar_url,
                            "request_url": r.request_url,
                        }
                        for r in missing
                    ],
                },
                indent=2,
            ),
            soft_wrap=True,
            highlight=False,
            markup=False,
        )
        return
    if json_out:
        agent_payload["items"] = [
            {
                "itemKey": r.key,
                "title": r.title,
                "doi": r.doi,
                "url": r.url,
                "hint": r.hint,
                "miss_surface": r.miss_surface,
                "scholar_url": r.scholar_url,
                "request_url": r.request_url,
            }
            for r in missing
        ]
        agent_payload["summary"]["missing_pdfs"] = len(missing)
        _emit_agent(agent_payload, json_out=True, human=lambda: None)
        return
    else:
        t = Table(title=f"{len(missing)} missing PDFs")
        t.add_column("Key", style="dim")
        t.add_column("Title")
        t.add_column("DOI")
        t.add_column("URL")
        t.add_column("Scholar")
        t.add_column("Request")
        t.add_column("Hint")
        t.add_column("Miss")
        t.add_column("OA")
        for row in missing:
            t.add_row(
                row.key,
                row.title[:50],
                row.doi or "-",
                (row.url or "-")[:40],
                (row.scholar_url or "-")[:40],
                (row.request_url or "-")[:40],
                row.hint,
                row.miss_plain or row.miss_surface or "-",
                row.oa_status or "-",
            )
        console.print(t)

    if mode == "list":
        return
    if mode in {"tabs", "watch"}:

        def _confirm(n: int) -> bool:
            answer = (
                typer.prompt(f"Open {n} tabs in your browser?", default="y")
                .strip()
                .lower()
            )
            return answer in {"y", "yes"}

        opened = open_tabs(
            missing,
            include_doi_tabs=include_doi_tabs,
            confirm=_confirm,
            scholar=cfg.handoff_scholar,
            cfg=cfg,
        )
        console.print(f"Opened {opened} tab(s) in your browser.")
        if mode == "tabs" and not (
            cfg.inbox_watch_after_handoff and cfg.inbox_path is not None
        ):
            return
        if not backend.supports_write():
            console.print("[red]--handoff watch needs library write support.[/]")
            raise typer.Exit(1)
        _inbox_handoff_session(
            cfg,
            backend,
            manifest,
            items,
            missing,
            scope=scope,
            once=False,
        )
        return

    # walk
    if not backend.supports_write():
        console.print("[red]--handoff walk needs library write support.[/]")
        raise typer.Exit(1)
    dl = gaps_downloads_dir(cfg, downloads_dir)
    by_key = {it.key: it for it in items}
    walk_started = time.time()
    result = walk_missing(
        cfg,
        backend,
        manifest,
        by_key,
        missing,
        downloads_dir=dl,
        prompt=lambda msg: typer.prompt(msg, default=""),
        on_status=lambda msg: console.print(msg),
    )
    _flush(backend)
    _rag_auto(cfg, walk_started)
    console.print(
        f"Walk attached {result.attached}, skipped {result.skipped}"
        + (" (quit early)" if result.quit_early else "")
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
    from .author_request import apply_request_rg_override
    from .handoff import HINT_AUTHOR_REQUEST, list_missing_pdfs, open_tabs, parse_handoff, walk_missing
    from .reachout import build_reachout_rows, write_reachout_export
    from .store import Manifest
    from .twenty import twenty_ready

    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
    apply_request_rg_override(cfg, request_rg)
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
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    if not collection and not library:
        _refuse_missing_scope()
    try:
        mode = parse_handoff(handoff, default="list")
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if mode == "watch":
        console.print(
            "[red]reachout does not watch the inbox.[/] Use gaps --handoff watch."
        )
        raise typer.Exit(1)
    if lookup and not twenty_ready(cfg):
        console.print(
            "[yellow]--lookup ignored:[/] Twenty is off or TWENTY_API_KEY / base_url missing."
        )
    _require_manager(cfg)
    backend = _connect(cfg, quiet=json_out)
    loaded = _load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    started = time.time()
    manifest = Manifest(cfg.manifest_path)
    rows = build_reachout_rows(
        cfg,
        items,
        non_oa_only=non_oa_only,
        lookup=lookup and twenty_ready(cfg),
        re_request=re_request,
        manifest=manifest,
    )
    export_path = ""
    if to is not None:
        export_path = str(write_reachout_export(rows, to))
    with_email = sum(1 for r in rows if r.email)
    with_rg = sum(1 for r in rows if r.request_url)
    write_command_report(
        cfg,
        command="reachout",
        scope=scope,
        summary={
            "items": len(items),
            "rows": len(rows),
            "with_email": with_email,
            "with_rg": with_rg,
            "handoff": mode,
        },
        items=[{"itemKey": r.key, "status": r.email_source or "none"} for r in rows],
        started=started,
    )
    from .agent_json import envelope

    def _human() -> None:
        if export_path:
            console.print(f"Wrote {len(rows)} rows to {export_path}")
        table = Table(title=f"Reachout ({scope})")
        table.add_column("Key", style="dim")
        table.add_column("Author")
        table.add_column("Title")
        table.add_column("Email")
        table.add_column("Source")
        table.add_column("Request")
        table.add_column("Miss")
        for row in rows:
            table.add_row(
                row.key,
                (row.author or "-")[:24],
                (row.title or "-")[:40],
                row.email or "-",
                row.email_source or "-",
                (row.request_url or "-")[:36],
                row.miss_surface or "-",
            )
        console.print(table)
        console.print(
            f"{len(rows)} missing · {with_email} with email · {with_rg} ResearchGate. "
            "No fetch. Paperful does not send mail."
        )

    agent_payload = envelope(
        command="reachout",
        summary={
            "items": len(items),
            "rows": len(rows),
            "with_email": with_email,
            "with_rg": with_rg,
        },
        items=[r.as_dict() for r in rows],
        paths={"export": export_path} if export_path else None,
        flags={
            "non_oa_only": non_oa_only,
            "lookup": lookup,
            "handoff": mode,
        },
    )
    _emit_agent(agent_payload, json_out=json_out, human=_human)
    if mode == "list":
        return
    rg_rows = [
        m
        for m in list_missing_pdfs(items, manifest, cfg=cfg, re_request=re_request)
        if m.hint == HINT_AUTHOR_REQUEST and m.request_url
    ]
    if non_oa_only:
        keep = {r.key for r in rows}
        rg_rows = [m for m in rg_rows if m.key in keep]
    if not rg_rows:
        console.print("[dim]No ResearchGate publication URLs to open.[/]")
        return
    if mode == "tabs":

        def _confirm(n: int) -> bool:
            answer = (
                typer.prompt(f"Open {n} ResearchGate tabs?", default="y")
                .strip()
                .lower()
            )
            return answer in {"y", "yes"}

        opened = open_tabs(
            rg_rows,
            include_doi_tabs=False,
            confirm=_confirm,
            scholar=False,
            cfg=cfg,
        )
        console.print(f"Opened {opened} ResearchGate tab(s). You click Request.")
        return
    if not backend.supports_write():
        console.print("[red]--handoff walk needs library write support.[/]")
        raise typer.Exit(1)
    dl = gaps_downloads_dir(cfg, downloads_dir)
    by_key = {it.key: it for it in items}
    result = walk_missing(
        cfg,
        backend,
        manifest,
        by_key,
        rg_rows,
        downloads_dir=dl,
        prompt=lambda msg: typer.prompt(msg, default=""),
        on_status=lambda msg: console.print(msg),
    )
    _flush(backend)
    console.print(
        f"Walk attached {result.attached}, skipped {result.skipped}"
        + (" (quit early)" if result.quit_early else "")
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
    if not collection and not library:
        _refuse_missing_scope()
    _require_manager(cfg)
    source_list = _source_list(cfg, sources, scihub, preset)
    backend, offline_reason = _open_library(cfg, quiet=json_out)
    mirror_only = backend is None
    if mirror_only:
        manager = _manager_name(cfg)
        if not json_out:
            console.print(
                f"[yellow]{manager} is not reachable ({offline_reason}). "
                "Continuing from the local mirror. Nothing will be copied to the library.[/]"
            )
        catalog = items_from_mirror(cfg.out_dir, None if library else collection)
        scope = "library" if library else ", ".join(collection)
        keys = None
    else:
        keys, scope = _scope_keys(backend, collection, library)
    types = _resolve_types(item_type)
    # Drop sources that can never hit this -T / year scope (e.g. htmlpdf on
    # journals, Sci-Hub when --year-from is past its ~2021 coverage), including
    # under --try-all.
    source_list = filter_sources_for_item_types(
        source_list,
        types,
        academic_htmlpdf=cfg.htmlpdf_academic != "off",
    )
    source_list = filter_sources_for_year_scope(source_list, year_from)
    source_list = with_recover_lane(cfg, source_list, during_run=browser_agent)
    source_list = with_serpapi_lane(cfg, source_list)
    if not json_out:
        _warn_if_scihub(source_list)
        _warn_if_recover(source_list)

    manifest = Manifest(cfg.manifest_path)
    item_filter = year_from is not None or year_to is not None or types is not None
    # One library listing. Year and type filters, the linked-URL skip count,
    # and the PDF todo all come from that list.
    if not mirror_only:
        assert backend is not None
        with _spinner("Loading items from library…", json_out=json_out):
            catalog = backend.items_in_scope(keys)
    if item_filter:
        scoped, scope = _apply_item_filters(
            catalog,
            scope,
            year_from=year_from,
            year_to=year_to,
            item_types=types,
        )
        linked_skipped = 0 if upgrade_linked else linked_url_only_count(scoped)
    else:
        scoped = catalog
        linked_skipped = (
            0
            if upgrade_linked
            else linked_url_only_count(scoped, skip_empty_paths=keys is not None)
        )
    items = items_without_stored_pdf(
        scoped,
        upgrade_linked=upgrade_linked,
        upgrade_snapshot=want_snapshot_upgrade,
    )
    todo = [it for it in items if manifest.should_process(it.key, retry_failed)]
    skipped_manifest = len(items) - len(todo)
    if limit:
        todo = todo[:limit]
    linked_note = (
        f", {linked_skipped} linked URL only (skipped)" if linked_skipped else ""
    )
    if not json_out:
        console.print(
            f"Scope: [bold]{scope}[/] - {len(items)} items without PDF, {skipped_manifest} already handled, "
            f"{len(todo)} to process{linked_note}. Sources: {', '.join(source_list)}"
        )

    if dry_run:
        run_dry_run_table_and_payload(
            console,
            cfg,
            todo=todo,
            try_all=try_all,
            source_list=source_list,
            manifest=manifest,
            mirror_only=mirror_only,
            mirror_deferred=lambda: _mirror_deferred(cfg),
            json_out=json_out,
            emit_agent=_emit_agent,
        )
        raise typer.Exit(0)

    attacher = None
    if backend is not None and cfg.attach and not no_attach:
        attacher = backend
        if not backend.supports_write():
            console.print(
                "[yellow]Attach disabled: this library has no write support. PDFs still saved to disk.[/]"
            )
            attacher = None

    run_flags = _run_flags(
        dry_run=False,
        no_attach=no_attach,
        retry_failed=retry_failed,
        try_all=try_all,
        upgrade_linked=upgrade_linked,
        scihub=scihub,
        no_browser_agent=True if browser_agent is False else None,
        browser_agent=True if browser_agent is True else None,
        preset=preset,
        sources=sources,
        year_from=year_from,
        year_to=year_to,
        item_types=",".join(sorted(types)) if types else None,
        strict_pdf_doi=strict_pdf_doi,
        ezproxy_relogin=relogin,
    )
    write_api = None if mirror_only else _library_write_api(backend)

    if not todo:
        stats = RunStats(
            skipped_manifest=skipped_manifest, linked_url_skipped=linked_skipped
        )
        stats.scope = scope
        stats.sources_configured = list(source_list)
        stats.finished_at = stats.started_at
        _finish_run(
            cfg,
            stats,
            scope=scope,
            flags=run_flags,
            write_api=write_api,
            json_out=json_out,
        )
        if mirror_only:
            _mirror_deferred(cfg)
        return

    pipe = Pipeline(
        cfg,
        manifest,
        console,
        sources=source_list,
        attacher=attacher,
        try_all=True if try_all else None,
        strict_pdf_doi=bool(strict_pdf_doi),
    )
    pipe.on_ezproxy_down = mid_run_ezproxy_hook(console, cfg, pipe, enabled=relogin)
    preflight_ezproxy_session(console, cfg, pipe, source_list, enabled=relogin)
    interrupted = False
    with _item_progress() as progress:
        task_id = progress.add_task("Fetching PDFs", total=len(todo))
        pipe.progress = lambda: progress.advance(task_id)
        pipe.live_progress = progress
        try:
            stats = pipe.run(todo)
        except KeyboardInterrupt:
            interrupted = True
            console.print(
                "\n[yellow]Interrupted - progress is in the manifest; rerun to resume.[/]"
            )
            stats = pipe.stats
            if not stats.finished_at:
                stats.finished_at = time.time()
        stats = pipe.stats
        pipe.live_progress = None
    # Fetch bar is done and pipe.run has closed the vault browser. Re-login
    # happens here, still before the report and before --handoff opens tabs.
    if not interrupted:
        try:
            maybe_ezproxy_relogin(console, cfg, pipe, todo, enabled=relogin)
        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Interrupted during EZProxy re-login - "
                "progress is in the manifest.[/]"
            )
            if not pipe.stats.finished_at:
                pipe.stats.finished_at = time.time()
        stats = pipe.stats
    stats.skipped_manifest = skipped_manifest
    stats.linked_url_skipped = linked_skipped
    stats.scope = scope
    _finish_run(
        cfg,
        stats,
        scope=scope,
        flags=run_flags,
        write_api=write_api,
        json_out=json_out,
    )
    if backend is not None:
        _flush(backend)
    if mirror_only:
        _mirror_deferred(cfg)
    if not dry_run and not interrupted:
        _rag_auto(cfg, stats.started_at)
    if handoff and not dry_run:
        # Tabs use the default browser. Release the vault profile first so
        # those tabs do not land in the EZProxy login window.
        if pipe.browser is not None:
            pipe.browser.close()
        _run_session_handoff(
            cfg,
            backend,
            manifest,
            catalog,
            stats,
            handoff=handoff,
            include_doi_tabs=include_doi_tabs,
            downloads_dir=downloads_dir,
            re_request=re_request,
        )


def _ezproxy_headed_login_and_probe(cfg: Config, pipe: Pipeline) -> bool:
    return ezproxy_headed_login_and_probe(console, cfg, pipe)


def _ensure_ezproxy_session(
    cfg: Config,
    pipe: Pipeline,
    *,
    enabled: bool,
    prompt: str,
) -> bool:
    return ensure_ezproxy_session(
        console, cfg, pipe, enabled=enabled, prompt=prompt
    )


def _preflight_ezproxy_session(
    cfg: Config,
    pipe: Pipeline,
    source_list: list[str],
    *,
    enabled: bool,
) -> None:
    preflight_ezproxy_session(console, cfg, pipe, source_list, enabled=enabled)


def _mid_run_ezproxy_hook(
    cfg: Config, pipe: Pipeline, *, enabled: bool
) -> Callable[[], bool] | None:
    return mid_run_ezproxy_hook(console, cfg, pipe, enabled=enabled)


def _maybe_ezproxy_relogin(
    cfg: Config,
    pipe: Pipeline,
    todo: list,
    *,
    enabled: bool,
) -> None:
    maybe_ezproxy_relogin(console, cfg, pipe, todo, enabled=enabled)


def _run_session_handoff(
    cfg: Config,
    backend: LibraryBackend | None,
    manifest: Manifest,
    catalog: list,
    stats: RunStats,
    *,
    handoff: str,
    include_doi_tabs: bool,
    downloads_dir: Path | None,
    re_request: bool = False,
) -> None:
    run_session_handoff(
        console,
        cfg,
        backend,
        manifest,
        catalog,
        stats,
        handoff=handoff,
        include_doi_tabs=include_doi_tabs,
        downloads_dir=downloads_dir,
        re_request=re_request,
    )


def _inbox_handoff_session(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    items: list,
    missing: list,
    *,
    scope: str,
    once: bool,
    idle_seconds: float | None = None,
    use_fifo: bool = True,
) -> None:
    inbox_handoff_session(
        console,
        cfg,
        backend,
        manifest,
        items,
        missing,
        scope=scope,
        once=once,
        idle_seconds=idle_seconds,
        use_fifo=use_fifo,
    )


def _mirror_deferred(cfg: Config) -> None:
    manager = _manager_name(cfg)
    console.print(
        f"[yellow]Saved to the local mirror ({cfg.out_dir}). "
        f"Not copied to {manager} yet — it was not reachable. "
        f"When it is, run paperful attach.[/]"
    )


def _library_write_api(backend: LibraryBackend) -> bool | None:
    try:
        return bool(backend.supports_write())
    except Exception:
        return None


def _run_flags(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if v}


def _agent_json(fmt: str) -> bool:
    if not isinstance(fmt, str):
        return False
    kind = (fmt or "text").strip().lower()
    if kind not in {"text", "json"}:
        console.print("[red]--format must be text or json.[/]")
        raise typer.Exit(1)
    return kind == "json"


def _emit_agent(payload: dict[str, Any], *, json_out: bool, human: Callable[[], None]) -> None:
    from .agent_json import emit_stdout, stdout_suppressed

    if json_out:
        emit_stdout(payload)
    elif not stdout_suppressed():
        human()
    code = int(payload.get("exit") or 0)
    if code:
        raise typer.Exit(code)


def _agent_wins(fmt: str, as_json: bool = False) -> tuple[bool, bool]:
    """``--format json`` wins over legacy ``--json``."""
    json_out = _agent_json(fmt)
    return json_out, bool(as_json) and not json_out


def _finish_run(
    cfg: Config,
    stats: RunStats,
    *,
    scope: str,
    flags: dict,
    write_api: bool | None = None,
    json_out: bool = False,
) -> None:
    from .agent_json import batch_exit, envelope

    report = build_report(
        stats, cfg, command="run", scope=scope, flags=flags, write_api=write_api
    )
    path = write_run_report(cfg, report)
    summary = report.get("summary") or {}
    attached = int(summary.get("attached") or 0)
    attach_failed = int(summary.get("attach_failed") or 0)
    code = batch_exit(ok=attached, failed=attach_failed)
    payload = envelope(
        command="run",
        summary=summary if isinstance(summary, dict) else {},
        items=list(report.get("items") or []),
        paths={"report": str(path) if path else ""},
        flags=flags,
        report=report,
        exit_code=code,
    )

    def _human() -> None:
        print_run_summary(console, report, path)

    _emit_agent(payload, json_out=json_out, human=_human)


def _load_last_run(cfg: Config) -> dict | None:
    path = cfg.state_dir / "last-run.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


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

    Use ``--item KEY --file PATH`` to ingest a hand-downloaded PDF.
    """
    from .handoff import attach_pdf_file

    cfg = _cfg(config)
    _require_manager(cfg)
    backend = _connect(cfg)
    manifest = Manifest(cfg.manifest_path)
    if not backend.supports_write():
        _exit_env(_no_write(backend), cfg)

    if item or file is not None:
        if len(item) != 1 or file is None:
            console.print(
                "[red]Manual ingest needs exactly one --item KEY and --file PATH.[/]"
            )
            raise typer.Exit(1)
        loaded = _loaded_scope(backend, item_keys=item)
        if not loaded.items:
            console.print(f"[red]Unknown item {item[0]}.[/]")
            raise typer.Exit(1)
        try:
            rec = attach_pdf_file(cfg, backend, manifest, loaded.items[0], file)
        except (OSError, ValueError, LibraryError) as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
        _flush(backend)
        console.print(f"[green]Attached[/] {rec.itemKey} ← {file}")
        _rag_auto(cfg, time.time(), keys=[rec.itemKey])
        return

    pending = manifest.pending_attach(
        allow_pdf_doi_mismatch=allow_pdf_doi_mismatch,
        allow_short_pdf=allow_short_pdf,
    )
    if limit:
        pending = pending[:limit]
    console.print(f"{len(pending)} PDFs to attach")
    if not allow_short_pdf:
        held_short = sum(
            1
            for r in manifest.records.values()
            if r.status == STATUS_OK and r.path and r.reason == REASON_SHORT_PDF
        )
        if held_short:
            console.print(
                f"[dim]{held_short} short PDF(s) held — "
                "pass --allow-short-pdf to admit[/]"
            )
    if not pending:
        console.print("[bold]Attached 0/0[/]")
        return
    pipe = Pipeline(cfg, manifest, console, attacher=backend)
    done = 0
    try:
        with _item_progress() as progress:
            task_id = progress.add_task("Attaching PDFs", total=len(pending))
            for rec in pending:
                if pipe.attach_record(rec):
                    done += 1
                progress.advance(task_id)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
    _flush(backend)
    console.print(f"[bold]Attached {done}/{len(pending)}[/]")


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
    Pass ``-C`` only when you intentionally want a narrower DOI index.
    """
    from .inbox import (
        ensure_inbox_dirs,
        events_as_report_items,
        process_candidates,
        summary_from_stats,
    )

    library = _inbox_library_when_unscoped(collection, library, profile, run_config)
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
    _require_manager(cfg)
    backend = _connect(cfg)
    if not backend.supports_write():
        _exit_env("inbox watch needs library write support.", cfg)
    try:
        root = ensure_inbox_dirs(cfg)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    loaded = _load_scope(
        backend,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    manifest = Manifest(cfg.manifest_path)
    started = time.time()
    console.print(
        f"[bold]Inbox[/] watching {root} for {scope} (DOI match only; Ctrl+C to stop)"
    )
    stats = process_candidates(
        cfg,
        backend,
        manifest,
        items,
        fifo_queue=None,
        once=False,
        idle_seconds=idle,
        collection=collection[0] if collection else "",
        extra_tags=tag,
        on_status=lambda msg: console.print(msg),
    )
    _flush(backend)
    _rag_auto(cfg, started)
    path = write_command_report(
        cfg,
        command="inbox",
        scope=scope,
        summary=summary_from_stats(stats),
        items=events_as_report_items(stats.events),
        flags={"once": False, "fifo": False, "idle": idle},
        started=started,
        extra_paths={"inbox_dir": str(root)},
    )
    console.print(
        f"Inbox attached {stats.attached}, unmatched {stats.unmatched}, "
        f"created_gated {stats.created_gated}, created_auto {stats.created_auto}, "
        f"errors {stats.errors}, skipped {stats.skipped}"
        + (f" ({stats.quit_reason})" if stats.quit_reason else "")
    )
    if path is not None:
        console.print(f"Inbox report: {path}")


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
    Pass ``-C`` only when you intentionally want a narrower DOI index.
    """
    from .inbox import (
        ensure_inbox_dirs,
        events_as_report_items,
        process_candidates,
        summary_from_stats,
    )

    library = _inbox_library_when_unscoped(collection, library, profile, run_config)
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
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    if not collection and not library:
        _refuse_missing_scope()
    _require_manager(cfg)
    backend = _connect(cfg, quiet=json_out)
    if not backend.supports_write():
        _exit_env("inbox drain needs library write support.", cfg)
    try:
        root = ensure_inbox_dirs(cfg)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    loaded = _load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    manifest = Manifest(cfg.manifest_path)
    started = time.time()
    if not json_out:
        console.print(f"[bold]Inbox[/] draining {root} for {scope}")
    stats = process_candidates(
        cfg,
        backend,
        manifest,
        items,
        fifo_queue=None,
        once=True,
        collection=collection[0] if collection else "",
        extra_tags=tag,
        on_status=None if json_out else (lambda msg: console.print(msg)),
    )
    _flush(backend)
    _rag_auto(cfg, started)
    summary = summary_from_stats(stats)
    items_out = events_as_report_items(stats.events)
    path = write_command_report(
        cfg,
        command="inbox",
        scope=scope,
        summary=summary,
        items=items_out,
        flags={"once": True, "fifo": False},
        started=started,
        extra_paths={"inbox_dir": str(root)},
    )
    from .agent_json import batch_exit, envelope

    payload = envelope(
        command="inbox drain",
        summary=summary,
        items=items_out,
        paths={"report": str(path) if path else "", "inbox_dir": str(root)},
        flags={"once": True},
        exit_code=batch_exit(ok=int(stats.attached or 0), failed=int(stats.errors or 0)),
    )

    def _human_drain() -> None:
        console.print(
            f"Inbox attached {stats.attached}, unmatched {stats.unmatched}, "
            f"created_gated {stats.created_gated}, created_auto {stats.created_auto}, "
            f"errors {stats.errors}, skipped {stats.skipped}"
        )
        if path is not None:
            console.print(f"Inbox report: {path}")

    _emit_agent(payload, json_out=json_out, human=_human_drain)


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
    from .inbox_match import list_proposals
    from .agent_json import envelope

    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    want = None if status == "all" else status
    rows = list_proposals(cfg, status=want)
    payload = envelope(
        command="inbox proposals list",
        summary={"count": len(rows)},
        items=rows,
        flags={"status": status},
    )

    def _human() -> None:
        if not rows:
            console.print("No inbox proposals.")
            return
        table = Table(title="inbox proposals")
        table.add_column("id")
        table.add_column("action")
        table.add_column("doi")
        table.add_column("title")
        table.add_column("status")
        for row in rows:
            table.add_row(
                str(row.get("id") or ""),
                str(row.get("action") or ""),
                str(row.get("doi") or ""),
                str(row.get("title") or "")[:60],
                str(row.get("status") or ""),
            )
        console.print(table)

    _emit_agent(payload, json_out=json_out, human=_human)


@inbox_proposals_app.command("apply")
def inbox_proposals_apply(
    proposal_id: str = typer.Argument(..., help="Proposal id from inbox proposals list."),
    tag: list[str] = CreateTagOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .inbox import apply_proposal
    from .agent_json import envelope

    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    _require_manager(cfg)
    backend = _connect(cfg, quiet=json_out)
    if not backend.supports_write():
        _exit_env("inbox proposals apply needs library write support.", cfg)
    manifest = Manifest(cfg.manifest_path)
    try:
        data = apply_proposal(cfg, backend, manifest, proposal_id, extra_tags=tag)
    except (FileNotFoundError, ValueError, LibraryError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    _flush(backend)
    payload = envelope(
        command="inbox proposals apply",
        summary={
            "id": proposal_id,
            "item_key": data.get("item_key") or "",
            "action": data.get("action") or "",
        },
        items=[data],
        flags={"apply": True},
    )

    def _human_apply() -> None:
        console.print(
            f"Applied proposal {proposal_id} → {data.get('item_key') or data.get('action')}"
        )

    _emit_agent(payload, json_out=json_out, human=_human_apply)


@inbox_proposals_app.command("reject")
def inbox_proposals_reject(
    proposal_id: str = typer.Argument(..., help="Proposal id from inbox proposals list."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from .inbox import reject_proposal
    from .agent_json import envelope

    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    try:
        data = reject_proposal(cfg, proposal_id)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    payload = envelope(
        command="inbox proposals reject",
        summary={"id": proposal_id, "status": data.get("status") or "rejected"},
        items=[data],
    )

    def _human_reject() -> None:
        console.print(f"Rejected proposal {proposal_id}")

    _emit_agent(payload, json_out=json_out, human=_human_reject)


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
    from .notes import NOTE_TYPES, apply_delete, collect, select

    if not item and _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    if all_owned and (note_type or model.strip()):
        console.print("[red]Do not combine --all with --type or --model.[/]")
        raise typer.Exit(1)
    types: frozenset[str] | None = None
    if note_type:
        types = frozenset(t.strip().lower() for t in note_type if t.strip())
        unknown = types - NOTE_TYPES
        if unknown:
            console.print(f"[red]Unknown --type: {', '.join(sorted(unknown))}[/]")
            raise typer.Exit(1)
    if not all_owned and types is None and not model.strip() and not except_model.strip():
        console.print(
            "[red]Give --type, --model / --except-model, or --all.[/]"
        )
        raise typer.Exit(1)
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
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    if not item and not collection and not library:
        _refuse_missing_scope()
    _require_manager(cfg)
    backend = _connect(cfg, quiet=json_out)
    loaded = _load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library) or not collection,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items = loaded.items
    scope = loaded.label
    if item:
        want = set(item)
        items = [it for it in items if it.key in want]
        if not items:
            console.print("[red]No matching --item keys in scope.[/]")
            raise typer.Exit(1)
    cols = []
    if collection:
        for spec in collection:
            try:
                cols.append(backend.resolve_collection(spec))
            except LookupError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1) from exc
    hits = collect(backend, items, cfg, collections=cols)
    matched = select(
        hits,
        types=types,
        model=model,
        except_model=except_model,
        all_owned=all_owned,
    )
    from .agent_json import batch_exit, envelope

    if apply and all_owned and not yes:
        if not sys.stdin.isatty():
            console.print("[red]--apply --all needs a TTY confirm or --yes.[/]")
            raise typer.Exit(1)
        if not typer.confirm(f"Trash {len(matched)} Paperful note(s) in {scope}?"):
            raise typer.Exit(1)
    trashed = 0
    errors: list[str] = []
    if apply:
        if not backend.supports_write():
            _exit_env(_no_write(backend), cfg)
        try:
            trashed, errors = apply_delete(backend, matched)
        except LibraryError as exc:
            _exit_env(str(exc), cfg)
        _flush(backend)
    code = batch_exit(ok=trashed, failed=len(errors)) if apply else 0
    payload = envelope(
        command="notes delete",
        summary={
            "matched": len(matched),
            "trashed": trashed,
            "errors": len(errors),
            "skipped_not_paperful": max(0, len(hits) - len(matched)) if all_owned else 0,
        },
        items=[
            {
                "noteKey": h.note_key,
                "parentKey": h.parent_key,
                "title": h.title,
                "type": h.note_type,
                "model": h.model,
                "standalone": h.standalone,
            }
            for h in matched
        ],
        flags={
            "apply": apply,
            "all": all_owned,
            "types": sorted(types) if types else [],
            "model": model,
            "except_model": except_model,
        },
        exit_code=code,
    )

    def _human_notes() -> None:
        console.print(f"Scope: [bold]{scope}[/] — {len(matched)} Paperful note(s)")
        if matched:
            table = Table(title="notes delete" + ("" if apply else " (dry-run)"))
            table.add_column("Note")
            table.add_column("Parent")
            table.add_column("Type")
            table.add_column("Model")
            for h in matched[:100]:
                table.add_row(h.note_key, h.parent_key or "(collection)", h.note_type, h.model)
            console.print(table)
        if apply:
            console.print(f"Trashed {trashed}. Errors {len(errors)}.")
            for err in errors[:20]:
                console.print(f"[yellow]{err}[/]")
        else:
            console.print("Dry-run. Pass [bold]--apply[/] to trash these notes.")

    _emit_agent(payload, json_out=json_out, human=_human_notes)


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
    from .identity import LibraryFingerprint
    from .mirror import pdf_for
    from .refs_gap import (
        ScanFinding,
        aggregate_citations,
        scan_items,
        scan_pdf_citations,
        write_pack,
    )

    if _scope_unset(collection, library, profile, run_config) and not item and not pdf:
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
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    backend = _connect(cfg, quiet=json_out)
    loaded = _load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library) or not collection,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items = loaded.items
    scope = loaded.label
    if item:
        want = set(item)
        items = [it for it in items if it.key in want]
        if not items and not pdf:
            console.print("[red]No matching --item keys in scope.[/]")
            raise typer.Exit(1)
    fingerprint = LibraryFingerprint.from_items(
        list(backend.items_in_scope(None)) if hasattr(backend, "items_in_scope") else items,
        scope=dedupe_scope,
        collection=collection[0] if collection else "",
    )

    def _pdf(it):
        return pdf_for(cfg.out_dir, it)

    refs, findings = scan_items(items, _pdf, fingerprint)
    extra_sources = []
    for path in pdf:
        entries, finding = scan_pdf_citations(path)
        findings.append(ScanFinding(item_key=f"pdf:{path.name}", path=str(path), finding=finding))
        if finding == "ok":
            extra_sources.append((f"pdf:{path.name}", entries))
    if extra_sources:
        extra_refs = aggregate_citations(extra_sources, fingerprint)
        by_id = {(r.doi or r.title, r.year): r for r in refs}
        for row in extra_refs:
            ident = (row.doi or row.title, row.year)
            if ident in by_id:
                host = by_id[ident]
                for key in row.citing_keys:
                    if key not in host.citing_keys:
                        host.citing_keys.append(key)
            else:
                refs.append(row)
    folder = write_pack(cfg.state_dir, scope, refs, findings)
    missing = [r for r in refs if not r.already_exists]
    ocr_n = sum(1 for f in findings if f.finding == "needs_ocr")
    from .agent_ops import refs_gap_envelope

    payload = refs_gap_envelope(
        refs=refs,
        findings=findings,
        folder=folder,
        flags={"dedupe_scope": dedupe_scope},
    )

    def _human_gap() -> None:
        table = Table(title="refs gap")
        table.add_column("n")
        table.add_column("DOI")
        table.add_column("Title")
        table.add_column("Action")
        for row in sorted(missing, key=lambda r: (-len(r.citing_keys), r.doi or r.title))[:50]:
            table.add_row(
                str(len(row.citing_keys)),
                row.doi or "",
                (row.title or "")[:50],
                row.suggested_action,
            )
        console.print(table)
        console.print(f"Cited {len(refs)} · missing {len(missing)} · needs_ocr {ocr_n}")
        console.print(f"Pack: {folder}")
        console.print(
            f"Next: paperful ingest-dois --from-file {folder / 'dois.txt'} -C <collection> --dry-run"
        )

    _emit_agent(payload, json_out=json_out, human=_human_gap)


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
        help="paperful.refs_gap.pack.v1 JSON (or its parent folder).",
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
    from .sync import clean_pdf_cache

    cfg = load_config(config)
    report = clean_pdf_cache(cfg, apply=apply)
    payload = {
        "schema": "paperful.agent.json.v1",
        "command": "cache clean",
        "exit": 0,
        "summary": report,
    }

    def _human() -> None:
        action = "Removed" if apply else "Would remove"
        console.print(
            f"{action} {report['removed'] if apply else report['removable']} "
            f"file(s) under {report['cache_dir']}; kept {report['kept']}."
        )
        if not apply and report["removable"]:
            console.print("[dim]Re-run with --apply to delete them.[/]")

    json_out, _ = _agent_wins(fmt)
    _emit_agent(payload, json_out=json_out, human=_human)


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
    from .restore import apply_restore, iter_records, plan_restore, record_in_scope

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
    from .interop.load import dump_records, record_from_item_json
    from .store import item_dirname, item_filename, load_json, record_path

    if not collection and not library:
        console.print("[red]Give --collection PATH (repeatable) or --library.[/]")
        raise typer.Exit(1)
    cfg = _cfg(config)
    _require_manager(cfg)
    kind = (fmt or dest.suffix.lstrip(".") or "").lower().replace("_", "-")
    if kind in {"bib", "biblatex"}:
        kind = "bibtex"
    if kind in {"xml", "enw"}:
        kind = "endnote-xml"
    if kind not in {"ris", "bibtex", "endnote-xml"}:
        console.print("[red]--format must be ris, bibtex, or endnote-xml.[/]")
        raise typer.Exit(1)
    backend = _connect(cfg)
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
    bundle_dir: Path | None = None
    pdf_dir: Path | None = None
    if kind == "endnote-xml" or pdfs:
        bundle_dir = dest if dest.suffix == "" else dest.parent / dest.stem
        pdf_dir = bundle_dir / "PDF"
        pdf_dir.mkdir(parents=True, exist_ok=True)
    records = []
    copied = 0
    manifest = Manifest(cfg.manifest_path)
    with _item_progress() as progress:
        for it in _track(progress, "Exporting records")(items):
            rec_json = None
            for folder in it.collection_paths or ["_uncollected"]:
                rec_json = load_json(record_path(cfg.out_dir / folder / item_dirname(it)))
                if rec_json:
                    break
            rec = record_from_item_json(rec_json or {}, None)
            rec["item_type"] = it.item_type
            rec["title"] = it.title
            rec["doi"] = it.doi
            rec["year"] = it.year
            rec["date"] = it.date or rec.get("date") or (str(it.year) if it.year else "")
            rec["publication_title"] = it.publication_title or rec.get("publication_title")
            rec["url"] = it.url
            rec["pmid"] = it.pmid
            rec["abstract"] = it.abstract or rec.get("abstract")
            rec["collection_paths"] = [
                p for p in it.collection_paths if p != "_uncollected"
            ]
            rec["item_key"] = it.key
            pdf_list: list[str] = []
            if pdf_dir is not None and it.has_pdf:
                target = pdf_dir / item_filename(it)
                local = pdf_for(cfg.out_dir, it, manifest)
                try:
                    if local is not None:
                        exported = shutil.copyfile(local, target)
                    else:
                        exported = backend.export_pdf(it, target)
                except LibraryError as exc:
                    _exit_env(str(exc), cfg)
                if exported is not None and Path(exported).is_file():
                    pdf_list.append(str(exported))
                    copied += 1
            rec["pdfs"] = pdf_list
            notes = []
            try:
                kids = backend.children(it.key)
            except LibraryError as exc:
                _exit_env(str(exc), cfg)
            for ch in kids:
                data = ch.get("data") or {}
                if data.get("itemType") != "note":
                    continue
                html = str(data.get("note") or "")
                if not html:
                    continue
                tags = [
                    t.get("tag")
                    for t in (data.get("tags") or [])
                    if isinstance(t, dict) and t.get("tag")
                ]
                notes.append(
                    {
                        "file": f"{ch.get('key') or 'note'}.html",
                        "html": html,
                        "tag": tags[0] if tags else "paperful-exported",
                    }
                )
            if notes:
                rec["notes"] = notes
            records.append(rec)
    text = dump_records(records, kind)
    if kind == "endnote-xml" and bundle_dir is not None:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        xml_path = bundle_dir / "paperful.xml"
        xml_path.write_text(text, encoding="utf-8")
        (bundle_dir / "README.txt").write_text(
            "Import paperful.xml in EndNote: File → Import → File, "
            "option EndNote Generated XML. PDFs are in PDF/.\n",
            encoding="utf-8",
        )
        console.print(
            f"[green]Wrote[/] {xml_path} ({len(records)} records, {copied} PDFs) for {scope}"
        )
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    extra = f", {copied} PDFs" if copied else ""
    console.print(f"[green]Wrote[/] {dest} ({len(records)} records{extra}) for {scope}")


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


def _fmt_pack_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    return f"{seconds:g}s"


@pack_app.command("open")
def pack_open(
    label: str | None = typer.Option(None, "--label", help="Name stored on the pack."),
    config: Path | None = ConfigOpt,
) -> None:
    """Start a pack. Later commands append their run reports until `pack close`."""
    from .pack import PackError, open_pack

    cfg = _cfg(config)
    try:
        pack = open_pack(cfg, label=label)
    except PackError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(pack["id"])


@pack_app.command("close")
def pack_close(config: Path | None = ConfigOpt) -> None:
    """Close the open pack and drop the current pointer."""
    from .pack import PackError, close_pack

    cfg = _cfg(config)
    try:
        pack = close_pack(cfg)
    except PackError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    n = len(pack.get("steps") or [])
    console.print(f"Closed {pack['id']} ({n} steps)")


@pack_app.command("show")
def pack_show(
    as_json: bool = typer.Option(
        False, "--json", help="Parent pack plus each step's summary."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Print the open pack, or the latest closed one. Does not open the library."""
    from .pack import headline, latest_pack, show_payload

    cfg = _cfg(config)
    pack = latest_pack(cfg)
    if pack is None:
        console.print("No pack yet. Run [bold]paperful pack open[/] first.")
        raise typer.Exit(0)
    payload = show_payload(cfg, pack)
    if as_json:
        console.print(
            json.dumps(payload, indent=2),
            soft_wrap=True,
            highlight=False,
            markup=False,
        )
        return
    title = pack.get("label") or pack["id"]
    console.print(f"Pack [bold]{pack['id']}[/] ({pack.get('status')})")
    if pack.get("label"):
        console.print(pack["label"], markup=False)
    if pack.get("scope"):
        console.print(f"Scope: {pack['scope']}")
    table = Table(title=str(title))
    table.add_column("Command")
    table.add_column("Duration", justify="right")
    table.add_column("Counts")
    for step in payload.get("steps") or []:
        table.add_row(
            str(step.get("command") or ""),
            _fmt_pack_duration(step.get("duration_s")),
            headline(str(step.get("command") or ""), step.get("summary") or {}),
        )
    console.print(table)


@app.command()
def mirrors(config: Path | None = ConfigOpt) -> None:
    """Ping the configured Sci-Hub mirrors."""
    cfg = _cfg(config)
    console.print(f"[red]{SCIHUB_DISCLAIMER}[/]")
    if "scihub" not in cfg.sources:
        console.print(
            '[dim]Sci-Hub is off until you add "scihub" to sources or pass --scihub on run.[/]'
        )
    ctx = Context(config=cfg, client=make_client(cfg))
    for mirror, status in ping_mirrors(ctx):
        colour = "green" if status == "HTTP 200" else "red"
        console.print(f"[{colour}]{status:<10}[/] {mirror}")


def _confirm_session_login() -> None:
    console.print("Complete login or CAPTCHA in the browser window, then press Enter.")
    try:
        input()
    except EOFError:
        pass


def _netscape_fallback_hint(cookie_path: Path, *, scholar: bool) -> None:
    extra = (
        "Include [bold].google.com[/] and [bold]scholar.google.com[/]. "
        if scholar
        else "Include your EZProxy host (e.g. [bold]*.idm.oclc.org[/]). "
    )
    console.print(
        f"\n[yellow]No session yet.[/] Preferred: [bold]paperful session login "
        f"{'scholar' if scholar else 'ezproxy'}[/] "
        f"(needs [bold]paperful[htmlpdf][/]).\n"
        f"Or export a Netscape cookies.txt ({extra}) to:\n"
        f"  {cookie_path}\n"
        f"If an extension saved to your Desktop:\n"
        f"  mv ~/Desktop/cookies.txt {cookie_path}\n"
        f"  chmod 600 {cookie_path}\n"
        "Firefox: addons.mozilla.org → cookies.txt · Chrome: Get cookies.txt LOCALLY\n"
    )


def _probe_slot(cfg: Config, slot: str) -> None:
    from .cookies import cookie_domains, ezproxy_cookie_status
    from .session import (
        BrowserSession,
        load_vault_cookies,
        profile_ready,
        storage_state_path,
        vault_cookies_path,
    )
    from .sources import ezproxy as ez
    from .sources import scholar as gs

    browser = BrowserSession(cfg)
    ctx = Context(config=cfg, client=make_client(cfg), browser=browser)
    try:
        if slot == "ezproxy":
            cookie_path = cfg.ezproxy_cookie_path
            if (
                not cookie_path.is_file()
                and not vault_cookies_path(cfg).is_file()
                and not storage_state_path(cfg).is_file()
                and not profile_ready(cfg)
            ):
                _netscape_fallback_hint(cookie_path, scholar=False)
                _print_exit_ladder()
                raise typer.Exit(2)
            ticket = ezproxy_cookie_status(load_vault_cookies(cfg), cfg.ezproxy_base)
            if ticket == "cas_only":
                console.print(
                    "[red]Session not ready:[/] CAS/IdP cookies only — "
                    "no EZProxy proxy-host ticket"
                )
                console.print(
                    "Run [bold]paperful session login ezproxy[/] and wait until a "
                    "publisher page loads through the proxy "
                    "(URL should include your idm.oclc.org host), then press Enter."
                )
                _print_exit_ladder()
                raise typer.Exit(2)
            if ticket != "proxy_ticket":
                console.print(
                    "[red]Session not ready:[/] no campus proxy cookies in the vault"
                )
                console.print("Run [bold]paperful session login ezproxy[/] and retry.")
                _print_exit_ladder()
                raise typer.Exit(2)
            ok, detail = ez.session_ok(ctx)
        else:
            cookie_path = cfg.scholar_cookie_path
            gs_domains = sorted(
                d
                for d in cookie_domains(ctx.client.cookies)
                if "google" in (d or "").lower()
            )
            if gs_domains:
                console.print(f"Loaded domains: {', '.join(gs_domains)}")
            if (
                not cookie_path.is_file()
                and not vault_cookies_path(cfg).is_file()
                and not profile_ready(cfg)
            ):
                _netscape_fallback_hint(cookie_path, scholar=True)
                _print_exit_ladder()
                raise typer.Exit(2)
            ok, detail = gs.session_ok(ctx)
    finally:
        browser.close()
    if ok:
        console.print(f"[green]Session OK[/] — {detail}")
        if slot == "ezproxy":
            console.print("[dim]proxy-host ticket present in vault[/]")
        warn = getattr(browser, "inject_warning", None)
        if warn:
            console.print(f"[yellow]{warn}[/]")
        return
    console.print(f"[red]Session not ready:[/] {detail}")
    if slot == "scholar":
        console.print(
            "Solve the CAPTCHA in [bold]paperful session login scholar[/] "
            "(the same Chromium profile used during [bold]run[/]).\n"
            "A cookie file can still fail: Google often keys the pass to the browser, "
            "not cookies alone. Do not retry in a tight loop."
        )
    else:
        console.print("Run [bold]paperful session login ezproxy[/] and retry.")
    _print_exit_ladder()
    raise typer.Exit(2)


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
    from . import session as sess

    cfg = _cfg(config)
    key = slot.strip().lower()
    if key == "mendeley":
        from .mendeley import MendeleyAuthError, MendeleyClient

        console.print(
            "Opening Mendeley / Elsevier authorization in your browser.\n"
            "[dim]Redirect URI must match the app at "
            f"{cfg.mendeley_redirect_uri}[/]"
        )
        try:
            MendeleyClient(cfg).login()
        except MendeleyAuthError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(2)
        console.print(
            "[green]Mendeley authorised.[/] Tokens in "
            f"{cfg.state_dir / 'mendeley-oauth.json'} (mode 0600)."
        )
        return
    if key not in sess.SLOTS:
        console.print(
            f"[red]Unknown slot {slot!r}.[/] Use scholar, ezproxy, or mendeley."
        )
        raise typer.Exit(1)
    eng = engine.strip().lower()
    if eng not in ("auto", "chrome", "playwright"):
        console.print("[red]--engine must be auto, chrome, or playwright.[/]")
        raise typer.Exit(1)
    console.print(f"Vault: {sess.sessions_dir(cfg)}")
    try:
        url = sess.login_url_for(cfg, key)
    except sess.SessionError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(f"Opening: {url}")
    try:
        written = sess.login_headed(
            cfg,
            key,
            confirm=_confirm_session_login,
            on_note=lambda msg: console.print(f"[dim]{msg}[/]"),
            engine=eng,  # type: ignore[arg-type]
        )
    except sess.SessionError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2)
    for path in written:
        console.print(f"Wrote {path}")
    console.print(
        "[green]Session saved.[/] Probe with [bold]paperful session status --probe[/]."
    )
    if key == "ezproxy":
        console.print(
            "[dim]storage_state + Netscape include a proxy-host ticket "
            "(login probed a proxied publisher URL before saving).[/]"
        )


@session_app.command("status")
def session_status(
    config: Path | None = ConfigOpt,
    probe: bool = typer.Option(
        False, "--probe/--no-probe", help="Hit Scholar / EZProxy session_ok (network)"
    ),
) -> None:
    """Show the vault. Default is offline file presence; --probe runs session_ok."""
    from . import session as sess
    from .cookies import ezproxy_cookie_status

    cfg = _cfg(config)
    console.print(f"Vault:     {sess.sessions_dir(cfg)}")
    console.print(f"Chromium:  {sess.chromium_dir(cfg)}")
    console.print(f"Ready:     {sess.profile_ready(cfg)}")
    meta = sess.load_meta(cfg)
    slots = meta.get("slots") or {}
    if slots:
        for name, info in slots.items():
            console.print(f"  {name}: {info}")
    else:
        console.print("[dim]No login slots recorded. Run paperful session login.[/]")
    vault = sess.vault_cookies_path(cfg)
    state = sess.storage_state_path(cfg)
    ez_path = cfg.ezproxy_cookie_path
    gs_path = cfg.scholar_cookie_path
    console.print(f"storage_state:  {'yes' if state.is_file() else 'no'} ({state})")
    console.print(f"Vault cookies:  {'yes' if vault.is_file() else 'no'} ({vault})")
    console.print(f"EZProxy file:  {'yes' if ez_path.is_file() else 'no'} ({ez_path})")
    console.print(f"Scholar file:   {'yes' if gs_path.is_file() else 'no'} ({gs_path})")
    if cfg.ezproxy_base:
        status = ezproxy_cookie_status(sess.load_vault_cookies(cfg), cfg.ezproxy_base)
        if status == "proxy_ticket":
            console.print("EZProxy cookies: [green]proxy-host ticket present[/]")
        elif status == "cas_only":
            console.print(
                "EZProxy cookies: [yellow]CAS/IdP only — no proxy ticket[/] "
                "(run [bold]paperful session login ezproxy[/] and wait for the publisher page)"
            )
        else:
            console.print(
                "EZProxy cookies: [yellow]none[/] "
                "(run [bold]paperful session login ezproxy[/])"
            )
    if not probe:
        return
    if cfg.ezproxy_base:
        _probe_slot(cfg, "ezproxy")
    if "scholar" in cfg.sources:
        _probe_slot(cfg, "scholar")


@session_app.command("export")
def session_export(config: Path | None = ConfigOpt) -> None:
    """Refresh storage_state + Netscape from the vault (keeps session tickets)."""
    from . import session as sess

    cfg = _cfg(config)
    try:
        written = sess.dump_profile_cookies(cfg)
    except sess.SessionError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2)
    for path in written:
        console.print(f"Wrote {path}")


@app.command("ezproxy")
def ezproxy_cmd(
    config: Path | None = ConfigOpt,
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open headed Chromium (or the system browser)"
    ),
) -> None:
    """Check / refresh the campus EZProxy session (wrapper for session login ezproxy)."""
    from . import session as sess
    from .sources import ezproxy as ez

    cfg = _cfg(config)
    cookie_path = cfg.ezproxy_cookie_path
    if not cfg.ezproxy_base:
        console.print("[red]ezproxy_base is empty in config.toml[/]")
        console.print(
            "Set it to your library EZProxy prefix, e.g. https://PREFIX.idm.oclc.org/login?url="
        )
        raise typer.Exit(1)

    console.print(f"Proxy:   {cfg.ezproxy_base}")
    console.print(f"Cookies: {cookie_path}")
    login_url = ez.proxify("https://www.sciencedirect.com/", cfg.ezproxy_base)
    if open_browser:
        if sess.playwright_available():
            session_login("ezproxy", config)
            return
        import webbrowser

        console.print(f"Opening login: {login_url}")
        webbrowser.open(login_url)
        _netscape_fallback_hint(cookie_path, scholar=False)
        console.print("Then re-run: [bold]uv run paperful ezproxy --no-open[/]")
        raise typer.Exit(2)
    _probe_slot(cfg, "ezproxy")


@app.command("scholar")
def scholar_cmd(
    config: Path | None = ConfigOpt,
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open headed Chromium (or the system browser)"
    ),
) -> None:
    """Check / refresh Google Scholar (wrapper for session login scholar)."""
    from . import session as sess

    cfg = _cfg(config)
    cookie_path = cfg.scholar_cookie_path
    console.print(f"Scholar: {sess.SCHOLAR_URL}")
    console.print(f"Cookies: {cookie_path}")
    if open_browser:
        if sess.playwright_available():
            session_login("scholar", config)
            return
        import webbrowser

        console.print(f"Opening: {sess.SCHOLAR_URL}")
        webbrowser.open(sess.SCHOLAR_URL)
        _netscape_fallback_hint(cookie_path, scholar=True)
        console.print("Then re-run: [bold]uv run paperful scholar --no-open[/]")
        raise typer.Exit(2)
    _probe_slot(cfg, "scholar")


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
    from .browser_agent import recover_start_url
    from .llm import agent_model_uses_litellm, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_recover
    from .llm.validate import LlmConfigError
    from .runreport import recover_item_keys_from_report

    if not item and not from_last_run:
        console.print("[red]Give --item KEY or --from-last-run.[/]")
        raise typer.Exit(1)
    if item and from_last_run:
        console.print("[red]Use --item or --from-last-run, not both.[/]")
        raise typer.Exit(1)
    if sys.version_info < (3, 11):
        console.print(
            "[red]recover requires Python 3.11+ for browser-use.[/] "
            f"This interpreter is {sys.version_info.major}.{sys.version_info.minor}."
        )
        raise typer.Exit(1)
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    _require_manager(cfg)
    try:
        validate_llm_for_recover(cfg)
    except LlmConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    if not json_out:
        console.print(f"[orange3]{RECOVER_DISCLAIMER}[/]")
        remote = llm_egress_is_remote(cfg)
        fb = cfg.browser_agent_fallback_model.strip()
        if fb and agent_model_uses_litellm(cfg, fb):
            remote = True
        if remote:
            console.print(
                "[orange3]Remote LLM provider — page text may leave this machine.[/]"
            )
    backend = _connect(cfg, quiet=json_out)
    manifest = Manifest(cfg.manifest_path)
    item_keys = list(item)
    scope = f"items:{','.join(item_keys)}"
    if from_last_run:
        last = _load_last_run(cfg)
        if not last or last.get("schema") != "paperful.run_report.v1":
            console.print(
                "[red]No auditable last run at state/last-run.json — run paperful run first.[/]"
            )
            raise typer.Exit(1)
        item_keys = recover_item_keys_from_report(last, mode=from_last_run_mode)
        if limit is not None and limit > 0:
            item_keys = item_keys[:limit]
        scope = f"from-last-run:{from_last_run_mode}"
        if not item_keys:
            console.print("[yellow]No items matched the last-run filter.[/]")
            raise typer.Exit(0)
    elif limit is not None and limit > 0:
        item_keys = item_keys[:limit]
    todo: list = []
    preview: list[dict[str, Any]] = []
    for key in item_keys:
        it = backend.get_item(key)
        if it is None:
            console.print(f"[red]Unknown item key {key}[/]")
            raise typer.Exit(1)
        if it.has_pdf and not dry_run:
            if not json_out:
                console.print(f"[dim]Skipping {key} — already has PDF[/]")
            preview.append({"itemKey": key, "status": "skip", "reason": "has_pdf"})
            continue
        url = recover_start_url(it)
        if not url:
            console.print(f"[red]{key}: no DOI or URL[/]")
            raise typer.Exit(1)
        if dry_run:
            if not json_out:
                console.print(f"[bold]{key}[/] would recover from {url}")
            preview.append({"itemKey": key, "status": "would", "url": url})
            continue
        todo.append(it)
    if dry_run or not todo:
        from .agent_json import envelope

        payload = envelope(
            command="recover",
            summary={
                "count": len(preview),
                "would": sum(1 for r in preview if r.get("status") == "would"),
            },
            items=preview,
            flags={"dry_run": dry_run, "no_attach": no_attach},
        )
        _emit_agent(payload, json_out=json_out, human=lambda: None)
        raise typer.Exit(0)
    attacher = None if no_attach else backend
    if attacher and not backend.supports_write():
        _exit_env("Write support required to attach.", cfg)
    with _item_progress(json_out=json_out) as progress:
        task_id = progress.add_task("Recovering PDFs", total=len(todo))
        pipe = Pipeline(
            cfg,
            manifest,
            console,
            sources=["browser_agent"],
            attacher=attacher,
            progress=lambda: progress.advance(task_id),
            try_all=True,
            use_browser=False,
        )
        try:
            stats = pipe.run(todo)
        except KeyboardInterrupt:
            stats = pipe.stats
    report = build_report(
        stats,
        cfg,
        command="recover",
        scope=scope,
        flags=_run_flags(no_attach=no_attach, from_last_run=from_last_run),
    )
    path = write_run_report(cfg, report)
    from .agent_json import batch_exit, envelope

    summary = report.get("summary") or {}
    code = batch_exit(
        ok=int(summary.get("attached") or 0),
        failed=int(summary.get("attach_failed") or 0),
    )
    payload = envelope(
        command="recover",
        summary=summary if isinstance(summary, dict) else {},
        items=list(report.get("items") or []),
        paths={"report": str(path) if path else ""},
        flags=_run_flags(no_attach=no_attach),
        report=report,
        exit_code=code,
    )
    _emit_agent(
        payload,
        json_out=json_out,
        human=lambda: print_run_summary(console, report, path),
    )
    _flush(backend)


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
    from .ocr import OcrUnavailable, ocr_items

    if not item and _scope_unset(collection, library, profile, run_config):
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    if attach and not apply:
        console.print("[red]--attach needs --apply.[/]")
        raise typer.Exit(1)
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
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    limit = bound.limit
    if not item and not collection and not library:
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    _require_manager(cfg)
    backend = _connect(cfg, quiet=json_out)
    if attach and not backend.supports_write():
        _exit_env("Write support required to attach.", cfg)
    manifest = Manifest(cfg.manifest_path)
    loaded = _load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        item_keys=item,
        pdfs_only=True,
    )
    items, scope = loaded.items, loaded.label
    if limit:
        items = items[:limit]
    started = time.time()
    deadline = (
        started + max_minutes * 60.0 if max_minutes is not None and max_minutes > 0 else None
    )
    if not items:
        write_command_report(
            cfg,
            command="ocr",
            scope=scope,
            summary={"ocr": 0, "skipped": 0, "failed": 0, "would": 0, "not_reached": 0},
            items=[],
            flags={"apply": apply, "attach": attach, "max_minutes": max_minutes},
            started=started,
        )
        from .agent_json import envelope

        payload = envelope(
            command="ocr",
            summary={"ocr": 0, "skipped": 0, "failed": 0, "would": 0, "not_reached": 0},
            flags={"apply": apply, "attach": attach},
        )

        def _human_ocr_empty() -> None:
            console.print("[yellow]No items with PDFs in scope.[/]")

        _emit_agent(payload, json_out=json_out, human=_human_ocr_empty)
        raise typer.Exit(0)
    try:
        with _item_progress(json_out=json_out) as progress:
            batch = ocr_items(
                cfg,
                items,
                manifest,
                backend,
                apply=apply,
                attach=attach,
                track=_track(progress, "Running OCR" if apply else "Checking PDFs"),
                deadline=deadline,
            )
    except OcrUnavailable as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    table = Table(title="paperful ocr" + ("" if apply else " (dry-run)"))
    table.add_column("Key")
    table.add_column("Title")
    table.add_column("Path")
    table.add_column("Why")
    for row in batch.rows:
        if row.status == "skip":
            continue
        title = row.title if len(row.title) <= 60 else row.title[:57] + "…"
        table.add_row(row.key, title, row.path, row.reason or row.status)
    outcomes = [
        {
            "itemKey": row.key,
            "title": row.title,
            "status": row.status,
            "reason": row.reason,
            "path": row.path,
        }
        for row in batch.rows
    ]
    write_command_report(
        cfg,
        command="ocr",
        scope=scope,
        summary={
            "ocr": batch.ocr,
            "skipped": batch.skipped,
            "failed": batch.failed,
            "would": batch.would,
            "not_reached": batch.not_reached,
        },
        items=outcomes,
        flags={"apply": apply, "attach": attach, "max_minutes": max_minutes},
        started=started,
    )
    from .agent_json import batch_exit, envelope

    code = batch_exit(ok=batch.ocr, failed=batch.failed) if apply else 0
    payload = envelope(
        command="ocr",
        summary={
            "ocr": batch.ocr,
            "skipped": batch.skipped,
            "failed": batch.failed,
            "would": batch.would,
            "not_reached": batch.not_reached,
        },
        items=outcomes,
        flags={"apply": apply, "attach": attach},
        exit_code=code,
    )

    def _human_ocr() -> None:
        if batch.would or batch.ocr or batch.failed:
            console.print(table)
        if apply:
            console.print(
                f"OCR {batch.ocr}, skipped {batch.skipped}, failed {batch.failed}."
                + (
                    f" Not checked: {batch.not_reached}."
                    if batch.not_reached
                    else ""
                )
            )
        else:
            console.print(
                f"Would OCR {batch.would}, skip {batch.skipped} "
                f"(already have text). Pass --apply to write the text layer."
            )

    _emit_agent(payload, json_out=json_out, human=_human_ocr)
    _flush(backend)
    if apply:
        _rag_auto(
            cfg, started, keys=[row.key for row in batch.rows if row.status == "ocr"]
        )


# ---- library index: `paperful rag` and `paperful ask` -------------------------
# These read out_dir and state_dir only. None of them opens the reference manager.


def _rag_require(cfg: Config) -> None:
    if not cfg.rag_enabled:
        console.print("[red]rag.enabled is false in config.toml[/]")
        raise typer.Exit(1)


def _rag_embedder(cfg: Config):
    """A checked embedder, or exit 1 with the reason."""
    from .llm import embed_egress_is_remote, validate_embedder
    from .llm.validate import LlmConfigError

    try:
        embedder = validate_embedder(cfg)
    except LlmConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if embed_egress_is_remote(cfg):
        console.print(
            "[yellow]Remote embedding model — passage text leaves this machine.[/]"
        )
    return embedder


def _rag_open(cfg: Config):
    """The index and its ledger, or exit 1 when there is nothing to search."""
    from .rag.index import (
        Index,
        IndexMismatch,
        IndexMissing,
        RagUnavailable,
        ledger_path,
    )
    from .rag.ledger import Ledger

    try:
        return Index.open(cfg), Ledger(ledger_path(cfg))
    except (RagUnavailable, IndexMissing, IndexMismatch) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


def _rag_auto(cfg: Config, since: float, keys: Any = ()) -> None:
    """Index PDFs this command just landed, when ``[rag].auto_ingest`` is on.

    Never fails the command it follows: the index is a cache, and
    ``paperful rag ingest`` catches up later.
    """
    if not (cfg.rag_enabled and cfg.rag_auto_ingest):
        return
    from .rag.auto import auto_ingest

    try:
        with _item_progress() as progress:
            batch = auto_ingest(
                cfg,
                since=since,
                keys=keys,
                track=_track(progress, "Indexing new PDFs"),
                ocr_track=_track(progress, "Running OCR"),
            )
    except KeyboardInterrupt:
        console.print(
            "[yellow]Indexing interrupted. `paperful rag ingest` resumes it.[/]"
        )
        return
    except Exception as exc:
        console.print(f"Index not updated: {exc}", markup=False, style="yellow")
        console.print("[yellow]Run `paperful rag ingest` to catch up.[/]")
        return
    if batch is None:
        return
    done = batch.count("pdf", "ocr", "abstract")
    if done:
        console.print(
            f"[dim]Index: {done} item(s) updated, {batch.chunks} passages.[/]"
        )


def _print_hits(hits: list) -> None:
    from .rag.prompt import Source

    for n, hit in enumerate(hits, start=1):
        who = Source("", hit.item_key, hit.title, hit.authors, hit.year).citation
        where = f", {hit.pages}" if hit.pages else ""
        console.print(
            f"{n}. {hit.score:.3f}  {who}. {hit.title}{where} [{hit.item_key}]",
            markup=False,
            highlight=False,
        )
        snippet = " ".join(hit.text.split())
        if len(snippet) > 320:
            snippet = snippet[:317] + "…"
        console.print(f"   {snippet}", markup=False, highlight=False, style="dim")


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


def _ask_once(
    cfg: Config,
    question: str,
    *,
    stream: bool,
    show_context: bool,
    history: list[dict[str, str]] | None = None,
    retrieve_as: str | None = None,
    quiet: bool = False,
    focus: str | None = None,
    prompt_path: str | None = None,
    **retrieval: Any,
) -> dict[str, Any]:
    """Answer one question on the terminal and return it for the run report."""
    from .rag.answer import answer

    reply = answer(
        cfg,
        question,
        history=history or (),
        retrieve_as=retrieve_as,
        focus=focus,
        prompt_path=prompt_path,
        **retrieval,
    )
    if quiet:
        reply.read()
    elif show_context and reply.hits:
        console.print("[bold]Passages[/]")
        _print_hits(reply.hits)
        console.print()
    if not quiet:
        # Answers carry [S1]-style markers; Rich would read them as markup and drop them.
        if stream:
            for piece in reply:
                console.out(piece, end="", highlight=False)
            console.out("", highlight=False)
        else:
            with _spinner("Thinking…"):
                reply.read()
            console.print(reply.text, markup=False, highlight=False)
        cited = reply.cited()
        listed = cited or reply.sources
        if listed:
            heading = "Sources" if cited else "Retrieved, not cited"
            console.print(f"\n[bold]{heading}[/]")
            for source in listed:
                pages = f" {', '.join(source.pages)}." if source.pages else ""
                console.print(
                    f"[{source.marker}] {source.citation}. {source.title}.{pages} "
                    f"[{source.item_key}]",
                    markup=False,
                    highlight=False,
                )
    cited = reply.cited()
    return {
        "question": question,
        "answer": reply.text,
        "cited": [s.marker for s in cited],
        "sources": [
            {
                "marker": s.marker,
                "itemKey": s.item_key,
                "title": s.title,
                "pages": s.pages,
            }
            for s in reply.sources
        ],
    }


def _ask_questions(first: str | None) -> Iterator[str]:
    """The question given, or a prompt loop. Piped input is one question per line."""
    if first is not None:
        yield first
        return
    interactive = sys.stdin.isatty()
    if interactive:
        console.print("[dim]Ask about your library. Empty line or :q to leave.[/]")
    while True:
        try:
            line = input("ask> " if interactive else "")
        except EOFError:
            return
        line = line.strip()
        if line in (":q", "exit", "quit") or (interactive and not line):
            return
        if line:
            yield line


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
    from .llm import LLMClientError, get_client, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_ask
    from .llm.validate import LlmConfigError
    from .rag.prompt import parse_focus
    from .rag.retrieve import scope_keys
    from .agent_json import batch_exit
    from .agent_ops import ask_envelope

    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    batch_mode = from_file is not None
    if json_out and question is None and not batch_mode:
        console.print("[red]ask --format json needs a question.[/]")
        raise typer.Exit(1)
    if batch_mode and thread is not None:
        console.print("[red]ask --from-file cannot use --thread.[/]")
        raise typer.Exit(1)
    if json_out:
        no_stream = True
    bound = _bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=None,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        focus=focus,
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
    try:
        validate_llm_for_ask(cfg)
    except LlmConfigError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    try:
        focus_name = parse_focus(
            focus if focus is not None else (bound.focus or cfg.rag_focus)
        )
    except ValueError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    prompt_path = str(prompt.expanduser().resolve()) if prompt is not None else (
        cfg.rag_prompt or None
    )
    types = _resolve_types(item_type)
    embedder = _rag_embedder(cfg)
    if llm_egress_is_remote(cfg) and not json_out:
        console.print(
            "[yellow]Remote LLM — excerpts from your PDFs leave this machine.[/]"
        )
    index, ledger = _rag_open(cfg)
    keys = scope_keys(
        ledger,
        collections=collection,
        item_keys=item,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
    )
    client = get_client(cfg)
    started = time.time()

    if batch_mode:
        from dataclasses import asdict as _asdict

        from .rag.batch import read_questions, run_batch, write_pack
        from .snowball.command import SnowballError

        try:
            questions = read_questions(str(from_file))
        except SnowballError as exc:
            console.print(str(exc), markup=False, style="red")
            raise typer.Exit(1) from exc
        if not questions:
            console.print("[red]No questions in --from-file.[/]")
            raise typer.Exit(1)
        dest = (to.value if to is not None else cfg.rag_dest) or "disk"
        if apply and dest == "disk":
            console.print(
                "[red]--apply writes a Zotero note; it conflicts with --to disk.[/]"
            )
            raise typer.Exit(1)
        if apply and wants_zotero(dest) and len(collection) != 1:
            console.print(
                "[red]ask --apply to Zotero needs exactly one -C collection.[/]"
            )
            raise typer.Exit(1)
        pack = run_batch(
            cfg,
            questions,
            keys=keys,
            focus=focus_name,
            prompt_path=prompt_path,
            k=top_k,
            force=force,
            scope={
                "collections": list(collection),
                "item": list(item),
                "year_from": year_from,
                "year_to": year_to,
            },
            client=client,
            embedder=embedder,
            index=index,
            ledger=ledger,
        )
        folder = write_pack(cfg, pack)
        if apply and wants_zotero(dest):
            from .notehtml import wrap
            from .summarize import to_note_html

            backend = get_backend(cfg)
            body = (folder / "answers.md").read_text(encoding="utf-8")
            html = wrap(
                to_note_html(body),
                note_type="review",
                verb="ask",
                model=pack.model,
            )
            target = backend.resolve_collection(collection[0])
            backend.create_or_update_collection_note(
                target.key, html, "paperful-ask-batch"
            )
            if not json_out:
                console.print(
                    f"[green]Zotero collection note updated for {collection[0]}.[/]"
                )
        if not json_out:
            console.print(
                f"Batch: {pack.answered} answered, {pack.skipped} skipped, "
                f"{pack.failed} failed → {folder}"
            )
        write_command_report(
            cfg,
            command="ask",
            scope=", ".join(collection) or "index",
            summary={
                "questions": pack.questions,
                "answered": pack.answered,
                "skipped": pack.skipped,
                "failed": pack.failed,
                "pack": str(folder),
            },
            items=[_asdict(r) for r in pack.rows],
            flags={
                "top_k": top_k or cfg.rag_top_k,
                "model": pack.model,
                "focus": pack.focus,
                "from_file": str(from_file),
                "batch": True,
            },
            started=started,
        )
        code = batch_exit(ok=pack.answered + pack.skipped, failed=pack.failed)
        if json_out:
            payload = ask_envelope(
                items=[_asdict(r) for r in pack.rows],
                summary={
                    "questions": pack.questions,
                    "answered": pack.answered,
                    "skipped": pack.skipped,
                    "failed": pack.failed,
                    "pack": str(folder),
                },
                flags={
                    "read_only": not apply,
                    "batch": True,
                    "focus": pack.focus,
                    "top_k": top_k or cfg.rag_top_k,
                },
                exit_code=code,
            )
            _emit_agent(payload, json_out=True, human=lambda: None)
            return
        if pack.failed:
            raise typer.Exit(1)
        return

    answered: list[dict[str, Any]] = []
    failures = 0
    from .rag.thread import load_thread, new_id, rewrite_query, save_thread

    use_thread = thread is not None or (
        (not json_out) and question is None and sys.stdin.isatty()
    )
    thread_id = None
    turns: list[dict[str, str]] = []
    if use_thread:
        raw_id = (thread or "").strip()
        thread_id = new_id() if raw_id in {"", "new"} else raw_id
        loaded = load_thread(cfg.state_dir, thread_id)
        turns = list(loaded.turns)
        if use_thread and not json_out:
            console.print(f"[dim]Thread {thread_id} ({len(turns) // 2} turns)[/]")
    for asked in _ask_questions(question):
        retrieve_as = asked
        if turns:
            retrieve_as = rewrite_query(cfg, asked, turns, client=client)
        try:
            row = _ask_once(
                cfg,
                asked,
                stream=not no_stream,
                show_context=show_context and not json_out,
                history=turns,
                retrieve_as=retrieve_as,
                k=top_k,
                keys=keys,
                focus=focus_name,
                prompt_path=prompt_path,
                client=client,
                embedder=embedder,
                index=index,
                ledger=ledger,
                quiet=json_out,
            )
            row["retrieve_as"] = retrieve_as
            row["focus"] = focus_name
            answered.append(row)
            if use_thread:
                turns.append({"role": "user", "content": asked})
                turns.append({"role": "assistant", "content": row.get("answer") or ""})
                from .rag.thread import Thread

                save_thread(
                    cfg.state_dir,
                    Thread(thread_id=thread_id, turns=turns, last_query=retrieve_as),
                )
        except KeyboardInterrupt:
            if not json_out:
                console.print("\n[yellow]Cancelled.[/]")
            failures += 1
        except LLMClientError as exc:
            if not json_out:
                console.print()
                console.print(str(exc), markup=False, style="red")
            failures += 1
        if question is None and not json_out:
            console.print()
    if answered or failures:
        write_command_report(
            cfg,
            command="ask",
            scope=", ".join(collection) or "index",
            summary={
                "questions": len(answered) + failures,
                "answered": len(answered),
                **({"thread": thread_id} if thread_id else {}),
            },
            items=answered,
            flags={
                "top_k": top_k or cfg.rag_top_k,
                "model": cfg.rag_model or cfg.llm_model,
                "embed_model": cfg.rag_embed_model,
                "focus": focus_name,
                **({"thread": thread_id} if thread_id else {}),
            },
            started=started,
        )
    code = batch_exit(ok=len(answered), failed=failures)
    if json_out:
        first = (question or "").strip()
        summary = {
            "questions": len(answered) + failures,
            "answered": len(answered),
        }
        if first:
            summary["question"] = first
        if thread_id:
            summary["thread"] = thread_id
        payload = ask_envelope(
            items=answered,
            summary=summary,
            flags={
                "read_only": True,
                "top_k": top_k or cfg.rag_top_k,
                "focus": focus_name,
                **({"thread": thread_id} if thread_id else {}),
            },
            exit_code=code,
        )
        _emit_agent(payload, json_out=True, human=lambda: None)
        return
    if question is not None and failures:
        raise typer.Exit(1)


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
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Grounded LLM summary from local PDF text. Default writes disk and a Zotero note."""
    from .llm import llm_egress_is_remote
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError
    from .summarize import SummaryRow, order_items, summarize_items

    if not item and _scope_unset(collection, library, profile, run_config):
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    bound = _bind_run(
        cfg,
        use_apply=True,
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
    if not item and not collection and not library:
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    dest = to.value if to is not None else cfg.summarize_dest
    queue_order = order.value if order is not None else cfg.summarize_order
    if apply and dest == "disk":
        console.print(
            "[red]--apply writes a Zotero note; it conflicts with --to disk.[/]"
        )
        raise typer.Exit(1)
    _require_manager(cfg)
    try:
        validate_llm_for_verb(cfg)
    except LlmConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    if llm_egress_is_remote(cfg):
        console.print(
            "[yellow]Remote LLM — PDF text may leave this machine for this run.[/]"
        )
    if prompt is not None:
        cfg.summarize_prompt_template = str(prompt.expanduser().resolve())
    backend = _connect(cfg, quiet=json_out)
    manifest = Manifest(cfg.manifest_path)
    loaded = _load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        item_keys=item,
        pdfs_only=True,
    )
    items, scope = loaded.items, loaded.label
    items = order_items(items, queue_order)
    if limit:
        items = items[:limit]
    started = time.time()
    deadline = (
        started + max_minutes * 60.0 if max_minutes is not None and max_minutes > 0 else None
    )
    agent_box: list[dict[str, Any]] = []

    def _finish(
        outcomes: list[dict],
        summarized: int,
        failed: int,
        skipped: int,
        not_reached: int = 0,
    ) -> None:
        write_command_report(
            cfg,
            command="summarize",
            scope=scope,
            summary={
                "summarized": summarized,
                "failed": failed,
                "skipped": skipped,
                "not_reached": not_reached,
                "dest": dest,
                "order": queue_order,
            },
            items=outcomes,
            flags={
                "to": dest,
                "order": queue_order,
                "max_new": max_new,
                "max_minutes": max_minutes,
            },
            started=started,
        )
        from .agent_json import batch_exit, envelope

        code = batch_exit(ok=summarized, failed=failed)
        payload = envelope(
            command="summarize",
            summary={
                "summarized": summarized,
                "failed": failed,
                "skipped": skipped,
                "not_reached": not_reached,
            },
            items=outcomes,
            flags={"to": dest, "order": queue_order},
            exit_code=code,
        )
        agent_box.append(payload)

    def _show(row: SummaryRow) -> None:
        if json_out:
            return
        who = row.label or row.title or row.key
        if row.status == "summarized":
            console.print(f"[green]Wrote[/] {who}")
            if row.disk_path:
                console.print(f"  {row.disk_path}")
            if row.note_key:
                console.print(f"  attached note {row.note_key}")
        elif row.status == "skipped":
            console.print(f"[dim]{who}[/]: {row.reason}")
        elif not row.fatal:
            console.print(f"[yellow]{who}[/]: {row.reason}")

    if not items:
        _finish([], 0, 0, 0)
        _emit_agent(
            agent_box[-1],
            json_out=json_out,
            human=lambda: console.print("[yellow]No items with PDFs in scope.[/]"),
        )
        return
    with _item_progress(json_out=json_out) as progress:
        batch = summarize_items(
            cfg,
            items,
            manifest,
            backend,
            dest=dest,
            force=force,
            on_row=_show,
            track=_track(progress, "Summarizing"),
            max_new=max_new,
            deadline=deadline,
        )
    outcomes = [
        {
            "itemKey": row.key,
            "title": row.title,
            "status": row.status,
            **({"reason": row.reason} if row.reason else {}),
        }
        for row in batch.rows
    ]
    _finish(
        outcomes,
        batch.summarized,
        batch.failed,
        batch.skipped,
        batch.not_reached,
    )
    if batch.fatal and not json_out:
        console.print(f"[red]{batch.fatal}[/]")
        raise typer.Exit(1)

    def _human_sum() -> None:
        if batch.fatal:
            console.print(f"[red]{batch.fatal}[/]")
            return
        where = cfg.summaries_dir if wants_disk(dest) else "Zotero"
        console.print(f"Summarized {batch.summarized}/{len(items)} items under {where}")
        if batch.not_reached:
            console.print(f"Not reached: {batch.not_reached} (time or --max-new limit).")
        if batch.skipped:
            console.print(
                f"Skipped {batch.skipped} already summarized for this model "
                "(pass --force to redo)."
            )
        if dest == "disk":
            console.print("Zotero not written (dest=disk).")

    if batch.fatal:
        agent_box[-1]["exit"] = 1
        agent_box[-1]["ok"] = False
    _emit_agent(agent_box[-1], json_out=json_out, human=_human_sum)
    if batch.fatal:
        raise typer.Exit(1)
    _flush(backend)


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
    from .llm import LLMClientError, get_client, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError
    from .synthesize import (
        ReduceCapError,
        SynthesisEvent,
        prepare_synthesis,
        report_is_current,
        write_synthesis,
    )

    if not item and _scope_unset(collection, library, profile, run_config):
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
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
    )
    collection, library, year_from, year_to, item_type = _take_scope(bound)
    limit = bound.limit
    if not item and not collection and not library:
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    dest = to.value if to is not None else cfg.synthesize_dest
    if report_collection and not wants_zotero(dest):
        console.print(
            "[red]--report-collection files a Zotero note; it conflicts with --to disk.[/]"
        )
        raise typer.Exit(1)
    _require_manager(cfg)
    try:
        validate_llm_for_verb(cfg)
    except LlmConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    if llm_egress_is_remote(cfg) and not dry_run:
        console.print(
            "[yellow]Remote LLM — summary text may leave this machine for this run.[/]"
        )
    if prompt is not None:
        cfg.synthesize_prompt_template = str(prompt.expanduser().resolve())
    backend = _connect(cfg, quiet=json_out)
    loaded = _load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        item_keys=item,
    )
    items, scope = loaded.items, loaded.label
    items.sort(
        key=lambda it: (it.year or 9999, (it.first_author or "").lower(), it.key)
    )
    if limit:
        items = items[:limit]
    targets = []
    if wants_zotero(dest):
        if report_collection:
            try:
                targets = [backend.resolve_collection(report_collection)]
            except LookupError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1)
        elif collection:
            seen_keys: set[str] = set()
            for spec in collection:
                try:
                    root = backend.resolve_collection(spec)
                except LookupError as exc:
                    console.print(f"[red]{exc}[/]")
                    raise typer.Exit(1)
                if root.key not in seen_keys:
                    seen_keys.add(root.key)
                    targets.append(root)
        else:
            console.print(
                "[red]Pass -C or --report-collection to file the Zotero note, or --to disk.[/]"
            )
            raise typer.Exit(1)
    slug_parts = []
    if library:
        slug_parts.append("library")
    slug_parts.extend(collection)
    slug_parts.extend(item)
    if year_from is not None or year_to is not None:
        slug_parts.append(f"{year_from or ''}-{year_to or ''}")
    types = _resolve_types(item_type)
    if types:
        slug_parts.extend(sorted(types))
    with _item_progress(json_out=json_out) as progress:
        prepared = prepare_synthesis(
            cfg,
            items,
            backend,
            slug_parts,
            track=_track(progress, "Reading summaries"),
        )
    sources, missing, slug = prepared.sources, prepared.missing, prepared.slug
    plan = prepared.chunks
    on_disk = sum(1 for src in sources if src.origin == "disk")
    from_note = sum(1 for src in sources if src.origin == "note")
    if dry_run:
        console.print(
            f"Sources: {on_disk} on disk, {from_note} from Zotero notes, {len(missing)} missing"
        )
        if plan:
            sizes = ", ".join(str(n) for n in plan)
            console.print(f"Chunks: {len(plan)} ({sizes} chars)")
        else:
            console.print("[yellow]No summary notes in scope.[/]")
        if wants_disk(dest):
            console.print(f"Disk: {cfg.reports_dir / (slug + '.html')}")
        for root in targets:
            console.print(f"Zotero: {root.path} ({root.key})")
        raise typer.Exit(0)
    if not sources:
        console.print(
            "[yellow]No summary notes in scope.[/] Run [bold]paperful summarize[/] first."
        )
        raise typer.Exit(0)
    if not force and report_is_current(cfg, slug, sources, dest=dest):
        console.print(
            f"Report up to date ({len(sources)} summaries unchanged). Pass [bold]--force[/] to regenerate."
        )
        raise typer.Exit(0)
    started = time.time()

    def _announce(event: SynthesisEvent) -> None:
        if event.kind == "html":
            console.print(f"[green]Wrote[/] {event.path}")
        elif event.kind == "note":
            console.print(
                f"  attached note {event.note_key} in {event.collection_path}"
            )
        elif event.kind == "json":
            console.print(f"[green]Wrote[/] {event.path}")

    try:
        with _spinner("Writing the report…", json_out=json_out):
            written = write_synthesis(
                cfg,
                sources=sources,
                missing=missing,
                scope=scope,
                slug=slug,
                dest=dest,
                targets=targets,
                backend=backend,
                client=get_client(cfg),
                log=lambda line: console.print(f"[dim]{line}[/]"),
                announce=_announce,
            )
    except ReduceCapError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    except LibraryError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    except (OSError, ValueError, LLMClientError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    n_chunks = written.n_chunks
    outcomes = [
        ItemOutcome(
            itemKey=src.key, title=src.title, status="summarized", reason=src.origin
        )
        for src in sources
    ]
    outcomes.extend(
        ItemOutcome(itemKey=it.key, title=it.title, status="missing_summary")
        for it in missing
    )

    class _Stats:
        pass

    stats = _Stats()
    stats.started_at = started
    stats.finished_at = time.time()
    stats.items = outcomes
    stats.scope = scope
    report = build_report(
        stats,
        cfg,
        command="synthesize",
        scope=scope,
        flags={
            "to": dest,
            "chunks": n_chunks,
            "included": len(sources),
            "missing": len(missing),
            "slug": slug,
        },
    )
    report["summary"]["included"] = len(sources)
    report["summary"]["missing"] = len(missing)
    report["summary"]["chunks"] = n_chunks
    path = write_run_report(cfg, report, as_last_run=False)
    from .agent_json import envelope

    payload = envelope(
        command="synthesize",
        summary={
            "included": len(sources),
            "missing": len(missing),
            "chunks": n_chunks,
        },
        paths={"report": str(path) if path else ""},
        flags={"to": dest, "slug": slug},
    )
    _emit_agent(
        payload,
        json_out=json_out,
        human=lambda: console.print(
            f"Synthesized {len(sources)} summaries ({len(missing)} not included) → {path}"
        ),
    )
    _flush(backend)


def _call_step(fn, /, **kwargs: Any) -> None:
    """Run one verb. ``typer.Exit(0)`` (dry-run tables) does not stop the chain."""
    try:
        fn(**kwargs)
    except typer.Exit as exc:
        if exc.exit_code not in (0, None):
            raise


def _all_scope(bound: ResolvedRunConfig, config: Path | None) -> dict[str, Any]:
    return {
        "collection": list(bound.collections),
        "library": bound.library,
        "year_from": bound.year_from,
        "year_to": bound.year_to,
        "item_type": list(bound.types),
        "profile": None,
        "run_config": None,
        "config": config,
    }


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
    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    bound = _bind_run(
        cfg,
        for_all=True,
        use_run_policy=True,
        use_apply=True,
        profile=profile,
        run_config=run_config,
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
    )
    if not bound.collections and not bound.library:
        _refuse_missing_scope()
    opened = False
    if pack_join_disabled():
        if not json_out:
            console.print("[dim]PAPERFUL_PACK=off — reports are not grouped.[/]")
    elif current_id(cfg) is None:
        try:
            pack = open_pack(cfg, label=label or bound.name or "all")
        except PackError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
        opened = True
        if not json_out:
            console.print(f"[dim]Pack {pack['id']} opened.[/]")
    else:
        if not json_out:
            console.print(f"[dim]Pack {current_id(cfg)} joined.[/]")
    scope = _all_scope(bound, config)
    steps_done: list[dict[str, Any]] = []
    chain_exit = 0
    from .agent_json import suppress_stdout

    try:
        for step in bound.steps:
            if step == "summarize" and dry_run:
                if not json_out:
                    console.print(
                        "[yellow]Skipping summarize — dry-run does not write summary notes.[/]"
                    )
                steps_done.append({"step": step, "status": "skipped"})
                continue
            if step == "summarize" and not cfg.llm_enabled:
                if bound.require_summarize:
                    steps_done.append({"step": step, "status": "failed", "exit": 1})
                    if json_out:
                        chain_exit = 1
                        break
                    console.print(
                        "[red]summarize needs llm.enabled = true "
                        "(--require-summarize).[/]"
                    )
                    raise typer.Exit(1)
                if not json_out:
                    console.print("[yellow]Skipping summarize — llm.enabled is false.[/]")
                steps_done.append({"step": step, "status": "skipped"})
                continue
            if not json_out:
                console.print(f"\n[bold]all[/] · {step}")
            try:
                if json_out:
                    with suppress_stdout():
                        _dispatch_all_step(
                            step,
                            bound,
                            scope,
                            dry_run=dry_run,
                            browser_agent=browser_agent,
                            serpapi_max=serpapi_max
                            if isinstance(serpapi_max, int)
                            else None,
                            json_out=True,
                        )
                else:
                    _dispatch_all_step(
                        step,
                        bound,
                        scope,
                        dry_run=dry_run,
                        browser_agent=browser_agent,
                        serpapi_max=serpapi_max if isinstance(serpapi_max, int) else None,
                    )
                steps_done.append({"step": step, "status": "ok"})
            except typer.Exit as exc:
                code = int(exc.exit_code or 0)
                if code in (0, None):
                    steps_done.append({"step": step, "status": "ok"})
                    continue
                steps_done.append({"step": step, "status": "failed", "exit": code})
                chain_exit = code
                if json_out:
                    break
                raise
    finally:
        if opened:
            try:
                closed = close_pack(cfg)
            except PackError:
                closed = None
            if closed is not None and not json_out:
                console.print(f"[dim]Pack {closed['id']} closed.[/]")
    from .agent_json import envelope

    payload = envelope(
        command="all",
        summary={"steps": len(steps_done), "failed": chain_exit != 0},
        items=steps_done,
        flags={"dry_run": dry_run},
        exit_code=chain_exit,
    )
    _emit_agent(payload, json_out=json_out, human=lambda: None)


def _dispatch_all_step(
    step: str,
    bound: ResolvedRunConfig,
    scope: dict[str, Any],
    *,
    dry_run: bool,
    browser_agent: bool | None = None,
    serpapi_max: int | None = None,
    json_out: bool = False,
) -> None:
    fmt = "json" if json_out else "text"
    if step == "gaps":
        _call_step(
            gaps,
            **scope,
            as_json=False,
            list_missing=False,
            handoff=None,
            include_doi_tabs=False,
            downloads_dir=None,
            request_rg=None,
            re_request=False,
            to=None,
            fmt=fmt,
        )
        return
    if step == "run":
        _call_step(
            run,
            **scope,
            dry_run=dry_run,
            limit=bound.limit,
            no_attach=bound.no_attach,
            retry_failed=bound.retry_failed,
            try_all=bound.try_all,
            sources=bound.sources_csv,
            preset=bound.preset,
            scihub=bound.scihub,
            browser_agent=browser_agent,
            upgrade_linked=bound.upgrade_linked,
            strict_pdf_doi=bound.strict_pdf_doi,
            handoff=None,
            include_doi_tabs=False,
            downloads_dir=None,
            request_rg=None,
            re_request=False,
            ezproxy_relogin=None,
            serpapi_max=serpapi_max,
            fmt=fmt,
        )
        return
    if step == "lint":
        _call_step(lint, **scope, limit=bound.limit, as_json=False, strict=False, fmt=fmt)
        return
    if step == "fix-metadata":
        _call_step(
            fix_metadata,
            **scope,
            limit=bound.limit,
            apply=False if dry_run else bound.apply,
            overwrite=bound.overwrite,
            fmt=fmt,
        )
        return
    if step == "ocr":
        _call_step(
            ocr,
            **scope,
            item=[],
            limit=bound.limit,
            apply=False if dry_run else bound.apply,
            attach=False,
            fmt=fmt,
        )
        return
    if step == "summarize":
        _call_step(
            summarize,
            **scope,
            item=[],
            limit=bound.limit,
            apply=bound.apply,
            to=None,
            prompt=None,
            force=False,
            fmt=fmt,
        )
        return
    if step == "snapshot":
        _call_step(snapshot, **scope, limit=bound.limit, dry_run=dry_run, pdfs=None)
        return
    if step == "dedupe":
        _call_step(
            dedupe,
            **scope,
            limit=bound.limit,
            dry_run=dry_run,
            apply=False if dry_run else bound.apply,
            apply_medium=False,
            phase="all",
            as_json=False,
            fmt=fmt,
        )
        return
    if step == "restore":
        _call_step(
            restore,
            **scope,
            limit=bound.limit,
            dry_run=dry_run,
            apply=False if dry_run else bound.apply,
            fmt=fmt,
        )
        return
    if step == "synthesize":
        _call_step(
            synthesize,
            **scope,
            item=[],
            to=None,
            report_collection=None,
            prompt=None,
            dry_run=dry_run,
            force=False,
            limit=bound.limit,
            fmt=fmt,
        )
        return
    console.print(f"[red]Unknown step {step!r}.[/]")
    raise typer.Exit(1)


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
) -> Any:
    from .snowball.command import SnowballRequest

    if twenty_writeback is not None:
        cfg.twenty_writeback_listings = twenty_writeback
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
        return Console(file=sys.stderr, highlight=False, quiet=True)
    return console


def _run_snowball(
    cfg: Config,
    action: Any,
    *,
    json_out: bool = False,
    command: str = "snowball",
) -> None:
    from .snowball.command import SnowballError
    from .agent_json import envelope

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
    summary = getattr(result, "summary", None) or {}
    if json_out:
        payload = envelope(
            command=command,
            summary=summary if isinstance(summary, dict) else {},
            paths={"run": str(result.run_dir)},
            exit_code=int(result.exit_code or 0),
        )
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
        min_seed_citations=min_seed_citations,
        note_provenance=note_provenance,
        backends=backends,
        refine=refine,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
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
        min_seed_citations=min_seed_citations,
        hybrid_seeds=hybrid_seeds,
        refine=refine,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
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
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
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
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
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
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
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
) -> None:
    """Write markdown from the inbox. Does not create items."""
    from .authorwatch import write_briefing

    cfg = _cfg(config)
    path = _authorwatch_call(lambda: write_briefing(cfg, name))
    console.print(f"Wrote [bold]{path}[/]")


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


if __name__ == "__main__":
    app()
