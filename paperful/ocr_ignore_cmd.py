"""``paperful ocr-ignore`` — manage the OCR failure skip list."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .ocr_ignore import OcrIgnoreList, import_failures_from_report, latest_ocr_report


def run_ocr_ignore_list(console: Console, *, config: Path | None) -> None:
    from . import cli as cli_mod

    cfg = cli_mod._cfg(config)
    ignores = OcrIgnoreList(cfg.ocr_ignore_path)
    rows = ignores.list_entries()
    if not rows:
        console.print(f"No ignored items ({cfg.ocr_ignore_path}).")
        return
    table = Table(title="OCR ignore list")
    table.add_column("Key")
    table.add_column("Source")
    table.add_column("Reason")
    for entry in rows:
        reason = entry.reason if len(entry.reason) <= 80 else entry.reason[:77] + "…"
        table.add_row(entry.itemKey, entry.source, reason)
    console.print(table)
    console.print(f"{len(rows)} item(s) · {cfg.ocr_ignore_path}")


def run_ocr_ignore_add(
    console: Console,
    *,
    item: list[str],
    reason: str,
    config: Path | None,
) -> None:
    from . import cli as cli_mod

    if not item:
        console.print("[red]Give at least one --item KEY.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    ignores = OcrIgnoreList(cfg.ocr_ignore_path)
    for key in item:
        ignores.add(key, reason or "manual", source="manual")
    console.print(f"Added {len(item)} item(s) to {cfg.ocr_ignore_path}")


def run_ocr_ignore_remove(
    console: Console,
    *,
    item: list[str],
    config: Path | None,
) -> None:
    from . import cli as cli_mod

    if not item:
        console.print("[red]Give at least one --item KEY.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    ignores = OcrIgnoreList(cfg.ocr_ignore_path)
    removed = sum(1 for key in item if ignores.remove(key))
    console.print(f"Removed {removed} item(s) from the ignore list.")


def run_ocr_ignore_import_failures(
    console: Console,
    *,
    report: Path | None,
    config: Path | None,
) -> None:
    from . import cli as cli_mod

    cfg = cli_mod._cfg(config)
    path = report
    if path is None:
        path = latest_ocr_report(cfg.state_dir)
    if path is None or not path.is_file():
        console.print("[red]No OCR run report found. Pass --report PATH.[/]")
        raise typer.Exit(1)
    pairs = import_failures_from_report(path)
    if not pairs:
        console.print(f"No failed or missing rows in {path}")
        return
    ignores = OcrIgnoreList(cfg.ocr_ignore_path)
    for key, why in pairs:
        ignores.add(key, why, source="auto")
    console.print(f"Added {len(pairs)} item(s) from {path.name} → {cfg.ocr_ignore_path}")
