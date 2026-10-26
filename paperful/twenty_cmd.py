"""``paperful twenty`` implementation (CLI parses flags only)."""

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

def run_twenty_lookup(
    console: Console,
    collection: Any,
    library: Any,
    year_from: Any,
    year_to: Any,
    item_type: Any,
    apply: Any,
    profile: Any,
    run_config: Any,
    config: Any,
) -> None:
    """Match collection authors against Twenty People. Read-only unless --apply."""
    from . import cli_runtime as cli_mod

    from .twenty import authors_from_items, lookup_authors, twenty_ready

    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    if not cfg.twenty_enabled:
        console.print(
            "[red]Twenty is off.[/] Set [twenty].enabled = true and TWENTY_API_KEY."
        )
        raise typer.Exit(1)
    if not twenty_ready(cfg):
        console.print(
            "[red]Twenty is not ready.[/] Set [twenty].base_url (or TWENTY_BASE_URL) "
            "and env TWENTY_API_KEY. Paperful never probes Twenty from doctor."
        )
        raise typer.Exit(1)
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
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg)
    loaded = cli_mod._load_scope(
        backend,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    authors = authors_from_items(loaded.items)
    label = collection[0] if collection else "library"
    if not loaded.items:
        console.print(
            f"[yellow]No items in scope ({label}).[/] "
            "Check the collection path (e.g. ocean/BBNJ vs a same-named empty folder)."
        )
        raise typer.Exit(1)
    if not authors:
        console.print(
            f"[yellow]{len(loaded.items)} item(s) in scope, but no creator names.[/]"
        )
        raise typer.Exit(1)
    rows = lookup_authors(
        cfg,
        authors,
        collection=label,
        apply=apply,
    )
    table = Table(title=f"Twenty lookup ({'apply' if apply else 'dry-run'})")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Website")
    table.add_column("Email")
    table.add_column("Note")
    for row in rows:
        table.add_row(
            row.query_name,
            row.status,
            (row.listing_url or (row.hit.website if row.hit else ""))[:50] or "-",
            (row.emails[0] if row.emails else "-"),
            row.note or "-",
        )
    console.print(table)
    matched = sum(1 for r in rows if r.status == "match")
    console.print(
        f"{len(rows)} authors · {matched} unique matches · "
        f"{sum(1 for r in rows if r.status == 'ambiguous')} ambiguous · "
        f"{sum(1 for r in rows if r.status == 'miss')} miss"
        f" · {len(loaded.items)} items"
    )
    if apply:
        console.print(
            "Wrote proposed pack listings (promote before author_site fetch) "
            "and contacts under state/author-contacts/. Paperful does not send mail."
        )
    else:
        console.print("[dim]Dry-run. Pass --apply to write proposed packs and contacts.[/]")

def run_twenty_sync(
    console: Console,
    collection: Any,
    library: Any,
    year_from: Any,
    year_to: Any,
    item_type: Any,
    apply: Any,
    limit: Any,
    yes: Any,
    profile: Any,
    run_config: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Create or enrich Twenty People from collection authors. Dry-run unless --apply."""
    from . import cli_runtime as cli_mod

    from .agent_json import EXIT_PARTIAL, envelope
    from .twenty import apply_sync_actions, plan_sync, twenty_ready

    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    if not cfg.twenty_enabled:
        console.print(
            "[red]Twenty is off.[/] Set [twenty].enabled = true and TWENTY_API_KEY."
        )
        raise typer.Exit(1)
    if not twenty_ready(cfg):
        console.print(
            "[red]Twenty is not ready.[/] Set [twenty].base_url (or TWENTY_BASE_URL) "
            "and env TWENTY_API_KEY."
        )
        raise typer.Exit(1)
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
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg)
    loaded = cli_mod._load_scope(
        backend,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    label = collection[0] if collection else "library"
    if not loaded.items:
        console.print(f"[yellow]No items in scope ({label}).[/]")
        raise typer.Exit(1)
    actions = plan_sync(cfg, loaded.items, collection=label, limit=limit)
    creates = [row for row in actions if row.action == "create"]
    if apply and len(creates) >= 50 and not yes:
        import sys

        if not sys.stdin.isatty():
            console.print(
                f"[red]{len(creates)} People would be created.[/] Pass --yes to confirm."
            )
            raise typer.Exit(1)
        if not typer.confirm(f"Create {len(creates)} Twenty People?"):
            raise typer.Exit(1)
    if apply:
        actions = apply_sync_actions(cfg, actions, collection=label)
    wrote = sum(1 for row in actions if row.note == "wrote")
    failed = sum(1 for row in actions if row.action == "miss-http")

    def _human() -> None:
        table = Table(title=f"Twenty sync ({'apply' if apply else 'dry-run'})")
        table.add_column("Name")
        table.add_column("Action")
        table.add_column("Note")
        for row in actions:
            table.add_row(row.name, row.action, (row.note or "-")[:80])
        console.print(table)
        console.print(
            f"{len(actions)} rows · "
            f"{sum(1 for row in actions if row.action == 'create')} create · "
            f"{sum(1 for row in actions if row.action == 'enrich')} enrich · "
            f"{sum(1 for row in actions if row.action == 'ambiguous')} ambiguous · "
            f"{sum(1 for row in actions if row.action == 'skip-corporate')} orgs · "
            f"{failed} http"
        )
        if apply:
            console.print(
                "Wrote People (keywords + a Paperful note) and state/author-contacts/. "
                "Paperful does not send mail."
            )
        else:
            console.print("[dim]Dry-run. Pass --apply to create and enrich People.[/]")

    code = 0
    if failed and wrote:
        code = EXIT_PARTIAL
    elif failed and apply:
        code = 1
    payload = envelope(
        command="twenty sync",
        summary={
            "rows": len(actions),
            "create": sum(1 for row in actions if row.action == "create"),
            "enrich": sum(1 for row in actions if row.action == "enrich"),
            "ambiguous": sum(1 for row in actions if row.action == "ambiguous"),
            "skip_corporate": sum(1 for row in actions if row.action == "skip-corporate"),
            "http_errors": failed,
            "items": len(loaded.items),
        },
        items=[
            {"name": row.name, "action": row.action, "note": row.note, "twenty_id": row.twenty_id}
            for row in actions
        ],
        flags={"apply": apply, "collection": label, "limit": limit},
        exit_code=code,
    )
    cli_mod._emit_agent(payload, json_out=json_out, human=_human)

