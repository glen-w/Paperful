"""``paperful playbooks`` implementation (CLI parses flags only)."""

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

def run_playbooks_probe(
    console: Console,
    corpus: Any,
    config: Any,
    examples: Any,
    check: Any,
    min_bytes: Any,
    delay: Any,
    save: Any,
    as_json: Any,
) -> None:
    """Fetch each corpus landing and require the first candidate to be a PDF.

    Exit 0 when every target passes. A pass is a %PDF body of at least
    --min-bytes. It does not prove the file is the record a listing page
    describes. This command talks to the network.
    """
    from . import cli_runtime as cli_mod

    import httpx

    from .grey_probe import load_corpus, playbooks_for_probe, probe_corpus, save_recorded

    if check < 1:
        console.print("[red]--check must be >= 1[/]")
        raise typer.Exit(2)
    if min_bytes < 1:
        console.print("[red]--min-bytes must be >= 1[/]")
        raise typer.Exit(2)
    try:
        targets = load_corpus(corpus)
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    cfg = cli_mod._cfg(config)
    books = playbooks_for_probe(cfg.grey_playbooks, examples=examples)
    timeout = httpx.Timeout(20.0, connect=15.0)
    with httpx.Client(
        headers={"User-Agent": cfg.user_agent, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        rows = probe_corpus(
            targets,
            books,
            client,
            check=check,
            min_bytes=min_bytes,
            delay_s=max(0.0, delay),
        )
    if save is not None:
        path = save_recorded(save, rows)
        console.print(f"Wrote {path}")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    if as_json:
        console.print(
            json.dumps(
                {
                    "counts": counts,
                    "rows": [row.to_dict() for row in rows],
                },
                indent=2,
            )
        )
    else:
        table = Table(title="Grey playbook probe")
        table.add_column("Status")
        table.add_column("Playbook")
        table.add_column("Landing")
        table.add_column("Chosen")
        table.add_column("Detail")
        for row in rows:
            table.add_row(
                row.status,
                row.playbook,
                row.url or row.extra,
                row.chosen,
                row.detail,
            )
        console.print(table)
        summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        console.print(summary)
    if any(row.status != "pass" for row in rows):
        raise typer.Exit(1)

def run_playbooks_propose(
    console: Console,
    config: Any,
    to: Any,
    min_hits: Any,
) -> None:
    """Draft learned playbooks from state/fetch-wins.jsonl. Does not install them."""
    from . import cli_runtime as cli_mod

    from .fetch_wins import load_wins, proposed_path, propose_toml, wins_path

    cfg = cli_mod._cfg(config)
    if min_hits < 1:
        console.print("[red]--min-hits must be >= 1[/]")
        raise typer.Exit(2)
    rows = load_wins(wins_path(cfg))
    text = propose_toml(rows, min_hits=min_hits)
    dest = to if to is not None else proposed_path(cfg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    if text.strip():
        console.print(text)
    else:
        console.print("[dim]No promotable wins yet.[/]")
    console.print(f"Wrote {dest}")

def run_playbooks_promote(
    console: Console,
    config: Any,
    source: Any,
) -> None:
    """Install proposed learned playbooks into grey_playbooks_dir/learned.toml."""
    from . import cli_runtime as cli_mod

    from .fetch_wins import proposed_path, write_learned
    from .playbooks import load_pack_file

    cfg = cli_mod._cfg(config)
    if cfg.grey_playbooks_dir is None:
        console.print(
            "[red]grey_playbooks_dir is unset.[/] "
            'Set grey_playbooks_dir = "packs" in config.toml.'
        )
        raise typer.Exit(2)
    path = source if source is not None else proposed_path(cfg)
    if not path.is_file():
        console.print(
            f"[red]No proposal file at {path}.[/] Run playbooks propose first."
        )
        raise typer.Exit(2)
    books = [pb for pb in load_pack_file(path) if pb.name.startswith("learned-")]
    if not books:
        console.print("[yellow]Proposal has no learned- playbooks.[/]")
        raise typer.Exit(1)
    changed = write_learned(cfg.grey_playbooks_dir, books)
    dest = cfg.grey_playbooks_dir / "learned.toml"
    if changed:
        console.print(f"[green]Promoted[/] {len(books)} playbook(s) to {dest}")
    else:
        console.print(f"[dim]Unchanged[/] {dest}")

