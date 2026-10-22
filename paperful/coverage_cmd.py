"""``paperful coverage`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
import typer
from .runreport import write_command_report
from rich.table import Table


def run_coverage(
    console: Console,
    *,
    collection: list[str],
    from_note: str | None,
    from_file: Path | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    """DOIs named in a briefing/note/file that are not filed under -C. Always dry-run."""
    from . import cli_runtime as cli_mod

    from .coverage import (
        classify_mentions,
        extract_mentions,
        load_text_from_note,
        write_pack,
    )
    from .identity import LibraryFingerprint

    if bool(from_note) == bool(from_file):
        console.print("[red]Pass exactly one of --from-note or --from-file.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(
        cfg, profile=profile, run_config=run_config, collection=collection
    )
    collection, _library, _yf, _yt, _types = cli_mod._take_scope(bound)
    if not collection:
        cli_mod._refuse_missing_scope()
    backend = cli_mod._connect(cfg, quiet=json_out)
    try:
        if from_file is not None:
            text = from_file.read_text(encoding="utf-8")
            source = {"kind": "file", "ref": str(from_file)}
        else:
            text, source = load_text_from_note(
                backend, from_note or "", out_dir=cfg.out_dir
            )
    except LookupError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    except OSError as exc:
        console.print(f"[red]Could not read source: {exc}[/]")
        raise typer.Exit(1) from exc

    mentions = extract_mentions(text)
    all_items = (
        list(backend.items_in_scope(None))
        if hasattr(backend, "items_in_scope")
        else []
    )
    collection_fp = LibraryFingerprint.from_items(
        all_items, scope="collection", collection=collection[0]
    )
    library_fp = LibraryFingerprint.from_items(all_items, scope="library")
    rows = classify_mentions(mentions, collection_fp, library_fp)
    scope = collection[0]
    folder = write_pack(cfg.state_dir, scope, rows, source)
    missing = [r for r in rows if r.status == "missing"]
    ambiguous = [r for r in rows if r.status == "ambiguous"]
    write_command_report(
        cfg,
        command="coverage",
        scope=scope,
        summary={
            "mentioned": len(rows),
            "in_collection": sum(1 for r in rows if r.status == "in_collection"),
            "missing": len(missing),
            "ambiguous": len(ambiguous),
            "write_api": None,
        },
        items=[
            {
                "doi": r.doi,
                "title": r.title,
                "status": r.status,
                "suggested_action": r.suggested_action,
            }
            for r in rows
            if r.status != "in_collection"
        ][:200],
        flags={"dry_run": True, **source},
        extra_paths={"pack": str(folder)},
        bound=bound,
    )
    from .agent_ops import coverage_envelope

    payload = coverage_envelope(rows=rows, folder=folder, flags=source)

    def _human_cov() -> None:
        table = Table(title="coverage")
        table.add_column("Status")
        table.add_column("DOI")
        table.add_column("Title")
        table.add_column("Action")
        show = [r for r in rows if r.status != "in_collection"][:50]
        for row in show:
            table.add_row(
                row.status,
                row.doi or "",
                (row.title or "")[:50],
                row.suggested_action,
            )
        console.print(table)
        console.print(
            f"Mentioned {len(rows)} · in collection "
            f"{sum(1 for r in rows if r.status == 'in_collection')} · "
            f"missing {len(missing)} · ambiguous {len(ambiguous)}"
        )
        console.print(f"Pack: {folder}")
        console.print(
            f"Next: paperful ingest-dois --from-file {folder / 'dois.txt'} "
            f"-C {scope} --dry-run"
        )

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_cov)
