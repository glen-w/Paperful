"""``paperful report`` and export-proposals implementation (CLI parses flags only)."""

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
from .runreport import print_run_summary, write_command_report, write_run_report
from .store import Manifest, STATUS_ATTACHED, STATUS_NOT_FOUND

def run_report(
    console: Console,
    config: Any,
    not_found: Any,
    status: Any,
    as_json: Any,
    last_run: Any,
) -> None:
    """Summarise the manifest and the latest auditable run report."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    manifest = Manifest(cfg.manifest_path)
    last = cli_mod._load_last_run(cfg)
    if as_json:
        payload = manifest.report_payload(last)
        console.print(json.dumps(payload, indent=2))
        raise typer.Exit(0)
    if last and last.get("schema") == "paperful.run_report.v1":
        print_run_summary(console, last, cfg.state_dir / "last-run.json")
        if last_run:
            raise typer.Exit(0)
        console.print()
    elif last_run:
        console.print("No auditable run report yet. Run [bold]paperful run[/] first.")
        raise typer.Exit(1)
    if not manifest.records:
        console.print("Manifest is empty.")
        raise typer.Exit(0)
    table = Table(title=f"{len(manifest.records)} items in manifest (all runs)")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for k, v in sorted(manifest.counts().items(), key=lambda kv: -kv[1]):
        table.add_row(k, str(v))
    console.print(table)
    by_src = manifest.by_source()
    if by_src:
        console.print(
            "PDFs by source: "
            + ", ".join(
                f"{k}={v}" for k, v in sorted(by_src.items(), key=lambda kv: -kv[1])
            )
        )
    want = STATUS_NOT_FOUND if not_found else status
    if want:
        rows = [r for r in manifest.records.values() if r.status == want]
        t = Table(title=f"{len(rows)} items with status {want}")
        t.add_column("Key", style="dim")
        t.add_column("Title")
        t.add_column("DOI")
        t.add_column("Attempts" if want != STATUS_ATTACHED else "Path")
        for r in sorted(rows, key=lambda r: r.title.lower()):
            t.add_row(
                r.itemKey,
                r.title[:70],
                r.doi or "-",
                (
                    (r.path or "")
                    if want == STATUS_ATTACHED
                    else " ".join(r.attempts)[-90:]
                ),
            )
        console.print(t)

def run_export_proposals(
    console: Console,
    pack: Any,
    dest: Any,
    fmt: Any,
    config: Any,
) -> None:
    """Export BibTeX or RIS from an on-disk snowball or authorwatch proposal pack."""
    from . import cli_runtime as cli_mod

    from .pack_bib import export_pack_text

    cfg = cli_mod._cfg(config)
    kind = (fmt or dest.suffix.lstrip(".") or "").lower().replace("_", "-")
    if kind in {"bib", "biblatex"}:
        kind = "bibtex"
    if kind not in {"ris", "bibtex"}:
        console.print("[red]--format must be bibtex or ris.[/]")
        raise typer.Exit(1)
    path = pack
    if not path.is_absolute():
        path = cfg.state_dir / path
    try:
        text, jsonl, n = export_pack_text(path, kind)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    console.print(
        f"[green]Wrote[/] {dest} ({n} records from {jsonl.name})"
    )

def run_report_counts(
    console: Console,
    report_file: Any,
) -> None:
    """One-line counts summary for Nightshift index lines."""
    from . import cli_runtime as cli_mod

    import json

    from .runreport import nightshift_counts_line

    payload = json.loads(report_file.read_text(encoding="utf-8"))
    print(nightshift_counts_line(payload))

def run_report_new_count(
    console: Console,
    report_file: Any,
) -> None:
    """Count new model summaries in a run report (skips do not count)."""
    from . import cli_runtime as cli_mod

    import json

    from .runreport import nightshift_report_new_count

    payload = json.loads(report_file.read_text(encoding="utf-8"))
    print(nightshift_report_new_count(payload))

