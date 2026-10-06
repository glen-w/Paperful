"""Run-time CLI hooks: EZProxy session recovery, handoff, dry-run rows."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .config import Config
from .library import LibraryBackend
from .pipeline import Pipeline, RunStats, session_expired_items
from .progress import item_progress, pause_live, tracker
from .routing import sources_for_item
from .runreport import write_command_report
from .store import Manifest

def stdin_is_tty() -> bool:
    from . import cli as cli_mod

    return cli_mod._stdin_is_tty()


def confirm_session_login(console: Console) -> None:
    console.print("Complete login or CAPTCHA in the browser window, then press Enter.")
    try:
        input()
    except EOFError:
        pass


def gaps_downloads_dir(cfg: Config, override: Path | None) -> Path:
    if override is not None:
        return override.expanduser()
    raw = (cfg.gaps_downloads_dir or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "Downloads"


def flush_backend(console: Console, backend: LibraryBackend) -> None:
    behind = getattr(backend, "unrefreshed", None)
    err = Console(stderr=True, highlight=False)
    if behind:
        err.print(
            f"[yellow]{len(behind)} item(s) changed in the library but not yet in "
            f"the mirror. paperful snapshot brings them in.[/]"
        )
    fn = getattr(backend, "flush_writes", None)
    if not callable(fn):
        return
    path = fn()
    if path is None:
        return
    err.print(f"[green]EndNote import bundle[/] {path}")
    err.print(
        "[dim]In EndNote: File → Import → File → paperful.xml "
        "(import option: EndNote Generated XML).[/]"
    )


def rag_auto_after_command(console: Console, cfg: Config, since: float, keys: Any = ()) -> None:
    if not (cfg.rag_enabled and cfg.rag_auto_ingest):
        return
    from .rag.auto import auto_ingest

    try:
        with item_progress(console) as progress:
            batch = auto_ingest(
                cfg,
                since=since,
                keys=keys,
                track=tracker(progress, "Indexing new PDFs"),
                ocr_track=tracker(progress, "Running OCR"),
            )
    except KeyboardInterrupt:
        console.print(
            "[yellow]Indexing interrupted. `paperful rag ingest` resumes it.[/]"
        )
        return
    except Exception as exc:
        console.print(f"Index not updated: {exc}", markup=False, style="yellow")
        console.print("[yellow]Run `paperful rag ingest` to catch up.[/]")
        return
    if batch is None:
        return
    done = batch.count("pdf", "ocr", "abstract")
    if done:
        console.print(
            f"[dim]Index: {done} item(s) updated, {batch.chunks} passages.[/]"
        )


def ezproxy_headed_login_and_probe(
    console: Console, cfg: Config, pipe: Pipeline
) -> bool:
    from . import session as sess
    from .sources import ezproxy as ez

    console.print("Opening a browser to refresh the EZProxy session.")
    pipe.release_browser()
    try:
        sess.login_headed(
            cfg,
            "ezproxy",
            confirm=lambda: confirm_session_login(console),
            on_note=lambda msg: console.print(f"[dim]{msg}[/]"),
        )
    except sess.SessionError as exc:
        console.print(f"[red]{exc}[/]")
        console.print("Run [bold]paperful session login ezproxy[/] and retry.")
        return False
    pipe.refresh_session()
    ok, detail = ez.session_ok(pipe.ctx)
    if not ok:
        console.print(
            f"[yellow]EZProxy session still not ready ({detail}).[/] "
            "Run [bold]paperful session login ezproxy[/] and retry."
        )
        if pipe.browser is not None:
            pipe.browser.close()
        return False
    console.print("[green]EZProxy session ready.[/]")
    return True


def ensure_ezproxy_session(
    console: Console,
    cfg: Config,
    pipe: Pipeline,
    *,
    enabled: bool,
    prompt: str,
) -> bool:
    if not enabled or not stdin_is_tty():
        return False
    with pause_live(getattr(pipe, "live_progress", None)):
        try:
            answer = console.input(prompt).strip().lower()
        except EOFError:
            return False
        if answer not in {"", "y", "yes"}:
            console.print("[yellow]Skipping EZProxy re-login.[/]")
            return False
        return ezproxy_headed_login_and_probe(console, cfg, pipe)


def preflight_ezproxy_session(
    console: Console,
    cfg: Config,
    pipe: Pipeline,
    source_list: list[str],
    *,
    enabled: bool,
) -> None:
    if "ezproxy" not in source_list or not cfg.ezproxy_base:
        return
    from .sources import ezproxy as ez

    ok, detail = ez.session_ok(pipe.ctx)
    if ok:
        return
    console.print(f"[yellow]EZProxy session not ready ({detail}).[/]")
    if ensure_ezproxy_session(
        console,
        cfg,
        pipe,
        enabled=enabled,
        prompt="EZProxy session not ready — log in now? [Y/n] ",
    ):
        return
    pipe._ezproxy_down = True
    console.print(
        "[yellow]Continuing without EZProxy wraps for this pass.[/] "
        "Remaining proxy attempts will be skipped."
    )


def mid_run_ezproxy_hook(
    console: Console, cfg: Config, pipe: Pipeline, *, enabled: bool
) -> Callable[[], bool] | None:
    if not enabled:
        return None

    def bound() -> bool:
        return ensure_ezproxy_session(
            console,
            cfg,
            pipe,
            enabled=enabled,
            prompt="EZProxy session expired mid-run — re-login and continue? [Y/n] ",
        )

    return bound


def maybe_ezproxy_relogin(
    console: Console,
    cfg: Config,
    pipe: Pipeline,
    todo: list,
    *,
    enabled: bool,
) -> None:
    if not enabled or not stdin_is_tty():
        return
    retry = session_expired_items(pipe.manifest, todo)
    if not retry:
        return
    n = len(retry)
    if not ensure_ezproxy_session(
        console,
        cfg,
        pipe,
        enabled=True,
        prompt=f"Re-login and retry {n} EZProxy item(s)? [Y/n] ",
    ):
        return
    console.print(f"Retrying {n} item(s).")
    saved_sources = list(pipe.sources)
    saved_progress = pipe.progress
    pipe.sources = ["ezproxy"]
    pipe.stats.drop_outcomes({it.key for it in retry})
    try:
        with item_progress(console) as progress:
            task_id = progress.add_task("EZProxy retry", total=n)
            pipe.progress = lambda: progress.advance(task_id)
            pipe.run(retry)
    finally:
        pipe.sources = saved_sources
        pipe.progress = saved_progress
        if pipe.browser is not None:
            pipe.browser.close()


def inbox_handoff_session(
    console: Console,
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    items: list,
    missing: list,
    *,
    scope: str,
    once: bool,
    idle_seconds: float | None = None,
    use_fifo: bool = True,
) -> None:
    from .inbox import (
        ensure_inbox_dirs,
        events_as_report_items,
        fifo_from_missing,
        process_candidates,
        summary_from_stats,
    )

    started = time.time()
    try:
        root = ensure_inbox_dirs(cfg)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(
        f"[bold]Inbox[/] watching {root} "
        f"(DOI match"
        + ("; FIFO for openable misses" if use_fifo else "")
        + "; Ctrl+C to stop)"
    )
    fifo = fifo_from_missing(missing) if use_fifo else None
    stats = process_candidates(
        cfg,
        backend,
        manifest,
        list(items),
        fifo_queue=fifo,
        once=once,
        idle_seconds=idle_seconds,
        on_status=lambda msg: console.print(msg),
    )
    flush_backend(console, backend)
    rag_auto_after_command(console, cfg, started)
    path = write_command_report(
        cfg,
        command="inbox",
        scope=scope,
        summary=summary_from_stats(stats),
        items=events_as_report_items(stats.events),
        flags={"once": once, "fifo": use_fifo},
        started=started,
        extra_paths={"inbox_dir": str(root)},
    )
    console.print(
        f"Inbox attached {stats.attached}, unmatched {stats.unmatched}, "
        f"errors {stats.errors}, skipped {stats.skipped}"
        + (f" ({stats.quit_reason})" if stats.quit_reason else "")
    )
    if path is not None:
        console.print(f"Inbox report: {path}")


def run_session_handoff(
    console: Console,
    cfg: Config,
    backend: LibraryBackend | None,
    manifest: Manifest,
    catalog: list,
    stats: RunStats,
    *,
    handoff: str,
    include_doi_tabs: bool,
    downloads_dir: Path | None,
    re_request: bool = False,
) -> None:
    from .handoff import (
        missing_from_run_outcomes,
        open_tabs,
        parse_handoff,
        walk_missing,
    )

    try:
        mode = parse_handoff(handoff)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return
    if mode == "list":
        return
    outcomes = [
        {
            "itemKey": o.itemKey,
            "status": o.status,
            "reason": o.reason,
            "attempts": list(o.attempts or []),
        }
        for o in stats.items
    ]
    by_key = {it.key: it for it in catalog}
    missing = missing_from_run_outcomes(
        by_key, outcomes, cfg=cfg, re_request=re_request
    )
    if not missing:
        console.print("[dim]No openable soft-blocked PDFs to hand off.[/]")
        return
    console.print(f"[bold]Handoff[/] ({mode}): {len(missing)} openable miss(es)")
    if mode in {"tabs", "watch"}:

        def _confirm(n: int) -> bool:
            answer = (
                typer.prompt(f"Open {n} tabs in your browser?", default="y")
                .strip()
                .lower()
            )
            return answer in {"y", "yes"}

        opened = open_tabs(
            missing,
            include_doi_tabs=include_doi_tabs,
            confirm=_confirm,
            scholar=cfg.handoff_scholar,
            cfg=cfg,
        )
        console.print(f"Opened {opened} tab(s).")
        enter_watch = mode == "watch" or (
            mode == "tabs"
            and cfg.inbox_watch_after_handoff
            and cfg.inbox_path is not None
        )
        if not enter_watch:
            return
        if backend is None or not backend.supports_write():
            console.print(
                "[yellow]--handoff watch needs a writable library; skipped.[/]"
            )
            return
        inbox_handoff_session(
            console,
            cfg,
            backend,
            manifest,
            catalog,
            missing,
            scope="run handoff",
            once=False,
        )
        return
    if backend is None or not backend.supports_write():
        console.print("[yellow]--handoff walk needs a writable library; skipped.[/]")
        return
    dl = gaps_downloads_dir(cfg, downloads_dir)
    walk_started = time.time()
    result = walk_missing(
        cfg,
        backend,
        manifest,
        by_key,
        missing,
        downloads_dir=dl,
        prompt=lambda msg: typer.prompt(msg, default=""),
        on_status=lambda msg: console.print(msg),
    )
    flush_backend(console, backend)
    rag_auto_after_command(console, cfg, walk_started)
    console.print(
        f"Walk attached {result.attached}, skipped {result.skipped}"
        + (" (quit early)" if result.quit_early else "")
    )


def run_dry_run_table_and_payload(
    console: Console,
    cfg: Config,
    *,
    todo: list,
    try_all: bool | None,
    source_list: list[str],
    manifest: Manifest,
    mirror_only: bool,
    mirror_deferred: Callable[[], None],
    json_out: bool,
    emit_agent: Callable[..., None],
) -> None:
    from .agent_json import envelope
    from .miss_surface import honesty_row_for_item

    table = Table(title="Dry run", expand=True)
    table.add_column("Key", style="dim", no_wrap=True)
    table.add_column("Type", no_wrap=True, max_width=14)
    table.add_column("Item", no_wrap=True, overflow="ellipsis", ratio=3)
    table.add_column("DOI (source)", no_wrap=True, overflow="ellipsis", ratio=2)
    table.add_column("Would-hit", no_wrap=True, overflow="ellipsis", ratio=2)
    table.add_column("Miss", no_wrap=True, overflow="ellipsis", ratio=2)
    table.add_column("URL", no_wrap=True, overflow="ellipsis", ratio=1)
    table.add_column("Collections", no_wrap=True, overflow="ellipsis", ratio=1)
    dry_items: list[dict[str, Any]] = []
    for it in todo:
        if try_all or not cfg.source_routing:
            lanes = source_list
        else:
            lanes = sources_for_item(it, cfg, source_list)
        would = ", ".join(lanes) if lanes else "-"
        rec = manifest.get(it.key)
        honesty = honesty_row_for_item(cfg, it, rec)
        miss = honesty.get("miss_plain") or honesty.get("miss_surface") or "-"
        dry_items.append(
            {
                "itemKey": it.key,
                "title": it.label,
                "would_hit": would,
                "miss_surface": honesty.get("miss_surface") or "",
                "miss_plain": honesty.get("miss_plain") or "",
            }
        )
        table.add_row(
            it.key,
            it.item_type,
            it.label,
            (
                f"{it.doi} ({it.doi_source})"
                if it.doi
                else ("arXiv:" + it.arxiv_id if it.arxiv_id else "-")
            ),
            would,
            miss,
            (it.url or "-")[:60],
            "; ".join(it.collection_paths),
        )
    payload = envelope(
        command="run",
        summary={"todo": len(todo), "dry_run": True},
        items=dry_items,
        flags={"dry_run": True},
    )

    def _human_dry() -> None:
        console.print(table)
        if mirror_only:
            mirror_deferred()

    emit_agent(payload, json_out=json_out, human=_human_dry)
