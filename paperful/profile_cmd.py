"""``paperful profile`` implementation (CLI parses flags only)."""

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
from .run_config import (
    ProfileListing,
    RunConfigError,
    collect_save_body,
    format_effective,
    list_profiles,
    save_profile,
)
from .runreport import write_command_report, write_run_report
from .store import Manifest

def _profile_bind_kwargs(
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    try_all: bool | None,
    retry_failed: bool | None,
    upgrade_linked: bool | None,
    no_attach: bool | None,
    strict_pdf_doi: bool | None,
    scihub: bool | None,
    sources: str | None,
    preset: str | None,
    apply: bool | None,
    overwrite: bool | None,
    steps: str | None,
    skip: list[str],
    require_summarize: bool | None,
    profile: str | None,
    run_config: Path | None,
) -> dict[str, Any]:
    return {
        "profile": profile,
        "run_config": run_config,
        "collection": collection,
        "library": library,
        "year_from": year_from,
        "year_to": year_to,
        "item_type": item_type,
        "limit": limit,
        "try_all": try_all,
        "retry_failed": retry_failed,
        "upgrade_linked": upgrade_linked,
        "no_attach": no_attach,
        "strict_pdf_doi": strict_pdf_doi,
        "scihub": scihub,
        "sources": sources,
        "preset": preset,
        "apply": apply,
        "overwrite": overwrite,
        "steps": steps,
        "skip": skip,
        "require_summarize": require_summarize,
    }

def run_profile_list(
    console: Console,
    config: Any,
) -> None:
    """List saved run configs. The builtin ``all`` policy is not a named profile."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    rows: list[ProfileListing] = list_profiles(cfg)
    if not rows:
        console.print("No saved profiles.")
        console.print(
            "[dim]Builtin all: gaps → run → lint → fix-metadata → summarize. "
            "Save one with[/] [bold]paperful profile save NAME -C …[/]"
        )
        return
    table = Table(title="Run profiles")
    table.add_column("Name")
    table.add_column("Source")
    table.add_column("Description")
    for row in rows:
        table.add_row(row.name, row.source, row.description)
    console.print(table)
    console.print(
        "[dim]paperful profile show NAME[/] prints the merge [bold]paperful all[/] would use."
    )

def run_profile_show(
    console: Console,
    name: Any,
    collection: Any,
    library: Any,
    year_from: Any,
    year_to: Any,
    item_type: Any,
    limit: Any,
    dry_run: Any,
    try_all: Any,
    retry_failed: Any,
    upgrade_linked: Any,
    no_attach: Any,
    strict_pdf_doi: Any,
    scihub: Any,
    sources: Any,
    preset: Any,
    apply: Any,
    overwrite: Any,
    steps: Any,
    skip: Any,
    require_summarize: Any,
    profile: Any,
    run_config: Any,
    config: Any,
) -> None:
    """Print the effective ``paperful all`` config after profile and flag merge."""
    from . import cli_runtime as cli_mod

    chosen = name or profile
    if name and profile and name != profile:
        console.print(
            "[red]Pass the profile name once, as an argument or --profile.[/]"
        )
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    bound = cli_mod._bind_run(
        cfg,
        for_all=True,
        **_profile_bind_kwargs(
            collection=collection,
            library=library,
            year_from=year_from,
            year_to=year_to,
            item_type=item_type,
            limit=limit,
            try_all=try_all,
            retry_failed=retry_failed,
            upgrade_linked=upgrade_linked,
            no_attach=no_attach,
            strict_pdf_doi=strict_pdf_doi,
            scihub=scihub,
            sources=sources,
            preset=preset,
            apply=apply,
            overwrite=overwrite,
            steps=steps,
            skip=skip,
            require_summarize=require_summarize,
            profile=chosen,
            run_config=run_config,
        ),
    )
    where = ", ".join(bound.origins) or "builtin all"
    console.print(f"[dim]Effective paperful all configuration ({where})[/]")
    console.print(format_effective(bound), markup=False, highlight=False)
    if dry_run and "summarize" in bound.steps:
        console.print("[yellow]dry-run skips summarize.[/]")

def run_profile_save(
    console: Console,
    name: Any,
    collection: Any,
    library: Any,
    year_from: Any,
    year_to: Any,
    item_type: Any,
    limit: Any,
    try_all: Any,
    retry_failed: Any,
    upgrade_linked: Any,
    no_attach: Any,
    strict_pdf_doi: Any,
    scihub: Any,
    sources: Any,
    preset: Any,
    apply: Any,
    overwrite: Any,
    steps: Any,
    skip: Any,
    require_summarize: Any,
    description: Any,
    force: Any,
    profile: Any,
    run_config: Any,
    config: Any,
) -> None:
    """Write profiles/<name>.toml beside config.toml. Does not edit config.toml."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    try:
        body = collect_save_body(
            cfg,
            description=description,
            **_profile_bind_kwargs(
                collection=collection,
                library=library,
                year_from=year_from,
                year_to=year_to,
                item_type=item_type,
                limit=limit,
                try_all=try_all,
                retry_failed=retry_failed,
                upgrade_linked=upgrade_linked,
                no_attach=no_attach,
                strict_pdf_doi=strict_pdf_doi,
                scihub=scihub,
                sources=sources,
                preset=preset,
                apply=apply,
                overwrite=overwrite,
                steps=steps,
                skip=skip,
                require_summarize=require_summarize,
                profile=profile,
                run_config=run_config,
            ),
        )
        path = save_profile(cfg, name, body, force=force)
    except RunConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"Wrote [bold]{path}[/]")

