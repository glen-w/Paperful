"""``paperful pack`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table


def _fmt_pack_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    return f"{seconds:g}s"


def run_pack_open(
    console: Console,
    *,
    label: str | None,
    config: Path | None,
) -> None:
    from . import cli_runtime as cli_mod

    from .pack import PackError, open_pack

    cfg = cli_mod._cfg(config)
    try:
        pack = open_pack(cfg, label=label)
    except PackError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(pack["id"])


def run_pack_close(console: Console, *, config: Path | None) -> None:
    from . import cli_runtime as cli_mod

    from .pack import PackError, close_pack

    cfg = cli_mod._cfg(config)
    try:
        pack = close_pack(cfg)
    except PackError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    n = len(pack.get("steps") or [])
    console.print(f"Closed {pack['id']} ({n} steps)")


def run_pack_show(
    console: Console,
    *,
    as_json: bool,
    config: Path | None,
) -> None:
    from . import cli_runtime as cli_mod

    from .pack import headline, latest_pack, show_payload

    cfg = cli_mod._cfg(config)
    pack = latest_pack(cfg)
    if pack is None:
        console.print("No pack yet. Run [bold]paperful pack open[/] first.")
        raise typer.Exit(0)
    payload = show_payload(cfg, pack)
    if as_json:
        console.print(
            json.dumps(payload, indent=2),
            soft_wrap=True,
            highlight=False,
            markup=False,
        )
        return
    title = pack.get("label") or pack["id"]
    console.print(f"Pack [bold]{pack['id']}[/] ({pack.get('status')})")
    if pack.get("label"):
        console.print(pack["label"], markup=False)
    if pack.get("scope"):
        console.print(f"Scope: {pack['scope']}")
    table = Table(title=str(title))
    table.add_column("Command")
    table.add_column("Duration", justify="right")
    table.add_column("Counts")
    for step in payload.get("steps") or []:
        table.add_row(
            str(step.get("command") or ""),
            _fmt_pack_duration(step.get("duration_s")),
            headline(str(step.get("command") or ""), step.get("summary") or {}),
        )
    console.print(table)
