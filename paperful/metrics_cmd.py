"""``paperful metrics`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .runreport import write_command_report


def run_metrics_refresh(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    stale_days: int | None,
    dry_run: bool,
    apply: bool,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import EXIT_PARTIAL, envelope
    from .metrics import apply_citation_notes, refresh
    from .snowball.command import _openalex_client

    json_out = cli_mod._agent_json(fmt)
    if dry_run and apply:
        console.print("[red]--dry-run and --apply conflict.[/]")
        raise typer.Exit(2)
    scoped = cli_mod._bind_scoped(
        collection=collection,
        library=library,
        profile=profile,
        run_config=run_config,
        config=config,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
    )
    cfg = scoped.cfg
    backend, loaded, items = cli_mod._connect_scope(
        scoped, quiet=json_out, json_out=json_out
    )
    offline = cli_mod._offline()
    oa = None if offline else _openalex_client(cfg)
    result = refresh(
        cfg,
        items,
        oa_client=oa,
        dry_run=dry_run,
        offline=offline,
        stale_days=stale_days,
        scope=loaded.label,
    )
    counts = dict(result["counts"])
    folder = result["folder"]
    rows = result["rows"]
    note_counts = {"notes_wrote": 0, "notes_skipped": 0, "notes_error": 0}
    if apply:
        note_counts = apply_citation_notes(
            backend,
            cfg,
            rows,
            run_id=str(result["pack"].get("created_at") or ""),
        )
        counts.update(note_counts)
    write_command_report(
        cfg,
        command="metrics refresh",
        scope=loaded.label,
        summary=counts,
        items=[
            {
                "itemKey": row.get("item_key"),
                "status": row.get("source"),
                "title": "",
                "reason": str(
                    row.get("cited_by_count")
                    if row.get("cited_by_count") is not None
                    else row.get("skip") or ""
                ),
            }
            for row in rows[:200]
        ],
        flags={"dry_run": dry_run, "offline": offline, "apply": apply},
        extra_paths={"pack": str(folder)},
        bound=scoped.bound,
    )
    failed = int(counts.get("error") or 0) + int(counts.get("notes_error") or 0)
    ok = int(counts.get("fetched") or 0) + int(counts.get("skipped_fresh") or 0)
    if apply:
        ok += int(counts.get("notes_wrote") or 0)
    exit_code = EXIT_PARTIAL if failed and ok else (1 if failed and not ok else 0)
    payload = envelope(
        command="metrics refresh",
        summary=counts,
        items=[
            {
                "item_key": row.get("item_key"),
                "doi": row.get("doi"),
                "cited_by_count": row.get("cited_by_count"),
                "source": row.get("source"),
            }
            for row in rows
        ],
        paths={
            "pack": str(folder),
            "cache": str(cfg.state_dir / "metrics" / "cache.json"),
        },
        flags={
            "dry_run": dry_run,
            "offline": offline,
            "apply": apply,
            "wrote": bool(result["pack"].get("wrote")),
        },
        exit_code=exit_code,
    )

    def _human() -> None:
        console.print(
            f"Scope: [bold]{loaded.label}[/] — {counts.get('scoped', 0)} items · "
            f"fetched {counts.get('fetched', 0)} · skipped {counts.get('skipped_fresh', 0)} · "
            f"unresolved {counts.get('unresolved', 0)} · error {counts.get('error', 0)}"
        )
        if dry_run:
            console.print("[dim]Dry-run: cache.json was not written.[/]")
        if apply:
            console.print(
                f"Notes: wrote {counts.get('notes_wrote', 0)} · "
                f"skipped {counts.get('notes_skipped', 0)} · "
                f"error {counts.get('notes_error', 0)}"
            )
        table = Table(show_header=True, header_style="bold")
        table.add_column("Key")
        table.add_column("Citations", justify="right")
        table.add_column("Source")
        for row in rows[:50]:
            cited = row.get("cited_by_count")
            table.add_row(
                str(row.get("item_key") or ""),
                "—" if cited is None else str(cited),
                str(row.get("source") or ""),
            )
        if rows:
            console.print(table)
        console.print(f"Pack: {folder}")

    cli_mod._emit_agent(payload, json_out=json_out, human=_human)


def run_metrics_show(
    console: Console,
    *,
    item_key: str,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .metrics import cache_path, show_cached

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    row = show_cached(cfg, item_key.strip())
    if row is None:
        payload = envelope(
            command="metrics show",
            summary={"found": 0},
            items=[],
            paths={"cache": str(cache_path(cfg))},
            flags={"item_key": item_key},
            exit_code=1,
        )

        def _missing() -> None:
            console.print(
                f"[red]No cached metrics for {item_key}.[/] Run metrics refresh."
            )

        cli_mod._emit_agent(payload, json_out=json_out, human=_missing)
        return
    payload = envelope(
        command="metrics show",
        summary={"found": 1, "cited_by_count": row.get("cited_by_count")},
        items=[row],
        paths={"cache": str(cache_path(cfg))},
        flags={"item_key": item_key},
    )

    def _human() -> None:
        cited = row.get("cited_by_count")
        console.print(
            f"{item_key} · citations {cited if cited is not None else '—'} · "
            f"source {row.get('source')} · fetched {row.get('fetched_at')}"
        )

    cli_mod._emit_agent(payload, json_out=json_out, human=_human)
