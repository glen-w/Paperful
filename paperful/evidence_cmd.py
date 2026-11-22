"""``paperful evidence`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .runreport import write_command_report
from .store import Manifest


def run_evidence(
    console: Console,
    *,
    item: list[str],
    collection: list[str],
    library: bool | None,
    apply: bool,
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

    from .agent_json import envelope
    from .dedupe import scope_slug
    from .evidence import collect_items, pack_payload, write_pack

    if apply:
        console.print("[red]evidence --apply is not in this stage. The pack stays on disk.[/]")
        raise typer.Exit(1)
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
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg, quiet=json_out)
    manifest = Manifest(cfg.manifest_path)
    loaded = cli_mod._load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        item_keys=item,
        pdfs_only=False,
    )
    items, scope = loaded.items, loaded.label
    if limit:
        items = items[:limit]
    batch = collect_items(cfg, items, manifest, backend)
    eid = scope_slug(scope or "library")
    payload = pack_payload(evidence_id=eid, scope=scope, batch=batch)
    folder = write_pack(cfg, payload)
    write_command_report(
        cfg,
        command="evidence",
        scope=scope,
        summary=payload["counts"],
        items=[{"itemKey": r.key, "status": "ok"} for r in batch.rows][:200],
        flags={"dry_run": True},
        extra_paths={"pack": str(folder)},
        bound=bound,
    )
    agent = envelope(
        command="evidence",
        summary=payload["counts"],
        items=[{"itemKey": r.key, "design": r.design} for r in batch.rows],
        paths={"pack": str(folder)},
        flags={"dry_run": True},
    )

    def _human() -> None:
        table = Table(title="evidence")
        table.add_column("Key")
        table.add_column("Design")
        table.add_column("n")
        table.add_column("Finding")
        for row in batch.rows[:40]:
            table.add_row(
                row.key,
                (row.design or "")[:24],
                (row.n or "")[:24],
                (row.finding or "")[:48],
            )
        console.print(table)
        counts = payload["counts"]
        console.print(
            f"Rows {counts['rows']} · findings {counts['findings']} · "
            f"skips {counts['skips']}"
        )
        console.print(f"Pack: {folder}")

    cli_mod._emit_agent(agent, json_out=json_out, human=_human)
