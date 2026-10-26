"""``paperful acronyms`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table


def run_acronyms(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    min_count: int,
    apply: bool,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
) -> None:
    from . import cli_runtime as cli_mod
    from .acronyms import file_slug, harvest, write_allowlist

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
    )
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    if not collection and not library:
        cli_mod._refuse_missing_scope()
    backend = cli_mod._connect(cfg, quiet=False)
    loaded = cli_mod._load_scope(
        backend,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    rows = harvest(loaded.items, min_count=min_count)
    slug = file_slug(collection, library=library or not collection)
    console.print(
        f"Scope: [bold]{loaded.label}[/] — {len(loaded.items)} items, "
        f"{len(rows)} acronym{'s' if len(rows) != 1 else ''}"
    )
    if rows:
        table = Table(title="Acronyms")
        table.add_column("Token")
        table.add_column("Items", justify="right")
        for row in rows:
            table.add_row(row.token, str(row.count))
        console.print(table)
    else:
        console.print("[green]No acronyms at this count.[/]")
    if not apply:
        console.print("[dim]Dry-run. Pass --apply to write the allowlist.[/]")
        return
    path = write_allowlist(
        cfg.state_dir,
        slug,
        scope=loaded.label,
        rows=rows,
        min_count=min_count,
        n_items=len(loaded.items),
    )
    console.print(f"Wrote [bold]{path}[/]")
