"""``paperful gaps`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .config import Config
from .dedupe import summarize_gaps
from .handoff import (
    list_missing_pdfs,
    open_tabs,
    walk_missing,
    write_missing_export,
)
from .library import LibraryBackend
from .run_hooks import flush_backend, gaps_downloads_dir, rag_auto_after_command
from .runreport import write_command_report
from .store import Manifest


def run_gaps(
    console: Console,
    cfg: Config,
    backend: LibraryBackend,
    items: list,
    scope: str,
    *,
    list_missing: bool,
    mode: str,
    json_out: bool,
    as_json: bool,
    to: Path | None,
    include_doi_tabs: bool,
    downloads_dir: Path | None,
    re_request: bool,
    emit_agent: Callable[..., None],
    inbox_handoff: Callable[..., None],
) -> None:
    started = time.time()
    counts = summarize_gaps(items)
    payload = {
        "scope": scope,
        "items": counts.items,
        "no_stored_pdf": counts.no_stored_pdf,
        "linked_url_only": counts.linked_url_only,
        "missing_doi": counts.missing_doi,
        "snapshot_only": counts.snapshot_only,
    }
    rows = []
    for it in items:
        codes: list[str] = []
        if not it.has_pdf:
            codes.append("no_stored_pdf")
        if it.has_linked_url and not it.has_pdf:
            codes.append("linked_url_only")
        if not it.doi:
            codes.append("missing_doi")
        if it.pdf_tier == "snapshot":
            codes.append("snapshot_only")
        if codes:
            rows.append(
                {"itemKey": it.key, "title": it.title, "status": ",".join(codes)}
            )
    write_command_report(
        cfg,
        command="gaps",
        scope=scope,
        summary={
            "items": counts.items,
            "no_stored_pdf": counts.no_stored_pdf,
            "linked_url_only": counts.linked_url_only,
            "missing_doi": counts.missing_doi,
            "snapshot_only": counts.snapshot_only,
            "handoff": mode if list_missing else "",
        },
        items=rows,
        started=started,
    )
    from .agent_json import envelope

    def _human_gaps_counts() -> None:
        console.print(f"Scope: [bold]{scope}[/]")
        table = Table(title="Gaps")
        table.add_column("Count", justify="right")
        table.add_column("Gap")
        table.add_column("Next")
        table.add_row(str(counts.items), "items in scope", "")
        table.add_row(
            str(counts.no_stored_pdf),
            "no stored PDF",
            "paperful run (or --upgrade-linked)",
        )
        table.add_row(
            str(counts.linked_url_only),
            "linked PDF URL only",
            "paperful run --upgrade-linked",
        )
        table.add_row(str(counts.missing_doi), "missing DOI", "paperful lint")
        table.add_row(
            str(counts.snapshot_only),
            "HTML snapshot only",
            "paperful run --upgrade-snapshot",
        )
        console.print(table)

    agent_payload = envelope(
        command="gaps",
        summary={
            "items": counts.items,
            "no_stored_pdf": counts.no_stored_pdf,
            "linked_url_only": counts.linked_url_only,
            "missing_doi": counts.missing_doi,
            "snapshot_only": counts.snapshot_only,
        },
        items=rows,
        flags={"list_missing": list_missing, "handoff": mode if list_missing else ""},
    )
    if json_out and not list_missing:
        emit_agent(agent_payload, json_out=True, human=_human_gaps_counts)
        return
    if as_json and not list_missing:
        console.print(
            json.dumps(payload, indent=2), soft_wrap=True, highlight=False, markup=False
        )
        return
    if not as_json and not json_out:
        _human_gaps_counts()

    if not list_missing:
        return

    manifest = Manifest(cfg.manifest_path)
    missing = list_missing_pdfs(items, manifest, cfg=cfg, re_request=re_request)
    if to is not None:
        path = write_missing_export(missing, to)
        console.print(f"Wrote {len(missing)} rows to {path}")
    if as_json:
        console.print(
            json.dumps(
                {
                    **payload,
                    "missing": [
                        {
                            "itemKey": r.key,
                            "title": r.title,
                            "doi": r.doi,
                            "url": r.url,
                            "hint": r.hint,
                            "miss_surface": r.miss_surface,
                            "miss_plain": r.miss_plain,
                            "miss_detail": r.miss_detail,
                            "oa_status": r.oa_status,
                            "license": r.license,
                            "version": r.version,
                            "scholar_url": r.scholar_url,
                            "request_url": r.request_url,
                        }
                        for r in missing
                    ],
                },
                indent=2,
            ),
            soft_wrap=True,
            highlight=False,
            markup=False,
        )
        return
    if json_out:
        agent_payload["items"] = [
            {
                "itemKey": r.key,
                "title": r.title,
                "doi": r.doi,
                "url": r.url,
                "hint": r.hint,
                "miss_surface": r.miss_surface,
                "scholar_url": r.scholar_url,
                "request_url": r.request_url,
            }
            for r in missing
        ]
        agent_payload["summary"]["missing_pdfs"] = len(missing)
        emit_agent(agent_payload, json_out=True, human=lambda: None)
        return
    t = Table(title=f"{len(missing)} missing PDFs")
    t.add_column("Key", style="dim")
    t.add_column("Title")
    t.add_column("DOI")
    t.add_column("URL")
    t.add_column("Scholar")
    t.add_column("Request")
    t.add_column("Hint")
    t.add_column("Miss")
    t.add_column("OA")
    for row in missing:
        t.add_row(
            row.key,
            row.title[:50],
            row.doi or "-",
            (row.url or "-")[:40],
            (row.scholar_url or "-")[:40],
            (row.request_url or "-")[:40],
            row.hint,
            row.miss_plain or row.miss_surface or "-",
            row.oa_status or "-",
        )
    console.print(t)

    if mode == "list":
        return
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
        console.print(f"Opened {opened} tab(s) in your browser.")
        if mode == "tabs" and not (
            cfg.inbox_watch_after_handoff and cfg.inbox_path is not None
        ):
            return
        if not backend.supports_write():
            console.print("[red]--handoff watch needs library write support.[/]")
            raise typer.Exit(1)
        inbox_handoff(
            cfg,
            backend,
            manifest,
            items,
            missing,
            scope=scope,
            once=False,
        )
        return

    if not backend.supports_write():
        console.print("[red]--handoff walk needs library write support.[/]")
        raise typer.Exit(1)
    dl = gaps_downloads_dir(cfg, downloads_dir)
    by_key = {it.key: it for it in items}
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
