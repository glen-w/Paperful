"""``paperful lint`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .runreport import write_command_report
from .store import Manifest

def run_lint(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    as_json: bool,
    strict: bool,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .lint import Finding, lint_items
    from .pipeline import make_client
    from .zot import Item

    json_out, as_json = cli_mod._agent_wins(fmt, as_json)
    quiet = as_json or json_out
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
        scoped, quiet=quiet, json_out=quiet, require_manager=True
    )
    manifest = Manifest(cfg.manifest_path)
    partial: list[Finding] = []
    done = 0
    interrupted = False
    scope = loaded.label
    if not quiet:
        console.print(f"Scope: [bold]{scope}[/] — linting {len(items)} items")
    with cli_mod._item_progress(json_out=quiet) as progress:
        lint_id = progress.add_task("Linting", total=len(items))

        def _describe(current: str = "") -> str:
            n = len(partial)
            text = f"Linting [dim]· {n} finding{'' if n == 1 else 's'}"
            if current:
                text += f" · {escape(current)}"
            return text + "[/]"

        def _lint_start(item: Item) -> None:
            progress.update(lint_id, description=_describe(item.label[:48]))

        def _lint_done(item: Item, found: list[Finding]) -> None:
            nonlocal done
            done += 1
            partial.extend(found)
            progress.update(lint_id, advance=1, description=_describe())

        started = time.time()
        try:
            findings = lint_items(
                make_client(cfg),
                cfg,
                items,
                backend=backend,
                manifest=manifest,
                on_start=_lint_start,
                on_item=_lint_done,
            )
            partial[:] = findings
            progress.update(lint_id, completed=len(items), description=_describe())
        except KeyboardInterrupt:
            interrupted = True
            findings = partial
    if interrupted:
        progress.console.print(
            f"\n[yellow]Interrupted after {done}/{len(items)} items.[/] "
            "Findings so far:"
        )
    by_code: dict[str, int] = {}
    for finding in findings:
        by_code[finding.code] = by_code.get(finding.code, 0) + 1
    write_command_report(
        cfg,
        command="lint",
        scope=scope,
        summary={"findings": len(findings), "findings_by_code": by_code},
        items=[
            {
                "itemKey": finding.itemKey,
                "title": finding.title,
                "status": finding.code,
                "reason": finding.detail,
            }
            for finding in findings
        ],
        flags={"strict": strict, "interrupted": interrupted},
        started=started,
    )
    from .agent_json import envelope

    payload = envelope(
        command="lint",
        summary={"findings": len(findings), "findings_by_code": by_code},
        items=[
            {
                "itemKey": finding.itemKey,
                "title": finding.title,
                "status": finding.code,
                "reason": finding.detail,
            }
            for finding in findings
        ],
        flags={"strict": strict, "interrupted": interrupted},
        exit_code=130 if interrupted else (1 if strict and findings else 0),
    )

    def _human_lint() -> None:
        if not findings:
            console.print("[green]No findings.[/]")
            return
        table = Table(title=f"{len(findings)} findings")
        table.add_column("Code")
        table.add_column("Key", style="dim")
        table.add_column("Title")
        table.add_column("Detail")
        for f in findings:
            table.add_row(f.code, f.itemKey, f.title[:50], f.detail[:80])
        console.print(table)

    if json_out:
        cli_mod._emit_agent(payload, json_out=True, human=_human_lint)
        return
    if as_json:
        console.print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        _human_lint()
    if interrupted:
        raise typer.Exit(130)
    if strict and findings:
        raise typer.Exit(1)
