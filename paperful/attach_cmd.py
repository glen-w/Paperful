"""``paperful attach`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
import typer
from .store import Manifest, REASON_SHORT_PDF, STATUS_OK
from .pipeline import Pipeline
from .library import LibraryError
import time


def run_attach(
    console: Console,
    *,
    item: list[str],
    file: Path | None,
    config: Path | None,
    limit: int | None,
    allow_pdf_doi_mismatch: bool,
    allow_short_pdf: bool,
) -> None:
    """Write already-downloaded PDFs into the library. This command attaches; it is not a dry-run.

    Use ``--item KEY --file PATH`` to ingest a hand-downloaded PDF."""
    from . import cli_runtime as cli_mod

    from .handoff import attach_pdf_file

    cfg = cli_mod._cfg(config)
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg)
    manifest = Manifest(cfg.manifest_path)
    if not backend.supports_write():
        cli_mod._exit_env(cli_mod._no_write(backend), cfg)

    if item or file is not None:
        if len(item) != 1 or file is None:
            console.print(
                "[red]Manual ingest needs exactly one --item KEY and --file PATH.[/]"
            )
            raise typer.Exit(1)
        loaded = cli_mod._loaded_scope(backend, item_keys=item)
        if not loaded.items:
            console.print(f"[red]Unknown item {item[0]}.[/]")
            raise typer.Exit(1)
        try:
            rec = attach_pdf_file(cfg, backend, manifest, loaded.items[0], file)
        except (OSError, ValueError, LibraryError) as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
        cli_mod._flush(backend)
        console.print(f"[green]Attached[/] {rec.itemKey} ← {file}")
        cli_mod._rag_auto(cfg, time.time(), keys=[rec.itemKey])
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
        with cli_mod._item_progress() as progress:
            task_id = progress.add_task("Attaching PDFs", total=len(pending))
            for rec in pending:
                if pipe.attach_record(rec):
                    done += 1
                progress.advance(task_id)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
    cli_mod._flush(backend)
    console.print(f"[bold]Attached {done}/{len(pending)}[/]")
