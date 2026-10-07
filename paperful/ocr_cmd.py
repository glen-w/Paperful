"""``paperful ocr`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console

import time
from rich.table import Table

def run_ocr(
    console: Console,
    *,
    item: list[str],
    collection: list[str],
    library: bool | None,
    apply: bool,
    attach: bool,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    max_minutes: float | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli as cli_mod

    from .ocr import OcrUnavailable, ocr_items
    from .store import Manifest
    from .runreport import write_command_report

    if not item and cli_mod._scope_unset(collection, library, profile, run_config):
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    if attach and not apply:
        console.print("[red]--attach needs --apply.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
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
    if not item and not collection and not library:
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg, quiet=json_out)
    if attach and not backend.supports_write():
        cli_mod._exit_env("Write support required to attach.", cfg)
    manifest = Manifest(cfg.manifest_path)
    loaded = cli_mod._load_scope(
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

        cli_mod._emit_agent(payload, json_out=json_out, human=_human_ocr_empty)
        raise typer.Exit(0)
    try:
        with cli_mod._item_progress(json_out=json_out) as progress:
            batch = ocr_items(
                cfg,
                items,
                manifest,
                backend,
                apply=apply,
                attach=attach,
                track=cli_mod._track(progress, "Running OCR" if apply else "Checking PDFs"),
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

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_ocr)
    cli_mod._flush(backend)
    if apply:
        cli_mod._rag_auto(
            cfg, started, keys=[row.key for row in batch.rows if row.status == "ocr"]
        )

