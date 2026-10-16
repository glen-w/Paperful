"""``paperful dedupe`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .library import LibraryError
from .runreport import write_command_report
from .store import Manifest

def run_dedupe(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    dry_run: bool,
    apply: bool | None,
    apply_medium: bool,
    phase: str,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    as_json: bool,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod

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
    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    json_out, as_json = cli_mod._agent_wins(fmt, as_json)
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
    quiet = as_json or json_out
    backend = cli_mod._connect(cfg, quiet=quiet)
    items: list
    scope: str
    groups: list
    if quiet:
        loaded = cli_mod._loaded_scope(
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
        with cli_mod._item_progress() as progress:
            load_id = progress.add_task("Connecting to Zotero scope…", total=None)

            def _load_status(msg: str) -> None:
                progress.update(load_id, description=msg)

            loaded = cli_mod._loaded_scope(
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
            cli_mod._exit_env(cli_mod._no_write(backend), cfg)
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
                with cli_mod._item_progress() as progress:
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
            cli_mod._exit_env(str(exc))
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
        cli_mod._print_dedupe_table(groups)
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
        cli_mod._emit_agent(agent, json_out=True, human=_human_dedupe)
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
