"""``paperful extract-sections`` implementation (CLI parses flags only)."""

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

def run_extract_sections(
    console: Console,
    item: Any,
    collection: Any,
    library: Any,
    year_from: Any,
    year_to: Any,
    item_type: Any,
    llm: Any,
    limit: Any,
    dry_run: Any,
    force: Any,
    grobid: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Extract IMRaD-style sections to disk (rules; optional GROBID / LLM)."""
    from . import cli_runtime as cli_mod

    from .agent_json import batch_exit, envelope
    from .grobid_client import (
        GrobidConfigError,
        grobid_client_from_config,
        grobid_egress_is_remote,
    )
    from .llm import get_client
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError
    from .sections.command import extract_scope, item_to_dict, write_item

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    if not (item or collection or library):
        console.print("[red]Pass --item, -C, or --library.[/]")
        raise typer.Exit(1)
    use_llm = cfg.extract_sections_llm if llm is None else llm
    use_grobid = cfg.grobid_enabled if grobid is None else grobid
    client = None
    grobid_client = None
    if use_llm:
        try:
            validate_llm_for_verb(cfg)
        except LlmConfigError as exc:
            console.print(str(exc), markup=False, style="red")
            raise typer.Exit(1) from exc
        client = get_client(cfg)
    if use_grobid:
        try:
            grobid_client = grobid_client_from_config(cfg)
        except GrobidConfigError as exc:
            console.print(str(exc), markup=False, style="red")
            raise typer.Exit(1) from exc
        if grobid_egress_is_remote(cfg) and not json_out:
            console.print(
                "[yellow]GROBID is not local — PDF bytes leave this machine.[/]"
            )
    types = cli_mod._resolve_types(item_type)
    started = time.time()
    try:
        items = extract_scope(
            cfg,
            collections=collection or None,
            item_keys=item,
            library=library,
            year_from=year_from,
            year_to=year_to,
            item_types=types,
            use_llm=use_llm,
            client=client,
            limit=limit,
            force=force,
            skip_existing=not force,
            use_grobid=use_grobid,
            grobid=grobid_client,
        )
    finally:
        if grobid_client is not None:
            grobid_client.close()
    filled = sum(
        1
        for it in items
        for name in cfg.extract_sections_fields
        if it.fields.get(name) is not None
    )
    if not dry_run:
        for it in items:
            write_item(cfg, it)
    scope = ", ".join(collection) or ("library" if library else "items")
    if not json_out:
        action = "Would extract" if dry_run else "Extracted"
        console.print(
            f"{action} sections for {len(items)} item(s)"
            + (f" ({filled} field(s) present)" if items else "")
            + (" (LLM on)" if use_llm else "")
            + (" (GROBID on)" if use_grobid else "")
            + "."
        )
    write_command_report(
        cfg,
        command="extract-sections",
        scope=scope,
        summary={
            "items": len(items),
            "fields_present": filled,
            "dry_run": dry_run,
            "llm": use_llm,
            "grobid": use_grobid,
            "notes": sum(1 for it in items if it.notes),
        },
        items=[item_to_dict(it) for it in items],
        flags={"limit": limit, "llm": use_llm, "force": force, "grobid": use_grobid},
        started=started,
    )
    code = batch_exit(ok=len(items), failed=0)
    if json_out:
        payload = envelope(
            command="extract-sections",
            summary={
                "items": len(items),
                "fields_present": filled,
                "dry_run": dry_run,
            },
            items=[item_to_dict(it) for it in items],
            flags={
                "read_only": dry_run,
                "llm": use_llm,
                "force": force,
                "grobid": use_grobid,
            },
            exit_code=code,
        )
        cli_mod._emit_agent(payload, json_out=True, human=lambda: None)

