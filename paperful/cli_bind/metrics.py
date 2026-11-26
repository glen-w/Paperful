"""Signatures: metrics refresh / show."""

from __future__ import annotations

from pathlib import Path

import typer

from paperful.cli import console, metrics_app
from paperful.cli_bind._shared import (
    AgentFormatOpt,
    ConfigOpt,
    ItemTypeOpt,
    LibraryOpt,
    ProfileOpt,
    RunConfigFileOpt,
    YearFromOpt,
    YearToOpt,
)


@metrics_app.command("refresh")
def metrics_refresh(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    stale_days: int | None = typer.Option(
        None,
        "--stale-days",
        help="Skip rows fetched this recently (default \\[metrics].stale_days).",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print and write a pack; do not update cache.json."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write or update a tagged child note on each item (Zotero item pane). Not Extra.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Fetch OpenAlex/Crossref citation counts for items you already hold. Writes state/metrics/."""
    from paperful.metrics_cmd import run_metrics_refresh

    run_metrics_refresh(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        stale_days=stale_days,
        dry_run=dry_run,
        apply=apply,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@metrics_app.command("show")
def metrics_show(
    item_key: str = typer.Argument(..., help="Library item key."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Print the cached citation row for one item. No network."""
    from paperful.metrics_cmd import run_metrics_show

    run_metrics_show(
        console,
        item_key=item_key,
        config=config,
        fmt=fmt,
    )
