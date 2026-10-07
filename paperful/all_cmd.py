"""``paperful all`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from .pack import PackError, close_pack, current_id, open_pack, pack_join_disabled
from .run_config import ResolvedRunConfig

def run_all(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    dry_run: bool,
    try_all: bool | None,
    retry_failed: bool | None,
    upgrade_linked: bool | None,
    no_attach: bool | None,
    strict_pdf_doi: bool | None,
    scihub: bool | None,
    browser_agent: bool | None,
    sources: str | None,
    preset: str | None,
    apply: bool | None,
    overwrite: bool | None,
    steps: str | None,
    skip: list[str],
    require_summarize: bool | None,
    serpapi_max: int | None,
    label: str | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli as cli_mod

    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(
        cfg,
        for_all=True,
        use_run_policy=True,
        use_apply=True,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        try_all=try_all,
        retry_failed=retry_failed,
        upgrade_linked=upgrade_linked,
        no_attach=no_attach,
        strict_pdf_doi=strict_pdf_doi,
        scihub=scihub,
        sources=sources,
        preset=preset,
        apply=apply,
        overwrite=overwrite,
        steps=steps,
        skip=skip,
        require_summarize=require_summarize,
    )
    if not bound.collections and not bound.library:
        cli_mod._refuse_missing_scope()
    opened = False
    if pack_join_disabled():
        if not json_out:
            console.print("[dim]PAPERFUL_PACK=off — reports are not grouped.[/]")
    elif current_id(cfg) is None:
        try:
            pack = open_pack(cfg, label=label or bound.name or "all")
        except PackError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
        opened = True
        if not json_out:
            console.print(f"[dim]Pack {pack['id']} opened.[/]")
    else:
        if not json_out:
            console.print(f"[dim]Pack {current_id(cfg)} joined.[/]")
    scope = _all_scope(bound, config)
    steps_done: list[dict[str, Any]] = []
    chain_exit = 0
    from .agent_json import suppress_stdout

    try:
        for step in bound.steps:
            if step == "summarize" and dry_run:
                if not json_out:
                    console.print(
                        "[yellow]Skipping summarize — dry-run does not write summary notes.[/]"
                    )
                steps_done.append({"step": step, "status": "skipped"})
                continue
            if step == "summarize" and not cfg.llm_enabled:
                if bound.require_summarize:
                    steps_done.append({"step": step, "status": "failed", "exit": 1})
                    if json_out:
                        chain_exit = 1
                        break
                    console.print(
                        "[red]summarize needs llm.enabled = true "
                        "(--require-summarize).[/]"
                    )
                    raise typer.Exit(1)
                if not json_out:
                    console.print("[yellow]Skipping summarize — llm.enabled is false.[/]")
                steps_done.append({"step": step, "status": "skipped"})
                continue
            if not json_out:
                console.print(f"\n[bold]all[/] · {step}")
            try:
                if json_out:
                    with suppress_stdout():
                        _dispatch_all_step(
                            step,
                            bound,
                            scope,
                            dry_run=dry_run,
                            browser_agent=browser_agent,
                            serpapi_max=serpapi_max
                            if isinstance(serpapi_max, int)
                            else None,
                            json_out=True,
                        )
                else:
                    _dispatch_all_step(
                        step,
                        bound,
                        scope,
                        dry_run=dry_run,
                        browser_agent=browser_agent,
                        serpapi_max=serpapi_max if isinstance(serpapi_max, int) else None,
                    )
                steps_done.append({"step": step, "status": "ok"})
            except typer.Exit as exc:
                code = int(exc.exit_code or 0)
                if code in (0, None):
                    steps_done.append({"step": step, "status": "ok"})
                    continue
                steps_done.append({"step": step, "status": "failed", "exit": code})
                chain_exit = code
                if json_out:
                    break
                raise
    finally:
        if opened:
            try:
                closed = close_pack(cfg)
            except PackError:
                closed = None
            if closed is not None and not json_out:
                console.print(f"[dim]Pack {closed['id']} closed.[/]")
    from .agent_json import envelope

    payload = envelope(
        command="all",
        summary={"steps": len(steps_done), "failed": chain_exit != 0},
        items=steps_done,
        flags={"dry_run": dry_run},
        exit_code=chain_exit,
    )
    cli_mod._emit_agent(payload, json_out=json_out, human=lambda: None)

def _call_step(fn, /, **kwargs: Any) -> None:
    """Run one verb. ``typer.Exit(0)`` (dry-run tables) does not stop the chain."""
    try:
        fn(**kwargs)
    except typer.Exit as exc:
        if exc.exit_code not in (0, None):
            raise

def _all_scope(bound: ResolvedRunConfig, config: Path | None) -> dict[str, Any]:
    return {
        "collection": list(bound.collections),
        "library": bound.library,
        "year_from": bound.year_from,
        "year_to": bound.year_to,
        "item_type": list(bound.types),
        "profile": None,
        "run_config": None,
        "config": config,
    }

def _dispatch_all_step(
    step: str,
    bound: ResolvedRunConfig,
    scope: dict[str, Any],
    *,
    dry_run: bool,
    browser_agent: bool | None = None,
    serpapi_max: int | None = None,
    json_out: bool = False,
) -> None:
    from . import cli as cli_mod
    fmt = "json" if json_out else "text"
    if step == "gaps":
        _call_step(
            cli_mod.gaps,
            **scope,
            as_json=False,
            list_missing=False,
            handoff=None,
            include_doi_tabs=False,
            downloads_dir=None,
            request_rg=None,
            re_request=False,
            to=None,
            fmt=fmt,
        )
        return
    if step == "run":
        _call_step(
            cli_mod.run,
            **scope,
            dry_run=dry_run,
            limit=bound.limit,
            no_attach=bound.no_attach,
            retry_failed=bound.retry_failed,
            try_all=bound.try_all,
            sources=bound.sources_csv,
            preset=bound.preset,
            scihub=bound.scihub,
            browser_agent=browser_agent,
            upgrade_linked=bound.upgrade_linked,
            strict_pdf_doi=bound.strict_pdf_doi,
            handoff=None,
            include_doi_tabs=False,
            downloads_dir=None,
            request_rg=None,
            re_request=False,
            ezproxy_relogin=None,
            serpapi_max=serpapi_max,
            fmt=fmt,
        )
        return
    if step == "lint":
        _call_step(cli_mod.lint, **scope, limit=bound.limit, as_json=False, strict=False, fmt=fmt)
        return
    if step == "fix-metadata":
        _call_step(
            cli_mod.fix_metadata,
            **scope,
            limit=bound.limit,
            apply=False if dry_run else bound.apply,
            overwrite=bound.overwrite,
            fmt=fmt,
        )
        return
    if step == "ocr":
        _call_step(
            cli_mod.ocr,
            **scope,
            item=[],
            limit=bound.limit,
            apply=False if dry_run else bound.apply,
            attach=False,
            fmt=fmt,
        )
        return
    if step == "summarize":
        _call_step(
            cli_mod.summarize,
            **scope,
            item=[],
            limit=bound.limit,
            apply=bound.apply,
            to=None,
            prompt=None,
            force=False,
            fmt=fmt,
        )
        return
    if step == "snapshot":
        _call_step(cli_mod.snapshot, **scope, limit=bound.limit, dry_run=dry_run, pdfs=None)
        return
    if step == "dedupe":
        _call_step(
            cli_mod.dedupe,
            **scope,
            limit=bound.limit,
            dry_run=dry_run,
            apply=False if dry_run else bound.apply,
            apply_medium=False,
            phase="all",
            as_json=False,
            fmt=fmt,
        )
        return
    if step == "restore":
        _call_step(
            cli_mod.restore,
            **scope,
            limit=bound.limit,
            dry_run=dry_run,
            apply=False if dry_run else bound.apply,
            fmt=fmt,
        )
        return
    if step == "synthesize":
        _call_step(
            cli_mod.synthesize,
            **scope,
            item=[],
            to=None,
            report_collection=None,
            prompt=None,
            dry_run=dry_run,
            force=False,
            limit=bound.limit,
            fmt=fmt,
        )
        return
    cli_mod.console.print(f"[red]Unknown step {step!r}.[/]")
    raise typer.Exit(1)

