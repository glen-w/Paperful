"""``paperful run`` implementation (CLI parses flags only)."""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console

from .config import Config
from .pipeline import Pipeline, RunStats
from .routing import (
    filter_sources_for_item_types,
    filter_sources_for_year_scope,
    with_recover_lane,
    with_serpapi_lane,
)
from .run_hooks import (
    maybe_ezproxy_relogin,
    mid_run_ezproxy_hook,
    preflight_ezproxy_session,
    rag_auto_after_command,
    run_dry_run_table_and_payload,
)
from .store import Manifest, items_from_mirror
from .zot import items_without_stored_pdf, linked_url_only_count


def run_fetch(
    console: Console,
    cfg: Config,
    *,
    collection: list[str],
    library: bool | None,
    dry_run: bool,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    no_attach: bool | None,
    retry_failed: bool | None,
    try_all: bool | None,
    sources: str | None,
    preset: str | None,
    scihub: bool | None,
    relogin: bool,
    browser_agent: bool | None,
    upgrade_linked: bool | None,
    want_snapshot_upgrade: bool,
    strict_pdf_doi: bool | None,
    handoff: str | None,
    include_doi_tabs: bool,
    downloads_dir: Path | None,
    re_request: bool,
    json_out: bool,
    item_keys: list[str] | None = None,
) -> None:
    from . import cli as cli_mod

    if not collection and not library:
        cli_mod._refuse_missing_scope()
    cli_mod._require_manager(cfg)
    source_list = cli_mod._source_list(cfg, sources, scihub, preset)
    backend, offline_reason = cli_mod._open_library(cfg, quiet=json_out)
    mirror_only = backend is None
    if mirror_only:
        manager = cli_mod._manager_name(cfg)
        if not json_out:
            console.print(
                f"[yellow]{manager} is not reachable ({offline_reason}). "
                "Continuing from the local mirror. Nothing will be copied to the library.[/]"
            )
        catalog = items_from_mirror(cfg.out_dir, None if library else collection)
        scope = "library" if library else ", ".join(collection)
        keys = None
    else:
        keys, scope = cli_mod._scope_keys(backend, collection, library)
    types = cli_mod._resolve_types(item_type)
    # Drop sources that can never hit this -T / year scope (e.g. htmlpdf on
    # journals, Sci-Hub when --year-from is past its ~2021 coverage), including
    # under --try-all.
    source_list = filter_sources_for_item_types(
        source_list,
        types,
        academic_htmlpdf=cfg.htmlpdf_academic != "off",
    )
    source_list = filter_sources_for_year_scope(source_list, year_from)
    source_list = with_recover_lane(cfg, source_list, during_run=browser_agent)
    source_list = with_serpapi_lane(cfg, source_list)
    if not json_out:
        cli_mod._warn_if_scihub(source_list)
        cli_mod._warn_if_recover(source_list)

    manifest = Manifest(cfg.manifest_path)
    item_filter = year_from is not None or year_to is not None or types is not None
    # One library listing. Year and type filters, the linked-URL skip count,
    # and the PDF todo all come from that list.
    if not mirror_only:
        assert backend is not None
        with cli_mod._spinner("Loading items from library…", json_out=json_out):
            catalog = backend.items_in_scope(keys)
    if item_filter:
        scoped, scope = cli_mod._apply_item_filters(
            catalog,
            scope,
            year_from=year_from,
            year_to=year_to,
            item_types=types,
        )
        linked_skipped = 0 if upgrade_linked else linked_url_only_count(scoped)
    else:
        scoped = catalog
        linked_skipped = (
            0
            if upgrade_linked
            else linked_url_only_count(scoped, skip_empty_paths=keys is not None)
        )
    if item_keys:
        wanted = set(item_keys)
        scoped = [it for it in scoped if it.key in wanted]
    items = items_without_stored_pdf(
        scoped,
        upgrade_linked=upgrade_linked,
        upgrade_snapshot=want_snapshot_upgrade,
    )
    todo = [it for it in items if manifest.should_process(it.key, retry_failed)]
    skipped_manifest = len(items) - len(todo)
    if limit:
        todo = todo[:limit]
    linked_note = (
        f", {linked_skipped} linked URL only (skipped)" if linked_skipped else ""
    )
    if not json_out:
        console.print(
            f"Scope: [bold]{scope}[/] - {len(items)} items without PDF, {skipped_manifest} already handled, "
            f"{len(todo)} to process{linked_note}. Sources: {', '.join(source_list)}"
        )

    if dry_run:
        run_dry_run_table_and_payload(
            console,
            cfg,
            todo=todo,
            try_all=try_all,
            source_list=source_list,
            manifest=manifest,
            mirror_only=mirror_only,
            mirror_deferred=lambda: cli_mod._mirror_deferred(cfg),
            json_out=json_out,
            emit_agent=cli_mod._emit_agent,
        )
        raise typer.Exit(0)

    attacher = None
    if backend is not None and cfg.attach and not no_attach:
        attacher = backend
        if not backend.supports_write():
            console.print(
                "[yellow]Attach disabled: this library has no write support. PDFs still saved to disk.[/]"
            )
            attacher = None

    run_flags = cli_mod._run_flags(
        dry_run=False,
        no_attach=no_attach,
        retry_failed=retry_failed,
        try_all=try_all,
        upgrade_linked=upgrade_linked,
        scihub=scihub,
        no_browser_agent=True if browser_agent is False else None,
        browser_agent=True if browser_agent is True else None,
        preset=preset,
        sources=sources,
        year_from=year_from,
        year_to=year_to,
        item_types=",".join(sorted(types)) if types else None,
        strict_pdf_doi=strict_pdf_doi,
        ezproxy_relogin=relogin,
    )
    write_api = None if mirror_only else cli_mod._library_write_api(backend)

    if not todo:
        stats = RunStats(
            skipped_manifest=skipped_manifest, linked_url_skipped=linked_skipped
        )
        stats.scope = scope
        stats.sources_configured = list(source_list)
        stats.finished_at = stats.started_at
        cli_mod._finish_run(
            cfg,
            stats,
            scope=scope,
            flags=run_flags,
            write_api=write_api,
            json_out=json_out,
        )
        if mirror_only:
            cli_mod._mirror_deferred(cfg)
        return

    pipe = Pipeline(
        cfg,
        manifest,
        console,
        sources=source_list,
        attacher=attacher,
        try_all=True if try_all else None,
        strict_pdf_doi=bool(strict_pdf_doi),
    )
    pipe.on_ezproxy_down = mid_run_ezproxy_hook(console, cfg, pipe, enabled=relogin)
    preflight_ezproxy_session(console, cfg, pipe, source_list, enabled=relogin)
    interrupted = False
    with cli_mod._item_progress() as progress:
        task_id = progress.add_task("Fetching PDFs", total=len(todo))
        pipe.progress = lambda: progress.advance(task_id)
        pipe.live_progress = progress
        try:
            stats = pipe.run(todo)
        except KeyboardInterrupt:
            interrupted = True
            console.print(
                "\n[yellow]Interrupted - progress is in the manifest; rerun to resume.[/]"
            )
            stats = pipe.stats
            if not stats.finished_at:
                stats.finished_at = time.time()
        stats = pipe.stats
        pipe.live_progress = None
    # Fetch bar is done and pipe.run has closed the vault browser. Re-login
    # happens here, still before the report and before --handoff opens tabs.
    if not interrupted:
        try:
            maybe_ezproxy_relogin(console, cfg, pipe, todo, enabled=relogin)
        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Interrupted during EZProxy re-login - "
                "progress is in the manifest.[/]"
            )
            if not pipe.stats.finished_at:
                pipe.stats.finished_at = time.time()
        stats = pipe.stats
    stats.skipped_manifest = skipped_manifest
    stats.linked_url_skipped = linked_skipped
    stats.scope = scope
    cli_mod._finish_run(
        cfg,
        stats,
        scope=scope,
        flags=run_flags,
        write_api=write_api,
        json_out=json_out,
    )
    if backend is not None:
        cli_mod._flush(backend)
    if mirror_only:
        cli_mod._mirror_deferred(cfg)
    if not dry_run and not interrupted:
        rag_auto_after_command(console, cfg, stats.started_at)
    if handoff and not dry_run:
        # Tabs use the default browser. Release the vault profile first so
        # those tabs do not land in the EZProxy login window.
        if pipe.browser is not None:
            pipe.browser.close()
        cli_mod._run_session_handoff(
            cfg,
            backend,
            manifest,
            catalog,
            stats,
            handoff=handoff,
            include_doi_tabs=include_doi_tabs,
            downloads_dir=downloads_dir,
            re_request=re_request,
        )
