"""``paperful mirrors`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from .config import SCIHUB_DISCLAIMER
from .pipeline import make_client
from .sources import Context
from .sources.scihub import ping_mirrors


def run_mirrors(console: Console, *, config: Path | None) -> None:
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    console.print(f"[red]{SCIHUB_DISCLAIMER}[/]")
    if "scihub" not in cfg.sources:
        console.print(
            '[dim]Sci-Hub is off until you add "scihub" to sources or pass --scihub on run.[/]'
        )
    ctx = Context(config=cfg, client=make_client(cfg))
    for mirror, status in ping_mirrors(ctx):
        colour = "green" if status == "HTTP 200" else "red"
        console.print(f"[{colour}]{status:<10}[/] {mirror}")
