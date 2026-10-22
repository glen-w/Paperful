"""``paperful doctor`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import Config
from .doctor import (
    Check,
    actionable_checks,
    has_red,
    remediation_text,
    run_checks,
)


def _in_docker() -> bool:
    """``cli.in_docker`` is the monkeypatch site used by tests."""
    import importlib

    return importlib.import_module("paperful.cli").in_docker()
def _collect_doctor_checks(cfg: Config, *, probe: bool = False) -> list[Check]:
    from . import cli_runtime as cli_mod

    try:
        return run_checks(cfg, cli_mod.ZoteroLocal(), probe=probe)
    except Exception:
        return run_checks(cfg, None, probe=probe)


def _print_doctor_table(console: Console, checks: list[Check]) -> None:
    table = Table(title="paperful doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    colour = {"green": "green", "amber": "yellow", "red": "red"}
    for ch in checks:
        table.add_row(ch.name, f"[{colour[ch.status]}]{ch.status}[/]", ch.detail)
    console.print(table)


def _wait_doctor_continue(console: Console) -> bool:
    """Wait for Enter. Return False if the user stops (EOF / interrupt)."""
    console.print("[dim]Press Enter when done (Ctrl-C to stop guide)…[/]")
    try:
        input()
        return True
    except EOFError:
        return False
    except KeyboardInterrupt:
        console.print("\n[dim]Guide stopped.[/]")
        return False


def _print_doctor_remediations(
    console: Console, cfg: Config, checks: list[Check]
) -> None:
    """Print amber/red fix steps once (no Enter wait)."""
    docker = _in_docker()
    pending = actionable_checks(checks, cfg, docker=docker)
    if not pending:
        return
    console.print("\n[bold]Fixes[/] — apply these, then re-run doctor.\n")
    for check, text in pending:
        colour = "red" if check.status == "red" else "yellow"
        console.print(f"[{colour}]• {check.name}[/] ({check.status})")
        console.print(f"[dim]{check.detail}[/]")
        console.print(text)
        console.print()


def _guide_doctor(
    console: Console,
    cfg: Config,
    checks: list[Check],
    *,
    probe: bool = False,
) -> list[Check]:
    """Walk amber/red remediations interactively; re-check after each step."""
    from . import cli_runtime as cli_mod

    docker = _in_docker()
    pending = actionable_checks(checks, cfg, docker=docker)
    if not pending:
        return checks

    console.print(
        "\n[bold]Guide[/] — fix the checks below one at a time. "
        "Sessions need a headed browser"
        + (" on the host" if docker else "")
        + "; this process only re-checks.\n"
    )
    for check, _text in pending:
        name = check.name
        checks = _collect_doctor_checks(cfg, probe=probe)
        current = next((c for c in checks if c.name == name), None)
        if current is None or current.status == "green":
            if current is not None:
                console.print(f"[green]✓ {name}[/] already green — skipping.")
            continue
        text = remediation_text(current, cfg, docker=docker)
        if not text:
            continue
        colour = "red" if current.status == "red" else "yellow"
        console.print(f"\n[{colour}]• {current.name}[/] ({current.status})")
        console.print(f"[dim]{current.detail}[/]")
        console.print(text)
        if not _wait_doctor_continue(console):
            break
        cfg = cli_mod._cfg(cfg.config_path)
        checks = _collect_doctor_checks(cfg, probe=probe)
        updated = next((c for c in checks if c.name == name), None)
        if updated is None:
            continue
        if updated.status == "green":
            console.print(f"[green]✓ {name} is green[/]")
        else:
            console.print(f"[yellow]Still {updated.status}:[/] {updated.detail}")

    console.print()
    _print_doctor_table(console, checks)
    return checks


def run_doctor(
    console: Console,
    *,
    config: Path | None,
    guide: bool | None,
    probe: bool,
    as_json: bool,
) -> None:
    """Check Zotero, paths, email, and optional browser sessions (green / amber / red)."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    checks = _collect_doctor_checks(cfg, probe=probe)
    if as_json:
        payload = [
            {
                "name": c.name,
                "status": c.status,
                "code": c.code,
                "detail": c.detail,
            }
            for c in checks
        ]
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        if has_red(checks):
            raise typer.Exit(2)
        return
    _print_doctor_table(console, checks)

    actionable = actionable_checks(checks, cfg)
    if guide is None:
        want_guide = cli_mod._stdin_is_tty() and not _in_docker()
    else:
        want_guide = guide
    if want_guide and actionable:
        checks = _guide_doctor(console, cfg, checks, probe=probe)
    elif actionable and not want_guide:
        _print_doctor_remediations(console, cfg, checks)
        if _in_docker():
            console.print(
                "[dim]Step-by-step re-check:[/] "
                "[bold]docker compose run --rm paperful doctor --guide[/]"
            )
        else:
            console.print(
                "[dim]Step-by-step re-check:[/] "
                "[bold]paperful doctor --guide[/]"
            )

    if has_red(checks):
        code = next((c.code for c in checks if c.status == "red" and c.code), "")
        cli_mod._print_exit_ladder(cfg, code=code, in_doctor=True)
        raise typer.Exit(2)
