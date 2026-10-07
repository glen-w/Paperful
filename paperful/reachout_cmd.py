"""``paperful reachout`` implementation (CLI parses flags only)."""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

def run_reachout(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    non_oa_only: bool,
    lookup: bool,
    to: Path | None,
    handoff: str | None,
    request_rg: bool | None,
    re_request: bool,
    downloads_dir: Path | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli as cli_mod
    from .author_request import apply_request_rg_override
    from .handoff import (
        HINT_AUTHOR_REQUEST,
        list_missing_pdfs,
        open_tabs,
        parse_handoff,
        walk_missing,
    )
    from .run_hooks import gaps_downloads_dir
    from .reachout import build_reachout_rows, write_reachout_export
    from .runreport import write_command_report
    from .store import Manifest
    from .twenty import twenty_ready

    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    apply_request_rg_override(cfg, request_rg)
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
    try:
        mode = parse_handoff(handoff, default="list")
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if mode == "watch":
        console.print(
            "[red]reachout does not watch the inbox.[/] Use gaps --handoff watch."
        )
        raise typer.Exit(1)
    if lookup and not twenty_ready(cfg):
        console.print(
            "[yellow]--lookup ignored:[/] Twenty is off or TWENTY_API_KEY / base_url missing."
        )
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg, quiet=json_out)
    loaded = cli_mod._load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    started = time.time()
    manifest = Manifest(cfg.manifest_path)
    rows = build_reachout_rows(
        cfg,
        items,
        non_oa_only=non_oa_only,
        lookup=lookup and twenty_ready(cfg),
        re_request=re_request,
        manifest=manifest,
    )
    export_path = ""
    if to is not None:
        export_path = str(write_reachout_export(rows, to))
    with_email = sum(1 for r in rows if r.email)
    with_rg = sum(1 for r in rows if r.request_url)
    write_command_report(
        cfg,
        command="reachout",
        scope=scope,
        summary={
            "items": len(items),
            "rows": len(rows),
            "with_email": with_email,
            "with_rg": with_rg,
            "handoff": mode,
        },
        items=[{"itemKey": r.key, "status": r.email_source or "none"} for r in rows],
        started=started,
    )
    from .agent_json import envelope

    def _human() -> None:
        if export_path:
            console.print(f"Wrote {len(rows)} rows to {export_path}")
        table = Table(title=f"Reachout ({scope})")
        table.add_column("Key", style="dim")
        table.add_column("Author")
        table.add_column("Title")
        table.add_column("Email")
        table.add_column("Source")
        table.add_column("Request")
        table.add_column("Miss")
        for row in rows:
            table.add_row(
                row.key,
                (row.author or "-")[:24],
                (row.title or "-")[:40],
                row.email or "-",
                row.email_source or "-",
                (row.request_url or "-")[:36],
                row.miss_surface or "-",
            )
        console.print(table)
        console.print(
            f"{len(rows)} missing · {with_email} with email · {with_rg} ResearchGate. "
            "No fetch. Paperful does not send mail."
        )

    agent_payload = envelope(
        command="reachout",
        summary={
            "items": len(items),
            "rows": len(rows),
            "with_email": with_email,
            "with_rg": with_rg,
        },
        items=[r.as_dict() for r in rows],
        paths={"export": export_path} if export_path else None,
        flags={
            "non_oa_only": non_oa_only,
            "lookup": lookup,
            "handoff": mode,
        },
    )
    cli_mod._emit_agent(agent_payload, json_out=json_out, human=_human)
    if mode == "list":
        return
    rg_rows = [
        m
        for m in list_missing_pdfs(items, manifest, cfg=cfg, re_request=re_request)
        if m.hint == HINT_AUTHOR_REQUEST and m.request_url
    ]
    if non_oa_only:
        keep = {r.key for r in rows}
        rg_rows = [m for m in rg_rows if m.key in keep]
    if not rg_rows:
        console.print("[dim]No ResearchGate publication URLs to open.[/]")
        return
    if mode == "tabs":

        def _confirm(n: int) -> bool:
            answer = (
                typer.prompt(f"Open {n} ResearchGate tabs?", default="y")
                .strip()
                .lower()
            )
            return answer in {"y", "yes"}

        opened = open_tabs(
            rg_rows,
            include_doi_tabs=False,
            confirm=_confirm,
            scholar=False,
            cfg=cfg,
        )
        console.print(f"Opened {opened} ResearchGate tab(s). You click Request.")
        return
    if not backend.supports_write():
        console.print("[red]--handoff walk needs library write support.[/]")
        raise typer.Exit(1)
    dl = gaps_downloads_dir(cfg, downloads_dir)
    by_key = {it.key: it for it in items}
    result = walk_missing(
        cfg,
        backend,
        manifest,
        by_key,
        rg_rows,
        downloads_dir=dl,
        prompt=lambda msg: typer.prompt(msg, default=""),
        on_status=lambda msg: console.print(msg),
    )
    cli_mod._flush(backend)
    console.print(
        f"Walk attached {result.attached}, skipped {result.skipped}"
        + (" (quit early)" if result.quit_early else "")
    )

