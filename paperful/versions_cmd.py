"""``paperful versions`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
import typer
from .library import LibraryError
import json


def run_versions(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    dry_run: bool,
    apply: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    as_json: bool,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
) -> None:
    """Link a preprint and its published paper as one work. Write only with --apply."""
    from . import cli_runtime as cli_mod

    import httpx

    from .versions import (
        apply_versions,
        classify_versions,
        http_fetch_published,
        pack_counts,
        resolver_for,
        write_pack,
    )

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
    backend = cli_mod._connect(cfg, quiet=as_json)
    loaded = cli_mod._load_scope(
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
            with cli_mod._item_progress(json_out=as_json) as progress:
                proposals = classify_versions(
                    items,
                    resolver_for(client, cfg.email),
                    track=cli_mod._track(progress, "Checking versions"),
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
                cli_mod._exit_env(cli_mod._no_write(backend), cfg)
            try:
                with cli_mod._item_progress(json_out=as_json) as progress:
                    applied, errors = apply_versions(
                        backend,
                        proposals,
                        fetch_published=http_fetch_published(client, cfg.email),
                        audit_path=cfg.versions_applied_path,
                        scope=scope,
                        pack=json_path,
                        track=cli_mod._track(progress, "Linking versions"),
                    )
            except LibraryError as exc:
                cli_mod._exit_env(str(exc))
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
            cli_mod._print_version_table(proposals)
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
