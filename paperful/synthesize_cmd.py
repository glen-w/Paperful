"""``paperful synthesize`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .config import wants_disk, wants_zotero
from .library import LibraryError
from .runreport import ItemOutcome, build_report, write_run_report

def run_synthesize(
    console: Console,
    *,
    item: list[str],
    collection: list[str],
    library: bool | None,
    to_dest: str | None,
    report_collection: str | None,
    prompt: Path | None,
    dry_run: bool,
    force: bool,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod

    from .llm import LLMClientError, get_client, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError
    from .synthesize import (
        ReduceCapError,
        SynthesisEvent,
        prepare_synthesis,
        report_is_current,
        write_synthesis,
    )

    if not item and cli_mod._scope_unset(collection, library, profile, run_config):
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
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
        limit=limit,
    )
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    limit = bound.limit
    if not item and not collection and not library:
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    dest = to_dest if to_dest is not None else cfg.synthesize_dest
    if report_collection and not wants_zotero(dest):
        console.print(
            "[red]--report-collection files a Zotero note; it conflicts with --to disk.[/]"
        )
        raise typer.Exit(1)
    cli_mod._require_manager(cfg)
    try:
        validate_llm_for_verb(cfg)
    except LlmConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    if llm_egress_is_remote(cfg) and not dry_run:
        console.print(
            "[yellow]Remote LLM — summary text may leave this machine for this run.[/]"
        )
    if prompt is not None:
        cfg.synthesize_prompt_template = str(prompt.expanduser().resolve())
    backend = cli_mod._connect(cfg, quiet=json_out)
    loaded = cli_mod._load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        item_keys=item,
    )
    items, scope = loaded.items, loaded.label
    items.sort(
        key=lambda it: (it.year or 9999, (it.first_author or "").lower(), it.key)
    )
    if limit:
        items = items[:limit]
    targets = []
    if wants_zotero(dest):
        if report_collection:
            try:
                targets = [backend.resolve_collection(report_collection)]
            except LookupError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1)
        elif collection:
            seen_keys: set[str] = set()
            for spec in collection:
                try:
                    root = backend.resolve_collection(spec)
                except LookupError as exc:
                    console.print(f"[red]{exc}[/]")
                    raise typer.Exit(1)
                if root.key not in seen_keys:
                    seen_keys.add(root.key)
                    targets.append(root)
        else:
            console.print(
                "[red]Pass -C or --report-collection to file the Zotero note, or --to disk.[/]"
            )
            raise typer.Exit(1)
    slug_parts = []
    if library:
        slug_parts.append("library")
    slug_parts.extend(collection)
    slug_parts.extend(item)
    if year_from is not None or year_to is not None:
        slug_parts.append(f"{year_from or ''}-{year_to or ''}")
    types = cli_mod._resolve_types(item_type)
    if types:
        slug_parts.extend(sorted(types))
    with cli_mod._item_progress(json_out=json_out) as progress:
        prepared = prepare_synthesis(
            cfg,
            items,
            backend,
            slug_parts,
            track=cli_mod._track(progress, "Reading summaries"),
        )
    sources, missing, slug = prepared.sources, prepared.missing, prepared.slug
    plan = prepared.chunks
    on_disk = sum(1 for src in sources if src.origin == "disk")
    from_note = sum(1 for src in sources if src.origin == "note")
    if dry_run:
        console.print(
            f"Sources: {on_disk} on disk, {from_note} from Zotero notes, {len(missing)} missing"
        )
        if plan:
            sizes = ", ".join(str(n) for n in plan)
            console.print(f"Chunks: {len(plan)} ({sizes} chars)")
        else:
            console.print("[yellow]No summary notes in scope.[/]")
        if wants_disk(dest):
            console.print(f"Disk: {cfg.reports_dir / (slug + '.html')}")
        for root in targets:
            console.print(f"Zotero: {root.path} ({root.key})")
        raise typer.Exit(0)
    if not sources:
        console.print(
            "[yellow]No summary notes in scope.[/] Run [bold]paperful summarize[/] first."
        )
        raise typer.Exit(0)
    if not force and report_is_current(cfg, slug, sources, dest=dest):
        console.print(
            f"Report up to date ({len(sources)} summaries unchanged). Pass [bold]--force[/] to regenerate."
        )
        raise typer.Exit(0)
    started = time.time()

    def _announce(event: SynthesisEvent) -> None:
        if event.kind == "html":
            console.print(f"[green]Wrote[/] {event.path}")
        elif event.kind == "note":
            console.print(
                f"  attached note {event.note_key} in {event.collection_path}"
            )
        elif event.kind == "json":
            console.print(f"[green]Wrote[/] {event.path}")

    try:
        with cli_mod._spinner("Writing the report…", json_out=json_out):
            written = write_synthesis(
                cfg,
                sources=sources,
                missing=missing,
                scope=scope,
                slug=slug,
                dest=dest,
                targets=targets,
                backend=backend,
                client=get_client(cfg),
                log=lambda line: console.print(f"[dim]{line}[/]"),
                announce=_announce,
            )
    except ReduceCapError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    except LibraryError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    except (OSError, ValueError, LLMClientError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    n_chunks = written.n_chunks
    outcomes = [
        ItemOutcome(
            itemKey=src.key, title=src.title, status="summarized", reason=src.origin
        )
        for src in sources
    ]
    outcomes.extend(
        ItemOutcome(itemKey=it.key, title=it.title, status="missing_summary")
        for it in missing
    )

    class _Stats:
        pass

    stats = _Stats()
    stats.started_at = started
    stats.finished_at = time.time()
    stats.items = outcomes
    stats.scope = scope
    report = build_report(
        stats,
        cfg,
        command="synthesize",
        scope=scope,
        flags={
            "to": dest,
            "chunks": n_chunks,
            "included": len(sources),
            "missing": len(missing),
            "slug": slug,
        },
    )
    report["summary"]["included"] = len(sources)
    report["summary"]["missing"] = len(missing)
    report["summary"]["chunks"] = n_chunks
    path = write_run_report(cfg, report, as_last_run=False)
    from .agent_json import envelope

    payload = envelope(
        command="synthesize",
        summary={
            "included": len(sources),
            "missing": len(missing),
            "chunks": n_chunks,
        },
        paths={"report": str(path) if path else ""},
        flags={"to": dest, "slug": slug},
    )
    cli_mod._emit_agent(
        payload,
        json_out=json_out,
        human=lambda: console.print(
            f"Synthesized {len(sources)} summaries ({len(missing)} not included) → {path}"
        ),
    )
    cli_mod._flush(backend)
