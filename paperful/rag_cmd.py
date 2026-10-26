"""``paperful rag`` implementation (CLI parses flags only)."""

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

def run_rag_ingest(
    console: Console,
    item: Any,
    collection: Any,
    library: Any,
    force: Any,
    retry_failed: Any,
    no_ocr: Any,
    dry_run: Any,
    year_from: Any,
    year_to: Any,
    item_type: Any,
    limit: Any,
    profile: Any,
    run_config: Any,
    config: Any,
) -> None:
    """Index PDFs and abstracts from the mirror. Scans get OCR first; text PDFs do not."""
    from . import cli_runtime as cli_mod

    from .llm import LLMClientError
    from .rag.index import IndexMismatch, RagUnavailable
    from .rag.ingest import ingest_entries, select_entries

    if not item and cli_mod._scope_unset(collection, library, profile, run_config):
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    bound = cli_mod._bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
    )
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    limit = bound.limit
    if not item and not collection and not library:
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    cli_mod._rag_require(cfg)
    types = cli_mod._resolve_types(item_type)
    embedder = None if dry_run else cli_mod._rag_embedder(cfg)
    started = time.time()
    with cli_mod._spinner("Reading the mirror…"):
        entries = select_entries(
            cfg,
            collections=None if library else collection,
            item_keys=item,
            year_from=year_from,
            year_to=year_to,
            item_types=types,
        )
    scope = "library" if library else ", ".join(collection) or f"{len(item)} item(s)"
    whole_mirror = bool(library) and not item and types is None
    whole_mirror = whole_mirror and year_from is None and year_to is None
    try:
        with cli_mod._item_progress() as progress:
            batch = ingest_entries(
                cfg,
                entries,
                force=force,
                retry_failed=retry_failed,
                ocr=not no_ocr,
                dry_run=dry_run,
                prune=whole_mirror and limit is None,
                limit=limit,
                track=cli_mod._track(progress, "Indexing"),
                ocr_track=cli_mod._track(progress, "Running OCR"),
                embedder=embedder,
            )
    except (RagUnavailable, IndexMismatch) as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    except LLMClientError as exc:
        console.print(f"Stopped: {exc}", markup=False, style="red")
        console.print("Items indexed so far are kept. Run again to continue.")
        raise typer.Exit(1) from exc
    changed = [r for r in batch.rows if r.status not in ("unchanged", "nothing")]
    failed = [r for r in changed if r.status == "failed"]
    shown = changed if len(changed) <= 30 else failed[:30]
    if shown:
        table = Table(title="paperful rag ingest" + (" (dry-run)" if dry_run else ""))
        table.add_column("Key")
        table.add_column("Title")
        table.add_column("From")
        table.add_column("Passages", justify="right")
        table.add_column("Why")
        for row in shown:
            title = row.title if len(row.title) <= 60 else row.title[:57] + "…"
            table.add_row(row.key, title, row.status, str(row.chunks or ""), row.reason)
        console.print(table)
    summary = batch.summary()
    write_command_report(
        cfg,
        command="rag-ingest",
        scope=scope,
        summary=dict(summary),
        items=[
            {
                "itemKey": r.key,
                "title": r.title,
                "status": r.status,
                "reason": r.reason,
                "chunks": r.chunks,
            }
            for r in changed
        ],
        flags={
            "force": force,
            "retry_failed": retry_failed,
            "no_ocr": no_ocr,
            "dry_run": dry_run,
            "embed_model": cfg.rag_embed_model,
        },
        started=started,
    )
    lead = "Would index" if dry_run else "Indexed"
    console.print(
        f"{lead} {summary['pdf'] + summary['ocr']} PDFs "
        f"({summary['ocr']} after OCR) and {summary['abstract']} abstracts"
        + ("" if dry_run else f", {summary['chunks']} passages")
        + f". Unchanged {summary['unchanged']}, nothing to index "
        f"{summary['empty']}, removed {summary['removed']}, "
        f"failed {summary['failed']}."
    )
    if dry_run:
        console.print("Run without --dry-run to build the index.")

def run_rag_status(
    console: Console,
    json_out: Any,
    config: Any,
) -> None:
    """What the index holds and how far it is behind the mirror."""
    from . import cli_runtime as cli_mod

    from .rag.status import index_status
    from .store import mirror_entries

    cfg = cli_mod._cfg(config)
    with cli_mod._spinner("Reading the mirror…", json_out=json_out):
        status = index_status(cfg, mirror_entries(cfg.out_dir))
    if json_out:
        console.print(
            json.dumps(status, indent=2), soft_wrap=True, highlight=False, markup=False
        )
        return
    mirror = status["mirror"]
    table = Table(title="paperful rag status")
    table.add_column("What")
    table.add_column("Value")
    rows = [
        ("Enabled", "yes" if status["enabled"] else "no (rag.enabled is false)"),
        ("Embedding model", f"{status['embed_provider']} / {status['embed_model']}"),
        ("Index", status["path"] if status["exists"] else "not built yet"),
        ("Items indexed", str(status["items_pdf"] + status["items_abstract"])),
        ("  from PDF text", str(status["items_pdf"])),
        ("  from abstract only", str(status["items_abstract"])),
        ("Passages", str(status["chunks"])),
        ("Scans waiting for OCR", str(status["items_ocr_pending"])),
        ("PDFs that failed", str(status["items_with_error"])),
        ("Items with several PDFs (newest indexed)", str(status["items_multi_pdf"])),
        ("Mirror items", str(mirror["items"])),
        ("  with a PDF on disk", str(mirror["with_pdf"])),
        ("  PDF held by the manager only", str(mirror["pdf_not_in_mirror"])),
        ("Items a new ingest would touch", str(mirror["stale"])),
    ]
    for name, value in rows:
        table.add_row(name, value)
    console.print(table)
    if status["problem"]:
        console.print(status["problem"], markup=False, style="yellow")
    if mirror["pdf_not_in_mirror"]:
        console.print(
            f"[dim]{mirror['pdf_not_in_mirror']} items have a PDF in the reference "
            "manager that is not in the mirror. `paperful snapshot --pdfs all` "
            "copies them in.[/]"
        )
    if mirror["stale"]:
        console.print(
            "[dim]`paperful rag ingest --library` brings the index up to date.[/]"
        )

def run_rag_search(
    console: Console,
    query: Any,
    top_k: Any,
    item: Any,
    collection: Any,
    year_from: Any,
    year_to: Any,
    item_type: Any,
    json_out: Any,
    config: Any,
) -> None:
    """Show the indexed passages closest to a query. No chat model is used."""
    from . import cli_runtime as cli_mod

    from dataclasses import asdict

    from .llm import LLMClientError
    from .rag.retrieve import scope_keys, search

    cfg = cli_mod._cfg(config)
    cli_mod._rag_require(cfg)
    types = cli_mod._resolve_types(item_type)
    embedder = cli_mod._rag_embedder(cfg)
    index, ledger = cli_mod._rag_open(cfg)
    keys = scope_keys(
        ledger,
        collections=collection,
        item_keys=item,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
    )
    try:
        hits = search(
            cfg, query, k=top_k, keys=keys, embedder=embedder, index=index, ledger=ledger
        )
    except LLMClientError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    if json_out:
        console.print(
            json.dumps([asdict(h) for h in hits], indent=2, ensure_ascii=False),
            soft_wrap=True,
            highlight=False,
            markup=False,
        )
        return
    if not hits:
        console.print("[yellow]No passages match.[/]")
        return
    cli_mod._print_hits(hits)

def run_rag_questions(
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
    config: Any,
    fmt: Any,
) -> None:
    """Extract research questions from indexed papers (rules; optional LLM)."""
    from . import cli_runtime as cli_mod

    from dataclasses import asdict

    from .agent_json import batch_exit, envelope
    from .llm import get_client
    from .llm.preflight import validate_llm_for_ask
    from .llm.validate import LlmConfigError
    from .rag.questions import extract_scope, write_item

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    cli_mod._rag_require(cfg)
    if not (item or collection or library):
        console.print("[red]Pass --item, -C, or --library.[/]")
        raise typer.Exit(1)
    use_llm = cfg.rag_extract_questions_llm if llm is None else llm
    client = None
    if use_llm:
        try:
            validate_llm_for_ask(cfg)
        except LlmConfigError as exc:
            console.print(str(exc), markup=False, style="red")
            raise typer.Exit(1) from exc
        client = get_client(cfg)
    types = cli_mod._resolve_types(item_type)
    _, ledger = cli_mod._rag_open(cfg)
    started = time.time()
    items = extract_scope(
        cfg,
        ledger=ledger,
        collections=None if library and not collection else collection,
        item_keys=item,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
        use_llm=use_llm,
        client=client,
        limit=limit,
    )
    total_q = sum(len(it.questions) for it in items)
    if not dry_run:
        for it in items:
            write_item(cfg, it)
    if not json_out:
        action = "Would extract" if dry_run else "Extracted"
        console.print(
            f"{action} {total_q} question(s) from {len(items)} item(s)"
            + (" (LLM on)" if use_llm else "")
            + "."
        )
        for it in items:
            if not it.questions:
                continue
            console.print(f"[bold]{it.item_key}[/] {it.title}", markup=False)
            for q in it.questions:
                console.print(
                    f"  [{q.provenance}] {q.text}", markup=False, highlight=False
                )
    write_command_report(
        cfg,
        command="rag-questions",
        scope=", ".join(collection) or ("library" if library else "items"),
        summary={
            "items": len(items),
            "questions": total_q,
            "dry_run": dry_run,
            "llm": use_llm,
        },
        items=[asdict(it) for it in items],
        flags={"limit": limit, "llm": use_llm},
        started=started,
    )
    code = batch_exit(ok=len(items), failed=0)
    if json_out:
        payload = envelope(
            command="rag-questions",
            summary={"items": len(items), "questions": total_q, "dry_run": dry_run},
            items=[asdict(it) for it in items],
            flags={"read_only": dry_run, "llm": use_llm},
            exit_code=code,
        )
        cli_mod._emit_agent(payload, json_out=True, human=lambda: None)

def run_rag_answered(
    console: Console,
    from_file: Any,
    from_extract: Any,
    after_item: Any,
    item: Any,
    collection: Any,
    year_from: Any,
    year_to: Any,
    item_type: Any,
    top_k: Any,
    ask_mode: Any,
    force: Any,
    profile: Any,
    run_config: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Ask whether the corpus already answers research questions."""
    from . import cli_runtime as cli_mod

    from dataclasses import asdict

    from .agent_json import batch_exit, envelope
    from .llm import get_client, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_ask
    from .llm.validate import LlmConfigError
    from .rag.answered import (
        file_questions,
        questions_from_extract,
        run_answered,
        write_pack,
    )
    from .rag.retrieve import scope_keys
    from .snowball.command import SnowballError

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=None,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    if bound.collections:
        collection = list(bound.collections)
    if bound.year_from is not None:
        year_from = bound.year_from
    if bound.year_to is not None:
        year_to = bound.year_to
    if bound.types:
        item_type = list(bound.types)
    cli_mod._rag_require(cfg)
    if not from_file and not from_extract:
        console.print("[red]Pass --from-file or --from-extract.[/]")
        raise typer.Exit(1)
    try:
        validate_llm_for_ask(cfg)
    except LlmConfigError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    if llm_egress_is_remote(cfg) and not json_out:
        console.print(
            "[yellow]Remote LLM — excerpts from your PDFs leave this machine.[/]"
        )
    types = cli_mod._resolve_types(item_type)
    embedder = cli_mod._rag_embedder(cfg)
    index, ledger = cli_mod._rag_open(cfg)
    keys = scope_keys(
        ledger,
        collections=collection,
        item_keys=[] if from_extract else item,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
    )
    questions: list[tuple[str, str, int | None]] = []
    if from_file is not None:
        try:
            questions.extend(file_questions(str(from_file)))
        except SnowballError as exc:
            console.print(str(exc), markup=False, style="red")
            raise typer.Exit(1) from exc
    if from_extract:
        extract_keys = list(item) if item else None
        questions.extend(questions_from_extract(cfg, item_keys=extract_keys))
    if not questions:
        console.print("[red]No questions to check.[/]")
        raise typer.Exit(1)
    started = time.time()
    client = get_client(cfg)
    pack = run_answered(
        cfg,
        questions,
        keys=keys,
        after_item=after_item,
        k=top_k,
        force=force,
        scope={
            "collections": list(collection),
            "year_from": year_from,
            "year_to": year_to,
            "after_item": after_item,
        },
        client=client,
        embedder=embedder,
        index=index,
        ledger=ledger,
        ask_mode=ask_mode,
    )
    folder = write_pack(cfg, pack)
    if not json_out:
        console.print(
            f"Answered {pack.answered} · partial {pack.partial} · "
            f"not_found {pack.not_found} · failed {pack.failed} → {folder}"
        )
    write_command_report(
        cfg,
        command="rag-answered",
        scope=", ".join(collection) or "index",
        summary={
            "questions": pack.questions,
            "answered": pack.answered,
            "partial": pack.partial,
            "not_found": pack.not_found,
            "failed": pack.failed,
            "pack": str(folder),
        },
        items=[asdict(r) for r in pack.rows],
        flags={"focus": "answered", "after_item": after_item},
        started=started,
    )
    code = batch_exit(
        ok=pack.answered + pack.partial + pack.not_found, failed=pack.failed
    )
    if json_out:
        payload = envelope(
            command="rag-answered",
            summary={
                "questions": pack.questions,
                "answered": pack.answered,
                "partial": pack.partial,
                "not_found": pack.not_found,
                "pack": str(folder),
            },
            items=[asdict(r) for r in pack.rows],
            flags={"read_only": True, "after_item": after_item},
            exit_code=code,
        )
        cli_mod._emit_agent(payload, json_out=True, human=lambda: None)
        return
    if pack.failed:
        raise typer.Exit(1)

