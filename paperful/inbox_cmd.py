"""``paperful inbox`` implementation (CLI parses flags only)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .library import LibraryError
from .runreport import write_command_report
from .store import Manifest


def run_inbox_watch(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    idle: float | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    tag: list[str],
) -> None:
    """Long-running sidecar: poll inbox.dir and attach by PDF DOI (no FIFO).

Defaults to the whole library so one drop folder can serve every topic.
Pass ``-C`` only when you intentionally want a narrower DOI index."""
    from . import cli_runtime as cli_mod

    from .inbox import (
        ensure_inbox_dirs,
        events_as_report_items,
        process_candidates,
        summary_from_stats,
    )

    library = cli_mod._inbox_library_when_unscoped(collection, library, profile, run_config)
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
    )
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    if not collection and not library:
        cli_mod._refuse_missing_scope()
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg)
    if not backend.supports_write():
        cli_mod._exit_env("inbox watch needs library write support.", cfg)
    try:
        root = ensure_inbox_dirs(cfg)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    loaded = cli_mod._load_scope(
        backend,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    manifest = Manifest(cfg.manifest_path)
    started = time.time()
    console.print(
        f"[bold]Inbox[/] watching {root} for {scope} (DOI match only; Ctrl+C to stop)"
    )
    stats = process_candidates(
        cfg,
        backend,
        manifest,
        items,
        fifo_queue=None,
        once=False,
        idle_seconds=idle,
        collection=collection[0] if collection else "",
        extra_tags=tag,
        on_status=lambda msg: console.print(msg),
    )
    cli_mod._flush(backend)
    cli_mod._rag_auto(cfg, started)
    path = write_command_report(
        cfg,
        command="inbox",
        scope=scope,
        summary=summary_from_stats(stats),
        items=events_as_report_items(stats.events),
        flags={"once": False, "fifo": False, "idle": idle},
        started=started,
        extra_paths={"inbox_dir": str(root)},
    )
    console.print(
        f"Inbox attached {stats.attached}, unmatched {stats.unmatched}, "
        f"created_gated {stats.created_gated}, created_auto {stats.created_auto}, "
        f"errors {stats.errors}, skipped {stats.skipped}"
        + (f" ({stats.quit_reason})" if stats.quit_reason else "")
    )
    if path is not None:
        console.print(f"Inbox report: {path}")



def run_inbox_drain(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    tag: list[str],
    fmt: str,
) -> None:
    """One-shot: ingest current PDFs in inbox.dir.

Default match is DOI-only. ``[inbox].match`` can add title / OCR / LLM stages.
Defaults to the whole library so one drop folder can serve every topic.
Pass ``-C`` only when you intentionally want a narrower DOI index."""
    from . import cli_runtime as cli_mod

    from .inbox import (
        ensure_inbox_dirs,
        events_as_report_items,
        process_candidates,
        summary_from_stats,
    )

    library = cli_mod._inbox_library_when_unscoped(collection, library, profile, run_config)
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
    if not collection and not library:
        cli_mod._refuse_missing_scope()
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg, quiet=json_out)
    if not backend.supports_write():
        cli_mod._exit_env("inbox drain needs library write support.", cfg)
    try:
        root = ensure_inbox_dirs(cfg)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    loaded = cli_mod._load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    manifest = Manifest(cfg.manifest_path)
    started = time.time()
    if not json_out:
        console.print(f"[bold]Inbox[/] draining {root} for {scope}")
    stats = process_candidates(
        cfg,
        backend,
        manifest,
        items,
        fifo_queue=None,
        once=True,
        collection=collection[0] if collection else "",
        extra_tags=tag,
        on_status=None if json_out else (lambda msg: console.print(msg)),
    )
    cli_mod._flush(backend)
    cli_mod._rag_auto(cfg, started)
    summary = summary_from_stats(stats)
    items_out = events_as_report_items(stats.events)
    path = write_command_report(
        cfg,
        command="inbox",
        scope=scope,
        summary=summary,
        items=items_out,
        flags={"once": True, "fifo": False},
        started=started,
        extra_paths={"inbox_dir": str(root)},
    )
    from .agent_json import batch_exit, envelope

    payload = envelope(
        command="inbox drain",
        summary=summary,
        items=items_out,
        paths={"report": str(path) if path else "", "inbox_dir": str(root)},
        flags={"once": True},
        exit_code=batch_exit(ok=int(stats.attached or 0), failed=int(stats.errors or 0)),
    )

    def _human_drain() -> None:
        console.print(
            f"Inbox attached {stats.attached}, unmatched {stats.unmatched}, "
            f"created_gated {stats.created_gated}, created_auto {stats.created_auto}, "
            f"errors {stats.errors}, skipped {stats.skipped}"
        )
        if path is not None:
            console.print(f"Inbox report: {path}")

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_drain)



def run_inbox_proposals_list(
    console: Console,
    *,
    status: str,
    config: Path | None,
    fmt: str,
) -> None:
    """"""
    from . import cli_runtime as cli_mod

    from .inbox_match import list_proposals
    from .agent_json import envelope

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    want = None if status == "all" else status
    rows = list_proposals(cfg, status=want)
    payload = envelope(
        command="inbox proposals list",
        summary={"count": len(rows)},
        items=rows,
        flags={"status": status},
    )

    def _human() -> None:
        if not rows:
            console.print("No inbox proposals.")
            return
        table = Table(title="inbox proposals")
        table.add_column("id")
        table.add_column("action")
        table.add_column("doi")
        table.add_column("title")
        table.add_column("status")
        for row in rows:
            table.add_row(
                str(row.get("id") or ""),
                str(row.get("action") or ""),
                str(row.get("doi") or ""),
                str(row.get("title") or "")[:60],
                str(row.get("status") or ""),
            )
        console.print(table)

    cli_mod._emit_agent(payload, json_out=json_out, human=_human)



def run_inbox_proposals_apply(
    console: Console,
    *,
    proposal_id: str,
    tag: list[str],
    config: Path | None,
    fmt: str,
) -> None:
    """"""
    from . import cli_runtime as cli_mod

    from .inbox import apply_proposal
    from .agent_json import envelope

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg, quiet=json_out)
    if not backend.supports_write():
        cli_mod._exit_env("inbox proposals apply needs library write support.", cfg)
    manifest = Manifest(cfg.manifest_path)
    try:
        data = apply_proposal(cfg, backend, manifest, proposal_id, extra_tags=tag)
    except (FileNotFoundError, ValueError, LibraryError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    cli_mod._flush(backend)
    payload = envelope(
        command="inbox proposals apply",
        summary={
            "id": proposal_id,
            "item_key": data.get("item_key") or "",
            "action": data.get("action") or "",
        },
        items=[data],
        flags={"apply": True},
    )

    def _human_apply() -> None:
        console.print(
            f"Applied proposal {proposal_id} → {data.get('item_key') or data.get('action')}"
        )

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_apply)



def run_inbox_proposals_reject(
    console: Console,
    *,
    proposal_id: str,
    config: Path | None,
    fmt: str,
) -> None:
    """"""
    from . import cli_runtime as cli_mod

    from .inbox import reject_proposal
    from .agent_json import envelope

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    try:
        data = reject_proposal(cfg, proposal_id)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    payload = envelope(
        command="inbox proposals reject",
        summary={"id": proposal_id, "status": data.get("status") or "rejected"},
        items=[data],
    )

    def _human_reject() -> None:
        console.print(f"Rejected proposal {proposal_id}")

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_reject)

