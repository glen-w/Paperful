"""``paperful restore`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from .library import LibraryError


def run_restore(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    dry_run: bool,
    apply: bool | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .restore import (
        apply_restore,
        dedupe_restore_records,
        iter_records,
        plan_restore,
        record_in_scope,
    )

    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
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
        apply=apply,
    )
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    limit = bound.limit
    apply = bound.apply
    if dry_run and apply:
        console.print("[red]Pass either --dry-run or --apply, not both.[/]")
        raise typer.Exit(1)
    if not collection and not library:
        cli_mod._refuse_missing_scope()
    cli_mod._require_manager(cfg)
    backend = cli_mod._live_backend(cfg, quiet=json_out)
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
    types = cli_mod._resolve_types(item_type)
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
    keys, _scope = cli_mod._scope_keys(backend, collection, library)
    with cli_mod._spinner("Loading items from library…", json_out=json_out):
        library_items = backend.items_in_scope(keys)
    with cli_mod._item_progress(json_out=json_out) as progress:
        note_tags: dict[str, set[str]] = {}
        for it in cli_mod._track(progress, "Reading library notes")(library_items):
            tags: set[str] = set()
            try:
                kids = backend.children(it.key)
            except LibraryError as exc:
                cli_mod._exit_env(str(exc), cfg)
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

        cli_mod._emit_agent(payload, json_out=json_out, human=_human_restore)
        return
    with cli_mod._item_progress(json_out=json_out) as progress:
        done = apply_restore(
            planned,
            backend,
            backend,
            track=cli_mod._track(progress, "Restoring items"),
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

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_restore_done)
    cli_mod._flush(backend)
