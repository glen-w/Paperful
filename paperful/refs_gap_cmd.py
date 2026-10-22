"""``paperful refs gap`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
import typer
from .runreport import write_command_report
from rich.table import Table


def run_refs_gap(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    item: list[str],
    pdf: list[Path],
    dedupe_scope: str,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    """Works cited inside collection PDFs that are not in the library. Never writes."""
    from . import cli_runtime as cli_mod

    from .identity import LibraryFingerprint
    from .mirror import pdf_for
    from .refs_gap import (
        ScanFinding,
        aggregate_citations,
        scan_items,
        scan_pdf_citations,
        write_pack,
    )

    if cli_mod._scope_unset(collection, library, profile, run_config) and not item and not pdf:
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    backend = cli_mod._connect(cfg, quiet=json_out)
    loaded = cli_mod._load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library) or not collection,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items = loaded.items
    scope = loaded.label
    if item:
        want = set(item)
        items = [it for it in items if it.key in want]
        if not items and not pdf:
            console.print("[red]No matching --item keys in scope.[/]")
            raise typer.Exit(1)
    fingerprint = LibraryFingerprint.from_items(
        list(backend.items_in_scope(None)) if hasattr(backend, "items_in_scope") else items,
        scope=dedupe_scope,
        collection=collection[0] if collection else "",
    )

    def _pdf(it):
        return pdf_for(cfg.out_dir, it)

    refs, findings = scan_items(items, _pdf, fingerprint)
    extra_sources = []
    for path in pdf:
        entries, finding = scan_pdf_citations(path)
        findings.append(ScanFinding(item_key=f"pdf:{path.name}", path=str(path), finding=finding))
        if finding == "ok":
            extra_sources.append((f"pdf:{path.name}", entries))
    if extra_sources:
        extra_refs = aggregate_citations(extra_sources, fingerprint)
        by_id = {(r.doi or r.title, r.year): r for r in refs}
        for row in extra_refs:
            ident = (row.doi or row.title, row.year)
            if ident in by_id:
                host = by_id[ident]
                for key in row.citing_keys:
                    if key not in host.citing_keys:
                        host.citing_keys.append(key)
            else:
                refs.append(row)
    folder = write_pack(cfg.state_dir, scope, refs, findings)
    missing = [r for r in refs if not r.already_exists]
    ocr_n = sum(1 for f in findings if f.finding == "needs_ocr")
    write_command_report(
        cfg,
        command="refs gap",
        scope=scope,
        summary={
            "cited": len(refs),
            "missing": len(missing),
            "needs_ocr": ocr_n,
            "write_api": None,
        },
        items=[
            {
                "doi": r.doi,
                "title": r.title,
                "suggested_action": r.suggested_action,
            }
            for r in missing[:200]
        ],
        flags={"dry_run": True, "dedupe_scope": dedupe_scope},
        extra_paths={"pack": str(folder)},
        bound=bound,
    )
    from .agent_ops import refs_gap_envelope

    payload = refs_gap_envelope(
        refs=refs,
        findings=findings,
        folder=folder,
        flags={"dedupe_scope": dedupe_scope},
    )

    def _human_gap() -> None:
        table = Table(title="refs gap")
        table.add_column("n")
        table.add_column("DOI")
        table.add_column("Title")
        table.add_column("Action")
        for row in sorted(missing, key=lambda r: (-len(r.citing_keys), r.doi or r.title))[:50]:
            table.add_row(
                str(len(row.citing_keys)),
                row.doi or "",
                (row.title or "")[:50],
                row.suggested_action,
            )
        console.print(table)
        console.print(f"Cited {len(refs)} · missing {len(missing)} · needs_ocr {ocr_n}")
        console.print(f"Pack: {folder}")
        console.print(
            f"Next: paperful ingest-dois --from-file {folder / 'dois.txt'} -C <collection> --dry-run"
        )

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_gap)
