"""paperful command line."""

from __future__ import annotations

import json
import os
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
from .library import LibraryBackend, LibraryError, get_backend
from .pack import PackError, close_pack, current_id, open_pack, pack_join_disabled
from .pipeline import Pipeline, RunStats, make_client, session_expired_items
from .routing import (
    filter_sources_for_item_types,
    filter_sources_for_year_scope,
    sources_for_item,
    with_recover_lane,
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
        "Propose and promote learned PDF playbooks from local fetch wins. "
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
rag_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Library index behind `paperful ask`. Built from the on-disk mirror; "
        "it never calls the reference manager."
    ),
)
app.add_typer(rag_app, name="rag")

# Canonical top-level verbs. tests/test_cli.py asserts this matches `paperful --help`.
JOBS: dict[str, tuple[str, ...]] = {
    "library": ("collections", "import", "export", "snowball"),
    "find": ("run", "attach", "recover", "gaps", "inbox"),
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
        "all",
    ),
    "mirror": ("snapshot", "restore"),
    "control": (
        "doctor",
        "session",
        "mirrors",
        "ezproxy",
        "scholar",
        "pack",
        "profile",
        "playbooks",
    ),
    "utility": ("report", "version", "jobs"),
}

console = Console(highlight=False)

ConfigOpt = typer.Option(
    None, "--config", "-c", help="Path to config.toml", exists=True, dir_okay=False
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


def _open_library(cfg: Config) -> tuple[LibraryBackend | None, str]:
    """Live library, or (None, reason) when it is not reachable.

    A missing manager does not stop work that can stay on the local mirror.
    """
    manager = _manager_name(cfg)
    try:
        if manager == "zotero":
            zl = ZoteroLocal()
            info = zl.ping()
            console.print(
                f"[dim]Zotero {info.get('zotero_version') or '?'}, "
                f"local API v{info.get('api_version')}, write support: "
                f"{'yes' if info.get('supports_write') else 'no'}[/]"
            )
            return get_backend(cfg, zl), ""
        backend = get_backend(cfg)
        info = backend.ping()
        if manager == "mendeley":
            console.print(
                f"[dim]Mendeley {info.get('display_name') or '?'}, write support: yes[/]"
            )
        elif manager == "endnote":
            console.print(
                f"[dim]EndNote {info.get('library') or '?'}, "
                f"{info.get('refs', '?')} refs, writes via import bundle[/]"
            )
        return backend, ""
    except Exception as exc:
        return None, str(exc)


def _connect(cfg: Config, *, quiet: bool = False) -> LibraryBackend:
    manager = (cfg.manager or "zotero").strip().lower()
    if manager == "zotero":
        zl = _zotero(quiet=quiet)
        return get_backend(cfg, zl)
    try:
        backend = get_backend(cfg)
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


def _flush(backend: LibraryBackend) -> None:
    fn = getattr(backend, "flush_writes", None)
    if not callable(fn):
        return
    path = fn()
    if path is None:
        return
    console.print(f"[green]EndNote import bundle[/] {path}")
    console.print(
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
def _main() -> None:
    """paperful."""


@app.command()
def jobs() -> None:
    """List canonical verbs for the five jobs (library, find, completeness, mirror, control)."""
    for name, verbs in JOBS.items():
        console.print(f"[bold]{name}[/]: {', '.join(verbs)}")
    console.print(
        "Snowball grows the library (metadata parents). "
        "Run fills PDFs for items already there."
    )


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


@app.command()
def collections(config: Path | None = ConfigOpt) -> None:
    """Show the collection tree with item counts and how many lack a PDF."""
    cfg = _cfg(config)
    _require_manager(cfg)
    backend = _connect(cfg)
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
    as_json: bool = typer.Option(False, "--json", help="Machine-readable findings."),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any finding."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Read-only check of identifiers vs APIs and PDF text on disk. Does not write to the manager."""
    from rich.markup import escape

    from .lint import Finding, lint_items
    from .pipeline import make_client
    from .zot import Item

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
    backend = _connect(cfg, quiet=as_json)
    manifest = Manifest(cfg.manifest_path)
    partial: list[Finding] = []
    done = 0
    interrupted = False
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
    if not as_json:
        console.print(f"Scope: [bold]{scope}[/] — linting {len(items)} items")
    with _item_progress(json_out=as_json) as progress:
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
    if as_json:
        console.print(json.dumps([f.__dict__ for f in findings], indent=2))
    elif not findings:
        console.print("[green]No findings.[/]")
    else:
        table = Table(title=f"{len(findings)} findings")
        table.add_column("Code")
        table.add_column("Key", style="dim")
        table.add_column("Title")
        table.add_column("Detail")
        for f in findings:
            table.add_row(f.code, f.itemKey, f.title[:50], f.detail[:80])
        console.print(table)
    if interrupted:
        raise typer.Exit(130)
    if strict and findings:
        raise typer.Exit(1)


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
) -> None:
    """Propose bibliographic patches on disk; --apply writes them through the library adapter.

    `run` never rewrites metadata. This is the only write path for DOI/title/date/venue.
    """
    from .metadata import apply_patches, collect_patches, write_patches
    from .pipeline import make_client

    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
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
    backend = _connect(cfg)
    manifest = Manifest(cfg.manifest_path)
    client = make_client(cfg)
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
    started = time.time()
    with _item_progress() as progress:
        patches = collect_patches(
            client,
            cfg,
            items,
            backend=backend,
            manifest=manifest,
            overwrite=overwrite,
            track=_track(progress, "Checking metadata"),
        )
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
    write_patches(cfg.patches_path, patches)
    field_counts: dict[str, int] = {}
    for p in patches:
        for key in p.after:
            field_counts[key] = field_counts.get(key, 0) + 1
    console.print(f"[dim]Wrote {len(patches)} lines to {cfg.patches_path}[/]")
    if not apply:
        _print_fix_summary(len(patches), field_counts, applied=None, errors=[])
        console.print(
            "Dry-run. Pass [bold]--apply[/] to write these fields into the library."
        )
        _write_fix_report(
            cfg,
            scope,
            patches,
            field_counts,
            applied=None,
            errors=[],
            apply=False,
            started=started,
        )
        return
    if not backend.supports_write():
        _exit_env("This library has no write support.", cfg)
    try:
        with _item_progress() as progress:
            ok, errors = apply_patches(
                backend, patches, track=_track(progress, "Applying patches")
            )
    except LibraryError as exc:
        _exit_env(str(exc), cfg)
    _flush(backend)
    _print_fix_summary(len(patches), field_counts, applied=ok, errors=errors)
    _write_fix_report(
        cfg,
        scope,
        patches,
        field_counts,
        applied=ok,
        errors=errors,
        apply=True,
        started=started,
    )


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
        help="high_doi, medium_title_year, or all (default). Apply runs high_doi first.",
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
    items: list
    scope: str
    groups: list
    if as_json:
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
            _exit_env("This library has no write support.", cfg)
        from .remarks import remark_duplicates

        remark_duplicates(backend, groups, items, surface=cfg.remarks_surface)
        merge_n = merge_apply_total(groups, apply_medium=apply_medium)
        try:
            if as_json:
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
    if as_json:
        console.print(
            json.dumps(payload, indent=2), soft_wrap=True, highlight=False, markup=False
        )
    else:
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
    started = time.time()
    children = []
    mirrors: dict = {}
    stems: dict = {}
    with _item_progress(json_out=as_json) as progress:
        for item in _track(progress, "Scanning attachments")(items):
            raw = []
            try:
                raw = backend.children(item.key) or []
            except Exception:
                raw = []
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
    if apply and flags.any:
        refusal = apply_refusal(
            manager=cfg.manager,
            library_type=str(getattr(backend, "library_type", "user")),
            link=flags.link,
        )
        if refusal:
            errors.append(refusal)
        elif not backend.supports_write():
            _exit_env("This library has no write support.", cfg)
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
                _exit_env("This library has no write support.", cfg)
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
    to: Path | None = typer.Option(
        None,
        "--to",
        help="Write the missing-PDF list to a .tsv or .md file.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print counts as JSON."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
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
    started = time.time()
    counts = summarize_gaps(items)
    payload = {
        "scope": scope,
        "items": counts.items,
        "no_stored_pdf": counts.no_stored_pdf,
        "linked_url_only": counts.linked_url_only,
        "missing_doi": counts.missing_doi,
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
            "handoff": mode if list_missing else "",
        },
        items=rows,
        started=started,
    )
    if as_json and not list_missing:
        console.print(
            json.dumps(payload, indent=2), soft_wrap=True, highlight=False, markup=False
        )
        return
    if not as_json:
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
        console.print(table)

    if not list_missing:
        return

    manifest = Manifest(cfg.manifest_path)
    missing = list_missing_pdfs(items, manifest)
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
    else:
        t = Table(title=f"{len(missing)} missing PDFs")
        t.add_column("Key", style="dim")
        t.add_column("Title")
        t.add_column("DOI")
        t.add_column("URL")
        t.add_column("Hint")
        for row in missing:
            t.add_row(
                row.key,
                row.title[:50],
                row.doi or "-",
                (row.url or "-")[:48],
                row.hint,
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

        opened = open_tabs(missing, include_doi_tabs=include_doi_tabs, confirm=_confirm)
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
    dl = _gaps_downloads_dir(cfg, downloads_dir)
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


def _gaps_downloads_dir(cfg: Config, override: Path | None) -> Path:
    if override is not None:
        return override.expanduser()
    raw = (cfg.gaps_downloads_dir or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "Downloads"


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
    promote: str | None = typer.Option(
        None,
        "--promote",
        help="Override [playbooks].promote for this run: gated or auto.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Fill PDFs into the local mirror. Copies into the library when it is reachable. --dry-run does not write."""
    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
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
    # `all` calls this function directly. An omitted flag is a Typer option
    # object, not None; only an explicit bool overrides config.
    relogin = (
        ezproxy_relogin if isinstance(ezproxy_relogin, bool) else cfg.ezproxy_relogin
    )
    if not collection and not library:
        _refuse_missing_scope()
    _require_manager(cfg)
    source_list = _source_list(cfg, sources, scihub, preset)
    backend, offline_reason = _open_library(cfg)
    mirror_only = backend is None
    if mirror_only:
        manager = _manager_name(cfg)
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
    source_list = filter_sources_for_item_types(source_list, types)
    source_list = filter_sources_for_year_scope(source_list, year_from)
    source_list = with_recover_lane(cfg, source_list, during_run=browser_agent)
    _warn_if_scihub(source_list)
    _warn_if_recover(source_list)

    manifest = Manifest(cfg.manifest_path)
    item_filter = year_from is not None or year_to is not None or types is not None
    # One library listing. Year and type filters, the linked-URL skip count,
    # and the PDF todo all come from that list.
    if not mirror_only:
        assert backend is not None
        with _spinner("Loading items from library…"):
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
    items = items_without_stored_pdf(scoped, upgrade_linked=upgrade_linked)
    todo = [it for it in items if manifest.should_process(it.key, retry_failed)]
    skipped_manifest = len(items) - len(todo)
    if limit:
        todo = todo[:limit]
    linked_note = (
        f", {linked_skipped} linked URL only (skipped)" if linked_skipped else ""
    )
    console.print(
        f"Scope: [bold]{scope}[/] - {len(items)} items without PDF, {skipped_manifest} already handled, "
        f"{len(todo)} to process{linked_note}. Sources: {', '.join(source_list)}"
    )

    if dry_run:
        table = Table(title="Dry run", expand=True)
        table.add_column("Key", style="dim", no_wrap=True)
        table.add_column("Type", no_wrap=True, max_width=14)
        table.add_column("Item", no_wrap=True, overflow="ellipsis", ratio=3)
        table.add_column("DOI (source)", no_wrap=True, overflow="ellipsis", ratio=2)
        table.add_column("Would-hit", no_wrap=True, overflow="ellipsis", ratio=2)
        table.add_column("URL", no_wrap=True, overflow="ellipsis", ratio=1)
        table.add_column("Collections", no_wrap=True, overflow="ellipsis", ratio=1)
        for it in todo:
            if try_all or not cfg.source_routing:
                lanes = source_list
            else:
                lanes = sources_for_item(it, cfg, source_list)
            would = ", ".join(lanes) if lanes else "-"
            table.add_row(
                it.key,
                it.item_type,
                it.label,
                (
                    f"{it.doi} ({it.doi_source})"
                    if it.doi
                    else ("arXiv:" + it.arxiv_id if it.arxiv_id else "-")
                ),
                would,
                (it.url or "-")[:60],
                "; ".join(it.collection_paths),
            )
        console.print(table)
        if mirror_only:
            _mirror_deferred(cfg)
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
    pipe.on_ezproxy_down = _mid_run_ezproxy_hook(cfg, pipe, enabled=relogin)
    _preflight_ezproxy_session(cfg, pipe, source_list, enabled=relogin)
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
            _maybe_ezproxy_relogin(cfg, pipe, todo, enabled=relogin)
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
        )


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _ezproxy_headed_login_and_probe(cfg: Config, pipe: Pipeline) -> bool:
    """Open headed EZProxy login, refresh the vault, and probe. True when ready."""
    from . import session as sess
    from .sources import ezproxy as ez

    console.print("Opening a browser to refresh the EZProxy session.")
    # session_ok / mid-run fetches may already hold the vault profile. System
    # Chrome needs that user-data-dir exclusively or it exits with no window.
    pipe.release_browser()
    try:
        sess.login_headed(
            cfg,
            "ezproxy",
            confirm=_confirm_session_login,
            on_note=lambda msg: console.print(f"[dim]{msg}[/]"),
        )
    except sess.SessionError as exc:
        console.print(f"[red]{exc}[/]")
        console.print("Run [bold]paperful session login ezproxy[/] and retry.")
        return False
    pipe.refresh_session()
    ok, detail = ez.session_ok(pipe.ctx)
    if not ok:
        console.print(
            f"[yellow]EZProxy session still not ready ({detail}).[/] "
            "Run [bold]paperful session login ezproxy[/] and retry."
        )
        if pipe.browser is not None:
            pipe.browser.close()
        return False
    console.print("[green]EZProxy session ready.[/]")
    return True


def _ensure_ezproxy_session(
    cfg: Config,
    pipe: Pipeline,
    *,
    enabled: bool,
    prompt: str,
) -> bool:
    """Prompt for headed re-login and verify session_ok. Returns True if ready.

    Pauses the fetch progress Live first so the prompt (and headed-login
    Enter confirm) are not overwritten by the Rich bar.
    """
    if not enabled or not _stdin_is_tty():
        return False
    with pause_live(getattr(pipe, "live_progress", None)):
        try:
            answer = console.input(prompt).strip().lower()
        except EOFError:
            return False
        if answer not in {"", "y", "yes"}:
            console.print("[yellow]Skipping EZProxy re-login.[/]")
            return False
        return _ezproxy_headed_login_and_probe(cfg, pipe)


def _preflight_ezproxy_session(
    cfg: Config,
    pipe: Pipeline,
    source_list: list[str],
    *,
    enabled: bool,
) -> None:
    """Probe EZProxy before batch 1; offer login or skip wraps for this pass."""
    if "ezproxy" not in source_list or not cfg.ezproxy_base:
        return
    from .sources import ezproxy as ez

    ok, detail = ez.session_ok(pipe.ctx)
    if ok:
        return
    console.print(f"[yellow]EZProxy session not ready ({detail}).[/]")
    if _ensure_ezproxy_session(
        cfg,
        pipe,
        enabled=enabled,
        prompt="EZProxy session not ready — log in now? [Y/n] ",
    ):
        return
    pipe._ezproxy_down = True
    console.print(
        "[yellow]Continuing without EZProxy wraps for this pass.[/] "
        "Remaining proxy attempts will be skipped."
    )


def _mid_run_ezproxy_hook(
    cfg: Config, pipe: Pipeline, *, enabled: bool
) -> Callable[[], bool] | None:
    """Return a Pipeline.on_ezproxy_down callback, or None when mid-run pause is off."""
    if not enabled:
        return None

    def bound() -> bool:
        return _ensure_ezproxy_session(
            cfg,
            pipe,
            enabled=enabled,
            prompt="EZProxy session expired mid-run — re-login and continue? [Y/n] ",
        )

    return bound


def _maybe_ezproxy_relogin(
    cfg: Config,
    pipe: Pipeline,
    todo: list,
    *,
    enabled: bool,
) -> None:
    """Pause after the fetch so the operator can refresh an expired EZProxy session.

    The vault browser from the fetch is already closed. This opens a headed
    login, retries only ``retryable`` / ``session expired`` items, then closes
    that browser again. The report and ``--handoff`` tabs run after this
    returns, so manual-download tabs are not opened in the login window.
    Off, or not a terminal: leave those items for the next ``run``.
    """
    if not enabled or not _stdin_is_tty():
        return
    retry = session_expired_items(pipe.manifest, todo)
    if not retry:
        return
    n = len(retry)
    if not _ensure_ezproxy_session(
        cfg,
        pipe,
        enabled=True,
        prompt=f"Re-login and retry {n} EZProxy item(s)? [Y/n] ",
    ):
        return
    console.print(f"Retrying {n} item(s).")
    saved_sources = list(pipe.sources)
    saved_progress = pipe.progress
    pipe.sources = ["ezproxy"]
    pipe.stats.drop_outcomes({it.key for it in retry})
    try:
        with _item_progress() as progress:
            task_id = progress.add_task("EZProxy retry", total=n)
            pipe.progress = lambda: progress.advance(task_id)
            pipe.run(retry)
    finally:
        pipe.sources = saved_sources
        pipe.progress = saved_progress
        if pipe.browser is not None:
            pipe.browser.close()


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
) -> None:
    from .handoff import (
        missing_from_run_outcomes,
        open_tabs,
        parse_handoff,
        walk_missing,
    )

    try:
        mode = parse_handoff(handoff)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return
    if mode == "list":
        return
    outcomes = [
        {
            "itemKey": o.itemKey,
            "status": o.status,
            "reason": o.reason,
            "attempts": list(o.attempts or []),
        }
        for o in stats.items
    ]
    by_key = {it.key: it for it in catalog}
    missing = missing_from_run_outcomes(by_key, outcomes)
    if not missing:
        console.print("[dim]No openable soft-blocked PDFs to hand off.[/]")
        return
    console.print(f"[bold]Handoff[/] ({mode}): {len(missing)} openable miss(es)")
    if mode in {"tabs", "watch"}:

        def _confirm(n: int) -> bool:
            answer = (
                typer.prompt(f"Open {n} tabs in your browser?", default="y")
                .strip()
                .lower()
            )
            return answer in {"y", "yes"}

        opened = open_tabs(missing, include_doi_tabs=include_doi_tabs, confirm=_confirm)
        console.print(f"Opened {opened} tab(s).")
        enter_watch = mode == "watch" or (
            mode == "tabs"
            and cfg.inbox_watch_after_handoff
            and cfg.inbox_path is not None
        )
        if not enter_watch:
            return
        if backend is None or not backend.supports_write():
            console.print(
                "[yellow]--handoff watch needs a writable library; skipped.[/]"
            )
            return
        _inbox_handoff_session(
            cfg,
            backend,
            manifest,
            catalog,
            missing,
            scope="run handoff",
            once=False,
        )
        return
    if backend is None or not backend.supports_write():
        console.print("[yellow]--handoff walk needs a writable library; skipped.[/]")
        return
    dl = _gaps_downloads_dir(cfg, downloads_dir)
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
    """Openable-miss session: poll ``[inbox].dir``, match DOI then FIFO, report."""
    from .inbox import (
        ensure_inbox_dirs,
        events_as_report_items,
        fifo_from_missing,
        process_candidates,
        summary_from_stats,
    )

    started = time.time()
    try:
        root = ensure_inbox_dirs(cfg)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(
        f"[bold]Inbox[/] watching {root} "
        f"(DOI match"
        + ("; FIFO for openable misses" if use_fifo else "")
        + "; Ctrl+C to stop)"
    )
    fifo = fifo_from_missing(missing) if use_fifo else None
    stats = process_candidates(
        cfg,
        backend,
        manifest,
        list(items),
        fifo_queue=fifo,
        once=once,
        idle_seconds=idle_seconds,
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
        flags={"once": once, "fifo": use_fifo},
        started=started,
        extra_paths={"inbox_dir": str(root)},
    )
    console.print(
        f"Inbox attached {stats.attached}, unmatched {stats.unmatched}, "
        f"errors {stats.errors}, skipped {stats.skipped}"
        + (f" ({stats.quit_reason})" if stats.quit_reason else "")
    )
    if path is not None:
        console.print(f"Inbox report: {path}")


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


def _finish_run(
    cfg: Config,
    stats: RunStats,
    *,
    scope: str,
    flags: dict,
    write_api: bool | None = None,
) -> None:
    report = build_report(
        stats, cfg, command="run", scope=scope, flags=flags, write_api=write_api
    )
    path = write_run_report(cfg, report)
    print_run_summary(console, report, path)


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
        _exit_env("This library has no write support.", cfg)

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
) -> None:
    """One-shot: ingest current PDFs in inbox.dir (DOI match only).

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
        _exit_env("inbox drain needs library write support.", cfg)
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
    console.print(f"[bold]Inbox[/] draining {root} for {scope}")
    stats = process_candidates(
        cfg,
        backend,
        manifest,
        items,
        fifo_queue=None,
        once=True,
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
        flags={"once": True, "fifo": False},
        started=started,
        extra_paths={"inbox_dir": str(root)},
    )
    console.print(
        f"Inbox attached {stats.attached}, unmatched {stats.unmatched}, "
        f"errors {stats.errors}, skipped {stats.skipped}"
    )
    if path is not None:
        console.print(f"Inbox report: {path}")


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
        help="additional (fetched PDFs only), all (also export Zotero PDFs), or none.",
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
    if not dry_run:
        # Exports do not go through the manifest, so name the items.
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
) -> None:
    """Recreate missing library items from out/. Dry-run unless --apply. Never overwrites fields."""
    from .restore import apply_restore, iter_records, plan_restore, record_in_scope

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
    backend = _connect(cfg)
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
    with _spinner("Loading items from library…"):
        library_items = backend.items_in_scope(keys)
    with _item_progress() as progress:
        note_tags: dict[str, set[str]] = {}
        for it in _track(progress, "Reading library notes")(library_items):
            tags: set[str] = set()
            for ch in backend.children(it.key):
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
    console.print(
        f"{len(records)} restore folder(s) · "
        f"create {counts.get('create_item', 0)} · "
        f"exists {counts.get('exists', 0)} · "
        f"attach {counts.get('attach_pdf', 0)} · "
        f"notes {counts.get('create_note', 0)}"
    )
    if not apply:
        console.print(
            "[dim]Dry run. Pass --apply to write missing items into the library.[/]"
        )
        return
    with _item_progress() as progress:
        done = apply_restore(
            planned, backend, backend, track=_track(progress, "Restoring items")
        )
    console.print(
        f"[bold]created {done['create_item']}[/] · "
        f"attached {done['attach_pdf']} · notes {done['create_note']}"
    )
    _flush(backend)


@app.command("import")
def import_library(
    path: Path = typer.Argument(
        ..., exists=True, dir_okay=False, help="RIS, BibTeX, or EndNote XML file."
    ),
    fmt: str | None = typer.Option(
        None,
        "--format",
        help="ris, bibtex, or endnote-xml. Default: detect from the file.",
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
    try:
        records = load_records(path, fmt)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(f"{len(records)} record(s) in {path.name}")
    if not apply:
        n_pdf = sum(1 for r in records if r.get("pdfs"))
        n_notes = sum(len(r.get("notes") or []) for r in records)
        console.print(
            f"[dim]Dry run. Pass --apply to create {len(records)} items, "
            f"attach {n_pdf} PDF path(s), add {n_notes} note(s).[/]"
        )
        return
    backend = _connect(cfg)
    if not backend.supports_write():
        _exit_env("This library has no write support.", cfg)
    with _item_progress() as progress:
        done = apply_import(
            records, backend, dry_run=False, track=_track(progress, "Importing records")
        )
    console.print(
        f"[bold]created {done['create']}[/] · attached {done['attach']} · "
        f"notes {done['notes']}"
        + (f" · missing PDFs {done['skipped_pdf']}" if done.get("skipped_pdf") else "")
    )
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
                exported = backend.export_pdf(it, target)
                if exported is not None and Path(exported).is_file():
                    pdf_list.append(str(exported))
                    copied += 1
            rec["pdfs"] = pdf_list
            notes = []
            for ch in backend.children(it.key):
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
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show start URL only; no browser agent."
    ),
    no_attach: bool = typer.Option(
        False, "--no-attach", help="Download to out/ only; do not attach in Zotero."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Browser-agent PDF recovery for named items (also auto-fires at the end of run)."""
    from .browser_agent import recover_start_url
    from .llm import llm_egress_is_remote
    from .llm.preflight import validate_llm_for_recover
    from .llm.validate import LlmConfigError

    if not item:
        console.print("[red]Give at least one --item KEY.[/]")
        raise typer.Exit(1)
    if sys.version_info < (3, 11):
        console.print(
            "[red]recover requires Python 3.11+ for browser-use.[/] "
            f"This interpreter is {sys.version_info.major}.{sys.version_info.minor}."
        )
        raise typer.Exit(1)
    cfg = _cfg(config)
    _require_manager(cfg)
    try:
        validate_llm_for_recover(cfg)
    except LlmConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(f"[orange3]{RECOVER_DISCLAIMER}[/]")
    if llm_egress_is_remote(cfg):
        console.print(
            "[orange3]Remote LLM provider — page text may leave this machine.[/]"
        )
    backend = _connect(cfg)
    manifest = Manifest(cfg.manifest_path)
    todo: list = []
    for key in item:
        it = backend.get_item(key)
        if it is None:
            console.print(f"[red]Unknown item key {key}[/]")
            raise typer.Exit(1)
        if it.has_pdf and not dry_run:
            console.print(f"[dim]Skipping {key} — already has PDF[/]")
            continue
        url = recover_start_url(it)
        if not url:
            console.print(f"[red]{key}: no DOI or URL[/]")
            raise typer.Exit(1)
        if dry_run:
            console.print(f"[bold]{key}[/] would recover from {url}")
            continue
        todo.append(it)
    if dry_run or not todo:
        raise typer.Exit(0)
    attacher = None if no_attach else backend
    if attacher and not backend.supports_write():
        _exit_env("Write support required to attach.", cfg)
    with _item_progress() as progress:
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
        scope=f"items:{','.join(item)}",
        flags=_run_flags(no_attach=no_attach),
    )
    path = write_run_report(cfg, report)
    print_run_summary(console, report, path)
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
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
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
    backend = _connect(cfg)
    if attach and not backend.supports_write():
        _exit_env("Write support required to attach.", cfg)
    manifest = Manifest(cfg.manifest_path)
    loaded = _load_scope(
        backend,
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
    if not items:
        console.print("[yellow]No items with PDFs in scope.[/]")
        write_command_report(
            cfg,
            command="ocr",
            scope=scope,
            summary={"ocr": 0, "skipped": 0, "failed": 0, "would": 0},
            items=[],
            flags={"apply": apply, "attach": attach},
            started=started,
        )
        raise typer.Exit(0)
    try:
        with _item_progress() as progress:
            batch = ocr_items(
                cfg,
                items,
                manifest,
                backend,
                apply=apply,
                attach=attach,
                track=_track(progress, "Running OCR" if apply else "Checking PDFs"),
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
    if batch.would or batch.ocr or batch.failed:
        console.print(table)
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
        },
        items=outcomes,
        flags={"apply": apply, "attach": attach},
        started=started,
    )
    if apply:
        console.print(
            f"OCR {batch.ocr}, skipped {batch.skipped}, failed {batch.failed}."
        )
    else:
        console.print(
            f"Would OCR {batch.would}, skip {batch.skipped} "
            f"(already have text). Pass --apply to write the text layer."
        )
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


def _ask_once(
    cfg: Config,
    question: str,
    *,
    stream: bool,
    show_context: bool,
    **retrieval: Any,
) -> dict[str, Any]:
    """Answer one question on the terminal and return it for the run report."""
    from .rag.answer import answer

    reply = answer(cfg, question, **retrieval)
    if show_context and reply.hits:
        console.print("[bold]Passages[/]")
        _print_hits(reply.hits)
        console.print()
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
    no_stream: bool = typer.Option(
        False, "--no-stream", help="Print the answer when it is complete."
    ),
    show_context: bool = typer.Option(
        False, "--show-context", help="List the passages the answer is built from."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Answer a question from the indexed library, with sources. Needs `rag ingest` first."""
    from .llm import LLMClientError, get_client, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_ask
    from .llm.validate import LlmConfigError
    from .rag.retrieve import scope_keys

    cfg = _cfg(config)
    _rag_require(cfg)
    try:
        validate_llm_for_ask(cfg)
    except LlmConfigError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    types = _resolve_types(item_type)
    embedder = _rag_embedder(cfg)
    if llm_egress_is_remote(cfg):
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
    answered: list[dict[str, Any]] = []
    failures = 0
    for asked in _ask_questions(question):
        try:
            answered.append(
                _ask_once(
                    cfg,
                    asked,
                    stream=not no_stream,
                    show_context=show_context,
                    k=top_k,
                    keys=keys,
                    client=client,
                    embedder=embedder,
                    index=index,
                    ledger=ledger,
                )
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled.[/]")
            failures += 1
        except LLMClientError as exc:
            console.print()
            console.print(str(exc), markup=False, style="red")
            failures += 1
        if question is None:
            console.print()
    if answered or failures:
        write_command_report(
            cfg,
            command="ask",
            scope=", ".join(collection) or "index",
            summary={"questions": len(answered) + failures, "answered": len(answered)},
            items=answered,
            flags={
                "top_k": top_k or cfg.rag_top_k,
                "model": cfg.rag_model or cfg.llm_model,
                "embed_model": cfg.rag_embed_model,
            },
            started=started,
        )
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
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
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
    backend = _connect(cfg)
    manifest = Manifest(cfg.manifest_path)
    loaded = _load_scope(
        backend,
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

    def _finish(
        outcomes: list[dict], summarized: int, failed: int, skipped: int
    ) -> None:
        write_command_report(
            cfg,
            command="summarize",
            scope=scope,
            summary={
                "summarized": summarized,
                "failed": failed,
                "skipped": skipped,
                "dest": dest,
                "order": queue_order,
            },
            items=outcomes,
            flags={"to": dest, "order": queue_order},
            started=started,
        )

    def _show(row: SummaryRow) -> None:
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
        console.print("[yellow]No items with PDFs in scope.[/]")
        _finish([], 0, 0, 0)
        raise typer.Exit(0)
    with _item_progress() as progress:
        batch = summarize_items(
            cfg,
            items,
            manifest,
            backend,
            dest=dest,
            force=force,
            on_row=_show,
            track=_track(progress, "Summarizing"),
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
    _finish(outcomes, batch.summarized, batch.failed, batch.skipped)
    if batch.fatal:
        console.print(f"[red]{batch.fatal}[/]")
        raise typer.Exit(1)
    where = cfg.summaries_dir if wants_disk(dest) else "Zotero"
    console.print(f"Summarized {batch.summarized}/{len(items)} items under {where}")
    if batch.skipped:
        console.print(
            f"Skipped {batch.skipped} already summarized for this model "
            "(pass --force to redo)."
        )
    if dest == "disk":
        console.print("Zotero not written (dest=disk).")
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
    backend = _connect(cfg)
    loaded = _load_scope(
        backend,
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
    with _item_progress() as progress:
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
        with _spinner("Writing the report…"):
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
    console.print(
        f"Synthesized {len(sources)} summaries ({len(missing)} not included) → {path}"
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
    label: str | None = typer.Option(
        None, "--label", help="Pack label when this command opens a pack."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Run gaps, then fetch, lint, fix-metadata --apply, and summarize --apply.

    Stops on the first failing step, same as chaining the commands with ``&&``.
    """
    if _scope_unset(collection, library, profile, run_config):
        _refuse_missing_scope()
    cfg = _cfg(config)
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
        console.print("[dim]PAPERFUL_PACK=off — reports are not grouped.[/]")
    elif current_id(cfg) is None:
        try:
            pack = open_pack(cfg, label=label or bound.name or "all")
        except PackError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
        opened = True
        console.print(f"[dim]Pack {pack['id']} opened.[/]")
    else:
        console.print(f"[dim]Pack {current_id(cfg)} joined.[/]")
    scope = _all_scope(bound, config)
    try:
        for step in bound.steps:
            if step == "summarize" and dry_run:
                console.print(
                    "[yellow]Skipping summarize — dry-run does not write summary notes.[/]"
                )
                continue
            if step == "summarize" and not cfg.llm_enabled:
                if bound.require_summarize:
                    console.print(
                        "[red]summarize needs llm.enabled = true "
                        "(--require-summarize).[/]"
                    )
                    raise typer.Exit(1)
                console.print("[yellow]Skipping summarize — llm.enabled is false.[/]")
                continue
            console.print(f"\n[bold]all[/] · {step}")
            _dispatch_all_step(
                step, bound, scope, dry_run=dry_run, browser_agent=browser_agent
            )
    finally:
        if opened:
            try:
                closed = close_pack(cfg)
            except PackError:
                closed = None
            if closed is not None:
                console.print(f"[dim]Pack {closed['id']} closed.[/]")


def _dispatch_all_step(
    step: str,
    bound: ResolvedRunConfig,
    scope: dict[str, Any],
    *,
    dry_run: bool,
    browser_agent: bool | None = None,
) -> None:
    if step == "gaps":
        _call_step(
            gaps,
            **scope,
            as_json=False,
            list_missing=False,
            handoff=None,
            include_doi_tabs=False,
            downloads_dir=None,
            to=None,
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
            ezproxy_relogin=None,
        )
        return
    if step == "lint":
        _call_step(lint, **scope, limit=bound.limit, as_json=False, strict=False)
        return
    if step == "fix-metadata":
        _call_step(
            fix_metadata,
            **scope,
            limit=bound.limit,
            apply=False if dry_run else bound.apply,
            overwrite=bound.overwrite,
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
        )
        return
    if step == "restore":
        _call_step(
            restore,
            **scope,
            limit=bound.limit,
            dry_run=dry_run,
            apply=False if dry_run else bound.apply,
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
) -> Any:
    from .snowball.command import SnowballRequest

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
    )


def _csv(raw: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (raw or "").split(",") if part.strip())


def _profile_queries(body: dict[str, Any], queries: list[str], *, or_mode: bool) -> None:
    """Persist one ``query`` or a ``queries`` array (+ optional ``query_op``)."""
    if len(queries) == 1:
        body["query"] = queries[0]
    else:
        body["queries"] = list(queries)
    if or_mode:
        body["query_op"] = "or"

def _run_snowball(cfg: Config, action: Any) -> None:
    from .snowball.command import SnowballError

    snowball_started = time.time()
    try:
        result = action(cfg)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _rag_auto(cfg, snowball_started)
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
    config: Path | None = ConfigOpt,
) -> None:
    """Search OpenAlex and write a candidate queue. Creates items only with --gate auto."""
    cfg = _cfg(config)
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
    )
    from .snowball.command import run_search
    from .snowball.expand import compose_keyword_query

    try:
        query = compose_keyword_query(queries, op="or" if or_mode else "and")
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    _run_snowball(cfg, lambda c: run_search(c, query, request, console=console))


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
    config: Path | None = ConfigOpt,
) -> None:
    """Keyword hits, then one hop from the top DOIs. Not a separate harvest command."""
    cfg = _cfg(config)
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
    )
    from .snowball.command import run_hybrid
    from .snowball.expand import compose_keyword_query

    try:
        query = compose_keyword_query(queries, op="or" if or_mode else "and")
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    _run_snowball(cfg, lambda c: run_hybrid(c, query, request, console=console))


@snowball_app.command("doi")
def snowball_doi(
    dois: list[str] = typer.Argument(..., help="One or more seed DOIs."),
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
    config: Path | None = ConfigOpt,
) -> None:
    """Bibliography and/or citing works of each DOI. Creates items only with --gate auto."""
    cfg = _cfg(config)
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
    )
    from .snowball.command import run_doi

    _run_snowball(cfg, lambda c: run_doi(c, dois, request, console=console))


@snowball_app.command("orcid")
def snowball_orcid(
    orcids: list[str] = typer.Argument(..., help="One or more ORCID iDs."),
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
    config: Path | None = ConfigOpt,
) -> None:
    """People's works (ORCID + OpenAlex), then references/citations those works expand to."""
    cfg = _cfg(config)
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
    )
    from .snowball.command import run_orcid

    _run_snowball(cfg, lambda c: run_orcid(c, orcids, request, console=console))


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
    config: Path | None = ConfigOpt,
) -> None:
    """Expand DOIs already in a collection. Creates items only with --gate auto."""
    cfg = _cfg(config)
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
    )
    from .snowball.command import run_collection

    _run_snowball(
        cfg, lambda c: run_collection(c, seed_collection, request, console=console)
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
    config: Path | None = ConfigOpt,
) -> None:
    """Continue OpenAlex work saved when the daily budget was spent. Same API key."""
    cfg = _cfg(config)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=None,
        depth=None,
        max_candidates=None,
        year_from=None,
        year_to=None,
    )
    from .snowball.command import run_resume

    _run_snowball(cfg, lambda c: run_resume(c, run_id, request, console=console))


@snowball_app.command("apply")
def snowball_apply(
    run_id: str = typer.Argument(..., help="Run id under state/snowball/<run-id>/."),
    collection: str = typer.Option("", "--collection", "-C", help="Target collection."),
    fetch_pdfs: str | None = FetchPdfsOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Create keep=true rows from a prior queue (approve-batch or edited dry-run)."""
    cfg = _cfg(config)
    request = _snowball_request(
        cfg,
        gate="auto",
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=None,
        max_candidates=None,
        year_from=None,
        year_to=None,
    )
    from .snowball.command import run_apply

    _run_snowball(cfg, lambda c: run_apply(c, run_id, request, console=console))


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
    config: Path | None = ConfigOpt,
) -> None:
    """Run a saved snowball profile (keyword, DOI, ORCID, or collection)."""
    cfg = _cfg(config)
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
        description = str(raw.get("description") or "").strip()
        if description:
            console.print(description)
        mode = str(raw.get("mode") or "")
        if mode == "search":
            query = composed_query_from_profile(raw)
            action = lambda c: run_search(c, query, request, console=console)
        elif mode == "hybrid":
            query = composed_query_from_profile(raw)
            action = lambda c: run_hybrid(c, query, request, console=console)
        elif mode == "doi":
            dois = [str(item) for item in (raw.get("dois") or [])]
            action = lambda c: run_doi(c, dois, request, console=console)
        elif mode == "orcid":
            from .snowball.profile import orcids_from_profile

            orcids = orcids_from_profile(raw)
            if not orcids:
                raise SnowballError(f"Profile {profile!r} needs orcid or orcids.")
            action = lambda c: run_orcid(c, orcids, request, console=console)
        elif mode == "collection":
            seed = str(
                raw.get("seed_collection") or raw.get("collection") or ""
            ).strip()
            if not seed:
                raise SnowballError(f"Profile {profile!r} needs seed_collection.")
            if not request.collection.strip():
                request.collection = seed
            action = lambda c: run_collection(c, seed, request, console=console)
        else:
            raise SnowballError(
                f"Profile {profile!r} mode must be search, hybrid, doi, orcid, or collection."
            )
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _run_snowball(cfg, action)


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
    config: Path | None = ConfigOpt,
) -> None:
    """Baseline on first run; later runs write only unseen new works to the inbox."""
    cfg = _cfg(config)
    from .snowball.watch import run_watch

    _run_snowball(cfg, lambda c: run_watch(c, name, console=console))


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


if __name__ == "__main__":
    app()
