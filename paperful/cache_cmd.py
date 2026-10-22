"""``paperful cache clean`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from .config import load_config


def run_cache_clean(
    console: Console,
    *,
    apply: bool | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod

    from .sync import clean_pdf_cache

    cfg = load_config(config)
    report = clean_pdf_cache(cfg, apply=apply)
    payload = {
        "schema": "paperful.agent.json.v1",
        "command": "cache clean",
        "exit": 0,
        "summary": report,
    }

    def _human() -> None:
        action = "Removed" if apply else "Would remove"
        console.print(
            f"{action} {report['removed'] if apply else report['removable']} "
            f"file(s) under {report['cache_dir']}; kept {report['kept']}."
        )
        if not apply and report["removable"]:
            console.print("[dim]Re-run with --apply to delete them.[/]")

    json_out, _ = cli_mod._agent_wins(fmt)
    cli_mod._emit_agent(payload, json_out=json_out, human=_human)
