"""``paperful authors`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table


def run_authors(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    min_count: int,
    max_authors: int,
    apply: bool,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod

    from .agent_json import envelope
    from .authors_report import (
        harvest,
        scope_slug,
        seed_proposed_pack,
        write_report,
    )
    from .snowball.authors import pack_slug

    json_out = cli_mod._agent_json(fmt)
    scoped = cli_mod._bind_scoped(
        collection=collection,
        library=library,
        profile=profile,
        run_config=run_config,
        config=config,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    cfg = scoped.cfg
    collection, library = scoped.collection, scoped.library
    backend, loaded, _items = cli_mod._connect_scope(
        scoped, quiet=json_out, json_out=json_out, apply_limit=False
    )
    report = harvest(loaded.items, min_count=min_count)
    slug = scope_slug(collection, library=library or not collection)
    pack_collection = (
        collection[0]
        if collection
        else (loaded.label if library or not collection else "library")
    )
    report_file: Path | None = None
    pack_file: Path | None = None
    if apply:
        report_file = write_report(
            cfg,
            slug,
            scope=loaded.label,
            report=report,
            min_count=min_count,
            n_items=len(loaded.items),
        )
        pack_file = seed_proposed_pack(
            cfg,
            collection=pack_collection,
            authors=report.authors,
            max_authors=max_authors,
        )

    def _human() -> None:
        console.print(
            f"Scope: [bold]{loaded.label}[/] — {len(loaded.items)} items, "
            f"{len(report.authors)} author{'s' if len(report.authors) != 1 else ''}, "
            f"{len(report.orgs)} org{'s' if len(report.orgs) != 1 else ''}"
        )
        if report.authors:
            table = Table(title="Authors")
            table.add_column("Name")
            table.add_column("Fingerprint")
            table.add_column("Items", justify="right")
            for row in report.authors:
                table.add_row(row.name, row.key, str(row.count))
            console.print(table)
        else:
            console.print("[green]No authors at this count.[/]")
        if report.orgs:
            table = Table(title="Orgs")
            table.add_column("Name")
            table.add_column("Items", justify="right")
            for row in report.orgs:
                table.add_row(row.name, str(row.count))
            console.print(table)
        else:
            console.print("[green]No orgs at this count.[/]")
        if not apply:
            console.print(
                "[dim]Dry-run. Pass --apply to write the report and proposed pack.[/]"
            )
            return
        if report_file is not None:
            console.print(f"Wrote report [bold]{report_file}[/]")
        if pack_file is not None:
            console.print(f"Proposed pack [bold]{pack_file}[/]")
            console.print(
                f"Next: paperful twenty lookup -C {pack_collection} --apply"
            )
            console.print(
                f"Next: paperful snowball packs promote {pack_slug(pack_collection)}"
            )
        elif report.authors:
            console.print("[dim]No pack seeded (empty top list).[/]")
        else:
            console.print("[dim]No authors to seed into a pack.[/]")

    agent_items = [
        {
            "kind": row.kind,
            "name": row.name,
            "key": row.key,
            "frequency": row.count,
        }
        for row in [*report.authors, *report.orgs]
    ]
    payload = envelope(
        command="authors",
        summary={
            "items": len(loaded.items),
            "authors": len(report.authors),
            "orgs": len(report.orgs),
            "min_count": min_count,
            "max_authors": max_authors,
        },
        items=agent_items,
        paths={
            "report": str(report_file) if report_file else "",
            "pack": str(pack_file) if pack_file else "",
        },
        flags={
            "apply": apply,
            "dry_run": not apply,
            "min_count": min_count,
            "max_authors": max_authors,
        },
    )
    cli_mod._emit_agent(payload, json_out=json_out, human=_human)

