"""``paperful summarize`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .config import wants_disk
from .runreport import write_command_report
from .store import Manifest

def run_summarize(
    console: Console,
    *,
    item: list[str],
    collection: list[str],
    library: bool | None,
    apply: bool | None,
    to_dest: str | None,
    prompt: Path | None,
    force: bool,
    order_value: str | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    max_new: int | None,
    max_minutes: float | None,
    collections_file: Path | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod

    from .llm import llm_egress_is_remote
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError
    from .summarize import SummaryRow, order_items, summarize_items

    if not item and cli_mod._scope_unset(collection, library, profile, run_config):
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(
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
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    limit = bound.limit
    apply = bound.apply
    if collections_file is not None:
        extra = [
            ln.strip()
            for ln in collections_file.expanduser().read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        collection = list(collection) + extra
    if not item and not collection and not library:
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    dest = to_dest if to_dest is not None else cfg.summarize_dest
    queue_order = order_value if order_value is not None else cfg.summarize_order
    if apply and dest == "disk":
        console.print(
            "[red]--apply writes a Zotero note; it conflicts with --to disk.[/]"
        )
        raise typer.Exit(1)
    cli_mod._require_manager(cfg)
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
    backend = cli_mod._connect(cfg, quiet=json_out)
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
        skipped_no_text: int = 0,
    ) -> None:
        write_command_report(
            cfg,
            command="summarize",
            scope=scope,
            summary={
                "summarized": summarized,
                "failed": failed,
                "skipped": skipped,
                "skipped_no_text": skipped_no_text,
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
                "skipped_no_text": skipped_no_text,
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
        cli_mod._emit_agent(
            agent_box[-1],
            json_out=json_out,
            human=lambda: console.print("[yellow]No items with PDFs in scope.[/]"),
        )
        return
    with cli_mod._item_progress(json_out=json_out) as progress:
        batch = summarize_items(
            cfg,
            items,
            manifest,
            backend,
            dest=dest,
            force=force,
            on_row=_show,
            track=cli_mod._track(progress, "Summarizing"),
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
    from .summarize import write_summarize_miss_digest

    miss_path = write_summarize_miss_digest(cfg, batch.rows)
    _finish(
        outcomes,
        batch.summarized,
        batch.failed,
        batch.skipped,
        batch.not_reached,
        batch.skipped_no_text,
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
        already = batch.skipped - batch.skipped_no_text
        if already:
            console.print(
                f"Skipped {already} already summarized for this model "
                "(pass --force to redo)."
            )
        if batch.skipped_no_text:
            console.print(
                f"Skipped {batch.skipped_no_text} with no PDF text "
                f"(needs ocr; miss list {miss_path or cfg.summarize_miss_path})."
            )
        if dest == "disk":
            console.print("Zotero not written (dest=disk).")

    if batch.fatal:
        agent_box[-1]["exit"] = 1
        agent_box[-1]["ok"] = False
    cli_mod._emit_agent(agent_box[-1], json_out=json_out, human=_human_sum)
    if batch.fatal:
        raise typer.Exit(1)
    cli_mod._flush(backend)
