"""``paperful since`` implementation (CLI parses flags only)."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import typer
from rich.console import Console

from .runreport import write_command_report


def run_since(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    since: str,
    limit: int | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    """Diff the mirror against the last run report. Always dry-run."""
    from . import cli_runtime as cli_mod
    from .agent_ops import since_envelope
    from .handoff_rank import cite_index
    from .pipeline import make_client
    from .routing import sources_for_item
    from .screen import lookup_doi_status
    from .since import (
        NOTHING_CHANGED,
        find_baseline,
        healed_rows,
        prior_status,
        probe_item,
        status_rows,
        write_pack,
    )
    from .sources import Context

    before: date | None = None
    if since.strip():
        try:
            before = date.fromisoformat(since.strip())
        except ValueError:
            console.print("[red]--since takes a date as YYYY-MM-DD.[/]")
            raise typer.Exit(1) from None
    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    started = time.time()
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
    )
    collection, library, *_ = cli_mod._take_scope(bound)
    backend = cli_mod._connect(cfg, quiet=json_out)
    keys, scope = cli_mod._scope_keys(backend, collection, bool(library))
    items = backend.items_in_scope(keys)
    sources = list(bound.sources or cfg.sources or [])

    notes: list[str] = []
    baseline = find_baseline(cfg.state_dir, scope, before=before)
    seen, compared_to = prior_status(cfg.state_dir, scope)
    client = make_client(cfg)
    try:
        with cli_mod._spinner("Checking retraction status…", json_out=json_out) as say:
            ctx = Context(config=cfg, client=client)
            holdings = status_rows(
                items,
                lambda doi: lookup_doi_status(client, cfg, doi, refresh=True),
                seen,
                compared_to,
            )
            healed: list[dict] = []
            counts = {"healed_candidates": 0, "probed": 0}
            say("Probing earlier misses…")
            if baseline is None:
                when = f" on or before {before.isoformat()}" if before else ""
                notes.append(
                    f"No run report for this scope{when}: healed misses not compared."
                )
            else:
                healed, counts = healed_rows(
                    baseline,
                    items,
                    lambda item: probe_item(
                        item, ctx, sources_for_item(item, cfg, sources)
                    ),
                    cite_index(cfg.state_dir),
                    limit=limit,
                )
                if counts["probed"] < counts["healed_candidates"]:
                    notes.append(
                        f"Probed {counts['probed']} of {counts['healed_candidates']} "
                        "earlier misses (--limit)."
                    )
    finally:
        client.close()

    folder = write_pack(cfg.state_dir, scope, baseline, holdings, healed, counts, notes)
    write_command_report(
        cfg,
        command="since",
        scope=scope,
        summary={"holdings": len(holdings), "healed": len(healed), **counts},
        items=[*holdings, *healed][:200],
        flags={"dry_run": True, "since": since.strip(), "limit": limit},
        started=started,
        extra_paths={"pack": str(folder)},
        bound=bound,
    )
    payload = since_envelope(
        holdings=holdings, healed=healed, counts=counts, notes=notes, folder=folder
    )

    def _human() -> None:
        if baseline is not None:
            console.print(
                f"Compared to run {baseline.finished_at[:10]} "
                f"(witness {baseline.witness_id or 'none'})."
            )
        for note in notes:
            console.print(f"[yellow]{note}[/]")
        if not holdings and not healed:
            console.print(NOTHING_CHANGED)
        for row in holdings:
            console.print(f"[red]{row['kind']}[/] {row['itemKey']} {row['title'][:70]}")
        for row in healed:
            console.print(
                f"[green]healed[/] {row['itemKey']} {row['title'][:60]} "
                f"({row['was']} → {row['lane']})"
            )
        console.print(f"Pack: {folder}")
        if healed:
            console.print("Next: open Wanted, or paperful run for this scope.")

    cli_mod._emit_agent(payload, json_out=json_out, human=_human)
