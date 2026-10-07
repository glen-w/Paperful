"""``paperful recover`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console

def run_recover(
    console: Console,
    *,
    item: list[str],
    from_last_run: bool,
    from_last_run_mode: str,
    limit: int | None,
    dry_run: bool,
    no_attach: bool,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli as cli_mod

    from .browser_agent import recover_start_url
    from .config import RECOVER_DISCLAIMER
    from .llm import agent_model_uses_litellm, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_recover
    from .llm.validate import LlmConfigError
    from .pipeline import Pipeline
    from .runreport import (
        build_report,
        print_run_summary,
        recover_item_keys_from_report,
        write_run_report,
    )
    from .store import Manifest

    if not item and not from_last_run:
        console.print("[red]Give --item KEY or --from-last-run.[/]")
        raise typer.Exit(1)
    if item and from_last_run:
        console.print("[red]Use --item or --from-last-run, not both.[/]")
        raise typer.Exit(1)
    if cli_mod.sys.version_info < (3, 11):
        console.print(
            "[red]recover requires Python 3.11+ for browser-use.[/] "
            f"This interpreter is {cli_mod.sys.version_info.major}."
            f"{cli_mod.sys.version_info.minor}."
        )
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    cli_mod._require_manager(cfg)
    try:
        validate_llm_for_recover(cfg)
    except LlmConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    if not json_out:
        console.print(f"[orange3]{RECOVER_DISCLAIMER}[/]")
        remote = llm_egress_is_remote(cfg)
        fb = cfg.browser_agent_fallback_model.strip()
        if fb and agent_model_uses_litellm(cfg, fb):
            remote = True
        if remote:
            console.print(
                "[orange3]Remote LLM provider — page text may leave this machine.[/]"
            )
    backend = cli_mod._connect(cfg, quiet=json_out)
    manifest = Manifest(cfg.manifest_path)
    item_keys = list(item)
    scope = f"items:{','.join(item_keys)}"
    if from_last_run:
        last = cli_mod._load_last_run(cfg)
        if not last or last.get("schema") != "paperful.run_report.v1":
            console.print(
                "[red]No auditable last run at state/last-run.json — run paperful run first.[/]"
            )
            raise typer.Exit(1)
        item_keys = recover_item_keys_from_report(last, mode=from_last_run_mode)
        if limit is not None and limit > 0:
            item_keys = item_keys[:limit]
        scope = f"from-last-run:{from_last_run_mode}"
        if not item_keys:
            console.print("[yellow]No items matched the last-run filter.[/]")
            raise typer.Exit(0)
    elif limit is not None and limit > 0:
        item_keys = item_keys[:limit]
    todo: list = []
    preview: list[dict[str, Any]] = []
    for key in item_keys:
        it = backend.get_item(key)
        if it is None:
            console.print(f"[red]Unknown item key {key}[/]")
            raise typer.Exit(1)
        if it.has_pdf and not dry_run:
            if not json_out:
                console.print(f"[dim]Skipping {key} — already has PDF[/]")
            preview.append({"itemKey": key, "status": "skip", "reason": "has_pdf"})
            continue
        url = recover_start_url(it)
        if not url:
            console.print(f"[red]{key}: no DOI or URL[/]")
            raise typer.Exit(1)
        if dry_run:
            if not json_out:
                console.print(f"[bold]{key}[/] would recover from {url}")
            preview.append({"itemKey": key, "status": "would", "url": url})
            continue
        todo.append(it)
    if dry_run or not todo:
        from .agent_json import envelope

        payload = envelope(
            command="recover",
            summary={
                "count": len(preview),
                "would": sum(1 for r in preview if r.get("status") == "would"),
            },
            items=preview,
            flags={"dry_run": dry_run, "no_attach": no_attach},
        )
        cli_mod._emit_agent(payload, json_out=json_out, human=lambda: None)
        raise typer.Exit(0)
    attacher = None if no_attach else backend
    if attacher and not backend.supports_write():
        cli_mod._exit_env("Write support required to attach.", cfg)
    with cli_mod._item_progress(json_out=json_out) as progress:
        task_id = progress.add_task("Recovering PDFs", total=len(todo))
        pipe = Pipeline(
            cfg,
            manifest,
            console,
            sources=["browser_agent"],
            attacher=attacher,
            progress=lambda: progress.advance(task_id),
            try_all=True,
            use_browser=False,
        )
        try:
            stats = pipe.run(todo)
        except KeyboardInterrupt:
            stats = pipe.stats
    report = build_report(
        stats,
        cfg,
        command="recover",
        scope=scope,
        flags=cli_mod._run_flags(no_attach=no_attach, from_last_run=from_last_run),
    )
    path = write_run_report(cfg, report)
    from .agent_json import batch_exit, envelope

    summary = report.get("summary") or {}
    code = batch_exit(
        ok=int(summary.get("attached") or 0),
        failed=int(summary.get("attach_failed") or 0),
    )
    payload = envelope(
        command="recover",
        summary=summary if isinstance(summary, dict) else {},
        items=list(report.get("items") or []),
        paths={"report": str(path) if path else ""},
        flags=cli_mod._run_flags(no_attach=no_attach),
        report=report,
        exit_code=code,
    )
    cli_mod._emit_agent(
        payload,
        json_out=json_out,
        human=lambda: print_run_summary(console, report, path),
    )
    cli_mod._flush(backend)

