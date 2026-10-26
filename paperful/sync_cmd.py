"""``paperful sync`` / ``import`` / openalex-store implementation (CLI parses flags only)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .config import Config, parse_pdfs
from .library import LibraryError
from .runreport import write_command_report, write_run_report
from .store import Manifest
from . import cli_runtime as cli_mod

def _print_sync(stats, *, dry_run: bool) -> None:
    was = "none" if stats.previous is None else f"v{stats.previous}"
    kind = "full" if stats.full else "changes since last refresh"
    verb = "would write" if dry_run else "written"
    cli_mod.console.print(
        f"[bold]library {was} → v{stats.version}[/] ({kind}) · "
        f"{verb} {stats.written} · left the library {stats.gone} · "
        f"pdfs copied {stats.pdf_exports}"
    )
    if stats.unread:
        cli_mod.console.print(
            f"[yellow]{stats.unread} item(s) could not be read. The mirror keeps "
            "what it had for them and the next refresh tries again.[/]"
        )
    if stats.unwritten:
        cli_mod.console.print(
            f"[yellow]{len(stats.unwritten)} item folder(s) could not be written. "
            "The next refresh tries again.[/]"
        )
        for line in stats.unwritten[:5]:
            cli_mod.console.print(f"[dim]  {line}[/]")
    if stats.pdf_missing:
        cli_mod.console.print(
            f"[yellow]{stats.pdf_missing} PDF(s) are listed in the library with no "
            "file behind them. See paperful attachments.[/]"
        )

def run_sync_command(
    console: Console,
    full: Any,
    dry_run: Any,
    pdfs: Any,
    accept_gone: Any,
    config: Any,
) -> None:
    """Bring out/ up to date with the library. Reads what changed since the last refresh."""
    from . import cli_runtime as cli_mod

    from .snapshot import run_snapshot, snapshot_report
    from .sync import run_sync, sync_report

    cfg = cli_mod._cfg(config)
    cli_mod._require_manager(cfg)
    try:
        mode = parse_pdfs(pdfs) if pdfs else cfg.mirror_pdfs
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    backend = cli_mod._live_backend(cfg)
    if not callable(getattr(backend, "changes", None)):
        # No change feed on this manager: read it whole, as snapshot does.
        loaded = cli_mod._load_scope(
            backend, collection=[], library=True, year_from=None, year_to=None, item_type=[]
        )
        with cli_mod._item_progress() as progress:
            snap = run_snapshot(
                cfg,
                backend,
                loaded.items,
                pdfs=mode,
                dry_run=dry_run,
                manifest=Manifest(cfg.manifest_path),
                track=cli_mod._track(progress, "Writing folders"),
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
        with cli_mod._item_progress() as progress:
            stats = run_sync(
                cfg,
                backend,
                full=full,
                dry_run=dry_run,
                pdfs=mode,
                accept_gone=accept_gone,
                track=cli_mod._track(progress, "Writing items"),
                pdf_track=cli_mod._track(progress, "Copying PDFs"),
                status=lambda msg: progress.console.print(f"[dim]{msg}[/]"),
            )
    except LibraryError as exc:
        cli_mod._exit_env(str(exc), cfg)
    if not dry_run:
        write_run_report(
            cfg, sync_report(cfg, stats, dry_run=dry_run, pdfs=mode), as_last_run=False
        )
    _print_sync(stats, dry_run=dry_run)
    if not dry_run:
        # Copies do not go through the manifest, so name the items.
        cli_mod._rag_auto(cfg, time.time(), keys=stats.pdf_keys)

def run_import_library(
    console: Console,
    path: Any,
    fmt: Any,
    apply: Any,
    config: Any,
) -> None:
    """Import a bibliography file. Default is a dry-run count; --apply writes the library."""
    from . import cli_runtime as cli_mod

    from .interop.load import load_records
    from .xfer import apply_import

    cfg = cli_mod._cfg(config)
    cli_mod._require_manager(cfg)
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

        cli_mod._emit_agent(payload, json_out=json_out, human=_human_imp)
        return
    backend = cli_mod._connect(cfg, quiet=json_out)
    if not backend.supports_write():
        cli_mod._exit_env(cli_mod._no_write(backend), cfg)
    with cli_mod._item_progress(json_out=json_out) as progress:
        done = apply_import(
            records, backend, dry_run=False, track=cli_mod._track(progress, "Importing records")
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

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_imp_done)
    cli_mod._flush(backend)

def run_openalex_store_build_cites(
    console: Console,
    out: Any,
    timeout_s: Any,
    config: Any,
) -> None:
    """Invert works.referenced_works into a cites index for store-backed citing.

    Needs [openalex_store] with a works parquet_glob. Point cites_index_glob at
    ``<out>/**/*.parquet`` afterward (or use --out that matches that glob).

    Builds one works ``updated_date`` partition at a time and writes
    ``.done/<date>`` markers — safe to re-run after a crash. Full OpenAlex
    dumps can take many hours; for a remote host prefer a nohup'd build on
    that machine so a laptop disconnect does not stop the job.
    """
    from . import cli_runtime as cli_mod

    from .snowball.local_openalex import OpenAlexStoreError, build_cites_index_from_config

    cfg = cli_mod._cfg(config)
    try:
        written, counts = build_cites_index_from_config(
            cfg,
            output_dir=out,
            timeout_s=timeout_s,
            progress=lambda msg: console.print(msg),
        )
    except OpenAlexStoreError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    example = written.rstrip("/") + "/**/*.parquet"
    console.print(
        f"Cites index under [bold]{written}[/] · "
        f"built {counts['built']}, skipped {counts['skipped']}, "
        f"total {counts['total']}. "
        f"Set [openalex_store].cites_index_glob to that tree (e.g. {example})."
    )

