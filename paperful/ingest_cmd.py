"""``paperful ingest-dois`` implementation (CLI parses flags only)."""

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

def run_ingest_dois(
    console: Console,
    collection: Any,
    from_file: Any,
    from_pack: Any,
    apply: Any,
    dry_run: Any,
    tag: Any,
    profile: Any,
    run_config: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Create metadata parents from a DOI list. Dry-run unless --apply. Then run fills PDFs."""
    from . import cli_runtime as cli_mod

    from .identity import LibraryFingerprint
    from .ingest_dois import (
        apply_creates,
        classify_rows,
        default_resolver,
        dois_from_file,
        dois_from_refs_pack,
        ingest_tags,
        write_summary,
    )

    if apply and dry_run:
        console.print("[red]Pass either --dry-run or --apply, not both.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(cfg, profile=profile, run_config=run_config, collection=collection)
    collection, _library, _yf, _yt, _types = cli_mod._take_scope(bound)
    if not collection:
        cli_mod._refuse_missing_scope()
    if from_file is None and from_pack is None:
        console.print("[red]Pass --from-file dois.txt or --from-pack state/refs-gaps/.../pack.json[/]")
        raise typer.Exit(1)
    if from_pack is not None:
        pack_path = from_pack / "pack.json" if from_pack.is_dir() else from_pack
        dois = dois_from_refs_pack(pack_path)
        source_path = pack_path
    else:
        dois = dois_from_file(from_file)
        source_path = from_file
    if not dois:
        console.print("No DOIs to ingest.")
        raise typer.Exit(0)
    backend = cli_mod._connect(cfg, quiet=json_out)
    all_items = list(backend.items_in_scope(None)) if hasattr(backend, "items_in_scope") else []
    fingerprint = LibraryFingerprint.from_items(
        all_items,
        scope=cfg.ingest_dedupe_scope,
        collection=collection[0],
    )
    works = {}
    resolver = default_resolver(cfg.email)

    def resolve(doi: str):
        work = resolver(doi)
        if work is not None:
            works[doi] = work
        return work

    from .acronyms import load_acronym_allowlist

    allowed = load_acronym_allowlist(cfg.state_dir)
    batch = classify_rows(dois, fingerprint, resolve=resolve, allowlist=allowed)
    tags = ingest_tags(
        cli_tags=tag, default_tags=cfg.ingest_default_tags, from_file=source_path
    )
    if apply:
        cli_mod._require_manager(cfg)
        if not backend.supports_write():
            cli_mod._exit_env("ingest-dois --apply needs library write support.", cfg)
        apply_creates(
            backend, batch, collection[0], works=works, tags=tags, allowlist=allowed
        )
        cli_mod._flush(backend)
    folder = write_summary(cfg.state_dir, collection[0], batch)
    counts = batch.counts()
    from dataclasses import asdict as _asdict

    from .agent_json import envelope
    from .agent_ops import ingest_dois_exit

    payload = envelope(
        command="ingest-dois",
        summary=counts,
        items=[_asdict(row) for row in batch.rows],
        paths={"summary": str(folder)},
        flags={"apply": apply, "dry_run": not apply},
        exit_code=ingest_dois_exit(
            apply=apply, created=int(counts["created"]), failed=int(counts["failed"])
        ),
    )

    def _human_ingest() -> None:
        table = Table(title="ingest-dois")
        table.add_column("DOI")
        table.add_column("Status")
        table.add_column("Title")
        table.add_column("Detail")
        for row in batch.rows:
            table.add_row(row.doi, row.status, (row.title or "")[:50], row.detail)
        console.print(table)
        console.print(
            f"created {counts['created']} · exists {counts['exists']} · "
            f"unresolved {counts['unresolved']} · held {counts['held']}"
            + (" (dry-run)" if not apply else "")
        )
        console.print(f"Summary: {folder}")
        if apply and counts["created"]:
            console.print(f"Next: paperful run -C {collection[0]}")

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_ingest)

