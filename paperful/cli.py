"""paperful command line."""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from . import __version__
from .attach import Attacher
from .config import SCIHUB_DISCLAIMER, SOURCE_PRESETS, Config, load_config
from .doctor import has_red, run_checks
from .library import LibraryError, get_backend
from .pipeline import Pipeline, RunStats, make_client
from .routing import sources_for_item
from .runreport import build_report, print_run_summary, write_run_report
from .sources import Context
from .sources.scihub import ping_mirrors
from .store import STATUS_ATTACHED, STATUS_NOT_FOUND, Manifest
from .zot import ZoteroLocal

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Fetch missing PDFs for Zotero items.",
)
session_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Local browser session vault for Scholar, EZProxy, and publishers.",
)
app.add_typer(session_app, name="session")
console = Console(highlight=False)

ConfigOpt = typer.Option(
    None, "--config", "-c", help="Path to config.toml", exists=True, dir_okay=False
)


def _item_progress() -> Progress:
    """Live bar that stays below scrolling per-item logs."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )


def _cfg(path: Path | None) -> Config:
    cfg = load_config(path)
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
        _exit_env(f"Cannot reach Zotero local API at localhost:23119: {exc}")
    if not quiet:
        console.print(
            f"[dim]Zotero {info.get('zotero_version') or '?'}, local API v{info['api_version']}, write support: "
            f"{'yes' if info['supports_write'] else 'no (Zotero 10+ needed)'}[/]"
        )
    return zl


def _print_exit_ladder() -> None:
    console.print(
        "\n[bold]Next steps[/]\n"
        "  1. Start Zotero on this machine.\n"
        "  2. Settings → Advanced → enable the local API.\n"
        "  3. Run [bold]paperful doctor[/] for a full check.\n"
        "  4. If you have no config yet: [bold]cp config.example.toml config.toml[/] and set email.\n"
    )


def _exit_env(message: str) -> None:
    console.print(f"[red]{message}[/]")
    _print_exit_ladder()
    raise typer.Exit(2)


def _warn_if_scihub(source_list: list[str]) -> None:
    if "scihub" in source_list:
        console.print(f"[yellow]{SCIHUB_DISCLAIMER}[/]")


def _require_manager(cfg: Config) -> None:
    if (cfg.manager or "zotero").strip().lower() != "zotero":
        console.print(
            f'[red]manager={cfg.manager!r} is not implemented.[/] Set manager = "zotero" '
            "(Mendeley write-back comes later)."
        )
        raise typer.Exit(1)


def _scope_keys(
    zl: ZoteroLocal, collection: list[str], library: bool
) -> tuple[list[str] | None, str]:
    if library:
        return None, "whole library"
    keys: list[str] = []
    for spec in collection:
        try:
            root = zl.resolve_collection(spec)
        except LookupError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1)
        keys.extend(zl.subtree_keys(root))
    return keys, ", ".join(collection)


@app.callback()
def _main() -> None:
    """paperful."""


@app.command()
def version() -> None:
    console.print(__version__)


@app.command()
def doctor(config: Path | None = ConfigOpt) -> None:
    """Check Zotero, paths, email, and optional browser sessions (green / amber / red)."""
    cfg = _cfg(config)
    zl: ZoteroLocal | None = None
    try:
        zl = ZoteroLocal()
        checks = run_checks(cfg, zl)
    except Exception:
        checks = run_checks(cfg, None)

    table = Table(title="paperful doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    colour = {"green": "green", "amber": "yellow", "red": "red"}
    for ch in checks:
        table.add_row(ch.name, f"[{colour[ch.status]}]{ch.status}[/]", ch.detail)
    console.print(table)
    if has_red(checks):
        _print_exit_ladder()
        raise typer.Exit(2)


@app.command()
def collections(config: Path | None = ConfigOpt) -> None:
    """Show the collection tree with item counts and how many lack a PDF."""
    cfg = _cfg(config)
    _require_manager(cfg)
    zl = _zotero()
    cols = zl.collections()
    counts = zl.collection_counts()
    table = Table(title="Zotero collections (counts include subcollections)")
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
    library: bool = typer.Option(
        False, "--library", help="Whole library instead of collections."
    ),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable findings."),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any finding."),
    config: Path | None = ConfigOpt,
) -> None:
    """Read-only check of identifiers vs APIs and PDF text on disk. Does not write to the manager."""
    from .lint import lint_items
    from .pipeline import make_client

    if not collection and not library:
        console.print("[red]Give --collection PATH (repeatable) or --library.[/]")
        raise typer.Exit(1)
    cfg = _cfg(config)
    _require_manager(cfg)
    zl = _zotero(quiet=as_json)
    keys, scope = _scope_keys(zl, collection, library)
    backend = get_backend(cfg, zl)
    items = backend.items_in_scope(keys)
    if limit:
        items = items[:limit]
    manifest = Manifest(cfg.manifest_path)
    if not as_json:
        console.print(f"Scope: [bold]{scope}[/] — linting {len(items)} items")
    findings = lint_items(
        make_client(cfg), cfg, items, backend=backend, manifest=manifest
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
    if strict and findings:
        raise typer.Exit(1)


@app.command("fix-metadata")
def fix_metadata(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool = typer.Option(
        False, "--library", help="Whole library instead of collections."
    ),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    apply: bool = typer.Option(
        False, "--apply", help="Write patches to the library (default is dry-run)."
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace title/date/venue even when already set."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Propose bibliographic patches on disk; --apply writes them through the library adapter.

    `run` never rewrites metadata. This is the only write path for DOI/title/date/venue.
    """
    from .lint import lint_item
    from .metadata import apply_patches, propose_patch, write_patches
    from .pipeline import make_client
    from .resolve import IdentifierCache

    if not collection and not library:
        console.print("[red]Give --collection PATH (repeatable) or --library.[/]")
        raise typer.Exit(1)
    cfg = _cfg(config)
    _require_manager(cfg)
    zl = _zotero()
    keys, scope = _scope_keys(zl, collection, library)
    backend = get_backend(cfg, zl)
    items = backend.items_in_scope(keys)
    if limit:
        items = items[:limit]
    manifest = Manifest(cfg.manifest_path)
    client = make_client(cfg)
    cache = IdentifierCache()
    patches = []
    for item in items:
        findings = lint_item(
            client, cfg, item, backend=backend, manifest=manifest, cache=cache
        )
        patch = propose_patch(
            client, cfg, item, findings, overwrite=overwrite, cache=cache
        )
        if patch:
            patches.append(patch)
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
        return
    if not backend.supports_write():
        _exit_env(
            "This Zotero has no local write API. Upgrade to Zotero 10+ to apply metadata."
        )
    try:
        ok, errors = apply_patches(backend, patches)
    except LibraryError as exc:
        _exit_env(str(exc))
    _print_fix_summary(len(patches), field_counts, applied=ok, errors=errors)
    _write_fix_report(cfg, scope, patches, field_counts, applied=ok, errors=errors)


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
    applied: int,
    errors: list[str],
) -> None:
    from .runreport import write_run_report

    report = {
        "schema": "paperful.run_report.v1",
        "command": "fix-metadata",
        "scope": scope,
        "summary": {
            "fields_corrected": sum(field_counts.values()),
            "fields_corrected_by_kind": field_counts,
            "patches_proposed": len(patches),
            "patches_applied": applied,
            "errors_by_type": {"apply_failed": len(errors)} if errors else {},
            "pdfs_downloaded": 0,
            "sources_checked": {},
        },
        "items": [
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
        "errors": errors,
        "paths": {"state_dir": str(cfg.state_dir), "patches": str(cfg.patches_path)},
    }
    write_run_report(cfg, report, as_last_run=False)


@app.command()
def run(
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Collection path/name/key (repeatable). Subcollections included.",
    ),
    library: bool = typer.Option(
        False, "--library", help="Whole library instead of collections."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List what would be fetched; no network beyond Zotero."
    ),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    no_attach: bool = typer.Option(
        False, "--no-attach", help="Do not attach PDFs into Zotero."
    ),
    retry_failed: bool = typer.Option(
        False, "--retry-failed", help="Retry items previously marked not_found."
    ),
    try_all: bool = typer.Option(
        False,
        "--try-all",
        help="Try every configured source even when item metadata looks inapplicable (overrides source_routing).",
    ),
    sources: str | None = typer.Option(
        None,
        "--sources",
        help="Comma-separated source order override (or preset name eoi).",
    ),
    preset: str | None = typer.Option(
        None,
        "--preset",
        help="Named source preset (eoi = OA + EZProxy, no Scholar or Sci-Hub).",
    ),
    scihub: bool = typer.Option(
        False,
        "--scihub",
        help="Opt in to Sci-Hub for this run (off by default; legal grey zone in some jurisdictions).",
    ),
    upgrade_linked: bool = typer.Option(
        False,
        "--upgrade-linked",
        help="Also fetch items that only have a linked PDF URL in Zotero (adds imported_file).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Find and download PDFs for items lacking one, then attach them."""
    if not collection and not library:
        console.print("[red]Give --collection PATH (repeatable) or --library.[/]")
        raise typer.Exit(1)
    cfg = _cfg(config)
    _require_manager(cfg)
    source_list = _source_list(cfg, sources, scihub, preset)
    _warn_if_scihub(source_list)
    zl = _zotero()

    keys, scope = _scope_keys(zl, collection, library)

    manifest = Manifest(cfg.manifest_path)
    linked_skipped = 0 if upgrade_linked else zl.count_linked_url_only(keys)
    items = zl.items_lacking_pdf(keys, upgrade_linked=upgrade_linked)
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
        raise typer.Exit(0)

    attacher: Attacher | None = None
    if cfg.attach and not no_attach:
        attacher = Attacher(cfg, zl)
        if not attacher.supports_write():
            console.print(
                "[yellow]Attach disabled: this Zotero has no local write API (upgrade to Zotero 10+). PDFs still saved to disk.[/]"
            )
            attacher = None

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
            flags=_run_flags(
                dry_run=False,
                no_attach=no_attach,
                retry_failed=retry_failed,
                try_all=try_all,
                upgrade_linked=upgrade_linked,
                scihub=scihub,
                preset=preset,
                sources=sources,
            ),
        )
        return

    with _item_progress() as progress:
        task_id = progress.add_task("Fetching PDFs", total=len(todo))
        pipe = Pipeline(
            cfg,
            manifest,
            console,
            sources=source_list,
            attacher=attacher,
            progress=lambda: progress.advance(task_id),
            try_all=True if try_all else None,
        )
        try:
            stats = pipe.run(todo)
        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Interrupted - progress is in the manifest; rerun to resume.[/]"
            )
            stats = pipe.stats
            if not stats.finished_at:
                stats.finished_at = time.time()
    stats.skipped_manifest = skipped_manifest
    stats.linked_url_skipped = linked_skipped
    stats.scope = scope
    _finish_run(
        cfg,
        stats,
        scope=scope,
        flags=_run_flags(
            dry_run=False,
            no_attach=no_attach,
            retry_failed=retry_failed,
            try_all=try_all,
            upgrade_linked=upgrade_linked,
            scihub=scihub,
            preset=preset,
            sources=sources,
        ),
    )


def _run_flags(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if v}


def _finish_run(cfg: Config, stats: RunStats, *, scope: str, flags: dict) -> None:
    report = build_report(stats, cfg, command="run", scope=scope, flags=flags)
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
    config: Path | None = ConfigOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
) -> None:
    """Attach already-downloaded PDFs (status ok / attach_failed) into Zotero."""
    cfg = _cfg(config)
    zl = _zotero()
    manifest = Manifest(cfg.manifest_path)
    attacher = Attacher(cfg, zl)
    if not attacher.supports_write():
        _exit_env(
            "This Zotero has no local write API. Upgrade to Zotero 10+ to attach."
        )
    pending = manifest.pending_attach()
    if limit:
        pending = pending[:limit]
    console.print(f"{len(pending)} PDFs to attach")
    if not pending:
        console.print("[bold]Attached 0/0[/]")
        return
    pipe = Pipeline(cfg, manifest, console, attacher=attacher)
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
    console.print(f"[bold]Attached {done}/{len(pending)}[/]")


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


@app.command()
def mirrors(config: Path | None = ConfigOpt) -> None:
    """Ping the configured Sci-Hub mirrors."""
    cfg = _cfg(config)
    console.print(f"[yellow]{SCIHUB_DISCLAIMER}[/]")
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
    from .cookies import cookie_domains
    from .session import BrowserSession, profile_ready, vault_cookies_path
    from .sources import ezproxy as ez
    from .sources import scholar as gs

    browser = BrowserSession(cfg)
    ctx = Context(config=cfg, client=make_client(cfg), browser=browser)
    try:
        if slot == "ezproxy":
            cookie_path = cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt")
            if (
                not cookie_path.is_file()
                and not vault_cookies_path(cfg).is_file()
                and not profile_ready(cfg)
            ):
                _netscape_fallback_hint(cookie_path, scholar=False)
                _print_exit_ladder()
                raise typer.Exit(2)
            ok, detail = ez.session_ok(ctx)
        else:
            cookie_path = cfg.scholar_cookies or (cfg.state_dir / "scholar-cookies.txt")
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
    slot: str = typer.Argument(..., help="scholar or ezproxy"),
    config: Path | None = ConfigOpt,
) -> None:
    """Open headed Chromium on the local vault; log in once, reuse on run."""
    from . import session as sess

    cfg = _cfg(config)
    key = slot.strip().lower()
    if key not in sess.SLOTS:
        console.print(f"[red]Unknown slot {slot!r}.[/] Use scholar or ezproxy.")
        raise typer.Exit(1)
    console.print(f"Vault: {sess.sessions_dir(cfg)}")
    try:
        url = sess.login_url_for(cfg, key)
    except sess.SessionError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(f"Opening: {url}")
    try:
        written = sess.login_headed(cfg, key, confirm=_confirm_session_login)
    except sess.SessionError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2)
    for path in written:
        console.print(f"Wrote {path}")
    console.print("[green]Session saved.[/] Probe with [bold]paperful session status[/].")


@session_app.command("status")
def session_status(
    config: Path | None = ConfigOpt,
    probe: bool = typer.Option(
        False, "--probe/--no-probe", help="Hit Scholar / EZProxy session_ok (network)"
    ),
) -> None:
    """Show the vault. Default is offline file presence; --probe runs session_ok."""
    from . import session as sess

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
    ez_path = cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt")
    gs_path = cfg.scholar_cookies or (cfg.state_dir / "scholar-cookies.txt")
    console.print(f"Vault cookies:  {'yes' if vault.is_file() else 'no'} ({vault})")
    console.print(f"EZProxy file:  {'yes' if ez_path.is_file() else 'no'} ({ez_path})")
    console.print(f"Scholar file:   {'yes' if gs_path.is_file() else 'no'} ({gs_path})")
    if not probe:
        return
    if cfg.ezproxy_base:
        _probe_slot(cfg, "ezproxy")
    if "scholar" in cfg.sources:
        _probe_slot(cfg, "scholar")


@session_app.command("export")
def session_export(config: Path | None = ConfigOpt) -> None:
    """Dump Netscape cookies from the Chromium profile (httpx compat)."""
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
    cookie_path = cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt")
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
    cookie_path = cfg.scholar_cookies or (cfg.state_dir / "scholar-cookies.txt")
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


if __name__ == "__main__":
    app()
