"""``paperful glossary`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table


def run_glossary_validate(
    console: Console,
    *,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .glossary import SCHEMA, load_glossary, resolve_glossary_dir

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    entries, issues = load_glossary(cfg)
    root = resolve_glossary_dir(cfg)
    errors = [row for row in issues if row.level == "error"]
    warnings = [row for row in issues if row.level != "error"]
    exit_code = 1 if errors else 0

    def _human() -> None:
        console.print(
            f"Glossary [bold]{root}[/] — {len(entries)} "
            f"entr{'y' if len(entries) == 1 else 'ies'} ({SCHEMA})"
        )
        if entries:
            table = Table(title="Entries")
            table.add_column("Token")
            table.add_column("Expansion")
            table.add_column("Aliases", justify="right")
            for entry in entries:
                table.add_row(entry.token, entry.expansion, str(len(entry.aliases)))
            console.print(table)
        elif not root.is_dir():
            console.print(
                "[dim]No glossary directory yet. Add state/glossary/*.json.[/]"
            )
        else:
            console.print("[dim]No glossary entries.[/]")
        for row in warnings:
            console.print(f"[yellow]{row.path}: {row.message}[/]")
        for row in errors:
            console.print(f"[red]{row.path}: {row.message}[/]")

    payload = envelope(
        command="glossary validate",
        summary={
            "entries": len(entries),
            "errors": len(errors),
            "warnings": len(warnings),
        },
        items=[
            {
                "token": entry.token,
                "expansion": entry.expansion,
                "aliases": list(entry.aliases),
            }
            for entry in entries
        ],
        paths={"glossary_dir": str(root)},
        flags={"schema": SCHEMA},
        exit_code=exit_code,
    )
    cli_mod._emit_agent(payload, json_out=json_out, human=_human)


def run_glossary_export_vale(
    console: Console,
    *,
    config: Path | None,
    fmt: str,
    out: Path | None,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .glossary import load_glossary, vale_swap_yaml

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    entries, issues = load_glossary(cfg)
    errors = [row for row in issues if row.level == "error"]
    yaml_text = vale_swap_yaml(entries)
    written = ""
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml_text, encoding="utf-8")
        written = str(out)

    def _human() -> None:
        for row in errors:
            console.print(f"[red]{row.path}: {row.message}[/]")
        alias_n = sum(len(entry.aliases) for entry in entries)
        if not entries:
            console.print("[dim]No glossary entries. Nothing to export.[/]")
        elif alias_n == 0:
            console.print("[dim]No aliases. Vale swap list is empty.[/]")
        if written:
            console.print(f"Wrote [bold]{written}[/]")
            return
        console.print(yaml_text, markup=False)

    payload = envelope(
        command="glossary export-vale",
        summary={
            "entries": len(entries),
            "aliases": sum(len(entry.aliases) for entry in entries),
            "errors": len(errors),
        },
        paths={"out": written},
        flags={"stdout": not written},
        exit_code=1 if errors else 0,
    )
    if json_out:
        payload["summary"]["yaml"] = yaml_text
    cli_mod._emit_agent(payload, json_out=json_out, human=_human)
