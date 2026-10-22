"""``paperful snapshot`` implementation (CLI parses flags only)."""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console

from .config import parse_pdfs
from .runreport import write_run_report
from .store import Manifest


def run_snapshot_cmd(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    dry_run: bool,
    pdfs: str | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
) -> None:
    from . import cli_runtime as cli_mod
    from .snapshot import run_snapshot as snapshot_library
    from .snapshot import snapshot_report

    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    bound = cli_mod._bind_run(
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
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    limit = bound.limit
    if not collection and not library:
        cli_mod._refuse_missing_scope()
    cli_mod._require_manager(cfg)
    try:
        mode = parse_pdfs(pdfs) if pdfs else cfg.mirror_pdfs
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    backend = cli_mod._live_backend(cfg)
    loaded = cli_mod._load_scope(
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
    with cli_mod._item_progress() as progress:
        stats = snapshot_library(
            cfg,
            backend,
            items,
            pdfs=mode,
            dry_run=dry_run,
            manifest=manifest,
            track=cli_mod._track(
                progress, "Counting folders" if dry_run else "Writing folders"
            ),
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
        cli_mod._rag_auto(cfg, time.time(), keys=stats.pdf_keys)
