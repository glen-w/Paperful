"""``paperful keepup`` implementation (CLI parses flags only)."""

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
from . import cli_runtime as cli_mod


def _keepup_call(action: Any) -> Any:
    from .keepup import KeepupError
    from .snowball.command import SnowballError

    try:
        return action()
    except (KeepupError, SnowballError) as exc:
        cli_mod.console.print(f"[red]{exc}[/]")
        raise typer.Exit(getattr(exc, "code", 2) or 2) from exc


def run_keepup_save(
    console: Console,
    name: Any,
    collection: Any,
    watch: Any,
    authorwatch: Any,
    source: Any,
    interval_days: Any,
    per_seed_limit: Any,
    max_candidates: Any,
    config: Any,
) -> None:
    """Create or update a keepup job. No API keys."""
    from . import cli_runtime as cli_mod

    from .keepup import Source, save_job

    cfg = cli_mod._cfg(config)
    sources = [Source(type="watch", name=item) for item in watch]
    sources.extend(Source(type="authorwatch", name=item) for item in authorwatch)
    for raw in source:
        kind = raw.strip().lower()
        sources.append(Source(type=kind, name=""))
    path = _keepup_call(
        lambda: save_job(
            cfg,
            name,
            collection=collection,
            sources=sources,
            interval_days=interval_days,
            per_seed_limit=per_seed_limit,
            max_candidates=max_candidates,
        )
    )
    console.print(f"Wrote [bold]{path}[/]")

def run_keepup_list(
    console: Console,
    config: Any,
) -> None:
    """List keepup jobs."""
    from . import cli_runtime as cli_mod

    from .keepup import list_jobs

    cfg = cli_mod._cfg(config)
    names = list_jobs(cfg)
    if not names:
        console.print("No keepup jobs.")
        return
    for name in names:
        console.print(name)

def run_keepup_show(
    console: Console,
    name: Any,
    config: Any,
) -> None:
    """Show job ledger. Does not open the library."""
    from . import cli_runtime as cli_mod

    from .keepup import show_job

    cfg = cli_mod._cfg(config)
    _keepup_call(lambda: show_job(cfg, name, console=console))

def run_keepup_delete(
    console: Console,
    name: Any,
    yes: Any,
    config: Any,
) -> None:
    """Delete a keepup job ledger."""
    from . import cli_runtime as cli_mod

    from .keepup import delete_job

    cfg = cli_mod._cfg(config)
    if not yes:
        console.print("Pass --yes to delete the keepup job directory.")
        raise typer.Exit(1)
    path = _keepup_call(lambda: delete_job(cfg, name))
    console.print(f"Deleted {path}")

def run_keepup_run(
    console: Console,
    name: Any,
    force: Any,
    apply: Any,
    config: Any,
) -> None:
    """Poll sources (respecting interval). Baseline proposes nothing."""
    from . import cli_runtime as cli_mod

    from .keepup import run_job

    cfg = cli_mod._cfg(config)
    backend = None
    if apply:
        cli_mod._require_manager(cfg)
        backend = cli_mod._connect(cfg)
        if not backend.supports_write():
            cli_mod._exit_env(cli_mod._no_write(backend), cfg)

    def _go():
        return run_job(
            cfg,
            name,
            console=console,
            force=force,
            apply=apply,
            backend=backend,
        )

    result = _keepup_call(_go)
    if result.created and getattr(result, "created", 0):
        pass

def run_keepup_digest(
    console: Console,
    name: Any,
    config: Any,
) -> None:
    """Rebuild digest.md from the keepup inbox. Does not create items."""
    from . import cli_runtime as cli_mod

    from .keepup import write_digest

    cfg = cli_mod._cfg(config)
    path = _keepup_call(lambda: write_digest(cfg, name))
    console.print(f"Wrote [bold]{path}[/]")

def run_keepup_apply(
    console: Console,
    name: Any,
    apply: Any,
    config: Any,
) -> None:
    """Create parents from the keepup inbox into the job collection."""
    from . import cli_runtime as cli_mod

    from .keepup import apply_job, load_job

    cfg = cli_mod._cfg(config)
    body = _keepup_call(lambda: load_job(cfg, name))
    backend = None
    if apply:
        cli_mod._require_manager(cfg)
        backend = cli_mod._connect(cfg)
        if not backend.supports_write():
            cli_mod._exit_env(cli_mod._no_write(backend), cfg)

    def _go():
        return apply_job(
            cfg,
            name,
            console=console,
            apply=apply,
            backend=backend,
        )

    result = _keepup_call(_go)
    _ = body
    if result.failed and result.created:
        raise typer.Exit(3)

def run_keepup_dismiss(
    console: Console,
    name: Any,
    doi: Any,
    identity: Any,
    config: Any,
) -> None:
    """Mute a work so keepup never re-proposes it."""
    from . import cli_runtime as cli_mod

    from .keepup import dismiss

    cfg = cli_mod._cfg(config)
    key = _keepup_call(
        lambda: dismiss(cfg, name, identity=identity, doi=doi)
    )
    console.print(f"Muted {key}")

