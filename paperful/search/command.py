"""``paperful search`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from ..agent_json import envelope
from .store import SearchError, list_runs, load_run


def _call(action: Any) -> Any:
    from .. import cli_runtime as cli_mod

    try:
        return action()
    except SearchError as exc:
        cli_mod.console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    except ValueError as exc:
        cli_mod.console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


def run_search_cmd(
    console: Console,
    terms: list[str] | None,
    *,
    hosts: str,
    filetype: str,
    max_hits: int | None,
    probe: bool | None,
    fmt: str,
    config: Path | None,
    run_id: str | None = None,
    out_dir: Path | None = None,
    apply: bool = False,
    collection: str = "",
    list_runs_flag: bool = False,
    getter: Any = None,
    probe_getter: Any = None,
    backend: Any = None,
) -> None:
    from .. import cli_runtime as cli_mod
    from .apply import mark_exists
    from .run import run_search

    cfg = cli_mod._cfg(config)
    if list_runs_flag:
        run_search_list(console, config=config, fmt=fmt)
        return
    cleaned = [t for t in (terms or []) if str(t).strip()]
    if run_id and not cleaned:
        bundle = _call(lambda: load_run(cfg, run_id, dest=out_dir))
        mark_exists(cfg, bundle.get("candidates") or [], backend=backend)
        _recount(bundle)
        _maybe_apply(
            console,
            cfg,
            bundle,
            apply=apply,
            collection=collection,
            backend=backend,
            fmt=fmt,
        )
        _emit(console, bundle, fmt=fmt, command="search")
        return
    bundle = _call(
        lambda: run_search(
            cfg,
            cleaned,
            hosts=hosts,
            filetype=filetype,
            max_hits=max_hits,
            probe=probe,
            run_id=run_id,
            dest=out_dir,
            getter=getter,
            probe_getter=probe_getter,
        )
    )
    mark_exists(cfg, bundle.get("candidates") or [], backend=backend)
    _recount(bundle)
    _maybe_apply(
        console,
        cfg,
        bundle,
        apply=apply,
        collection=collection,
        backend=backend,
        fmt=fmt,
    )
    _emit(console, bundle, fmt=fmt, command="search")


def run_search_list(console: Console, *, config: Path | None, fmt: str) -> None:
    from .. import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    rows = list_runs(cfg)
    if fmt == "json":
        print(
            json.dumps(
                envelope(
                    command="search list",
                    summary={"runs": len(rows)},
                    items=rows,
                    exit_code=0,
                ),
                indent=2,
            )
        )
        return
    if not rows:
        console.print("No search runs in state/search/.")
        return
    table = Table(title="Web search runs")
    table.add_column("run")
    table.add_column("query")
    table.add_column("kept")
    for row in rows:
        table.add_row(str(row.get("run_id") or ""), str(row.get("query") or "")[:60], str(row.get("kept") or 0))
    console.print(table)


def _maybe_apply(
    console: Console,
    cfg: Any,
    bundle: dict[str, Any],
    *,
    apply: bool,
    collection: str,
    backend: Any,
    fmt: str,
) -> None:
    if not apply:
        return
    from ..library import LibraryError
    from .apply import apply_candidates

    if not (collection or "").strip():
        console.print("[red]--apply needs -C / --collection.[/]")
        raise typer.Exit(1)
    try:
        result = apply_candidates(
            cfg,
            bundle.get("candidates") or [],
            collection,
            backend=backend,
        )
    except LibraryError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    bundle["apply"] = result
    if fmt != "json":
        console.print(
            f"Created {result['created']} · failed {result['failed']} · "
            f"skipped {result['skipped']}"
        )


def _recount(bundle: dict[str, Any]) -> None:
    summary = dict(bundle.get("summary") or {})
    rows = list(bundle.get("candidates") or [])
    summary["kept"] = len(rows)
    summary["exists"] = sum(1 for row in rows if row.get("status") == "exists")
    summary["new"] = sum(1 for row in rows if row.get("status") == "new")
    bundle["summary"] = summary


def _emit(console: Console, bundle: dict[str, Any], *, fmt: str, command: str) -> None:
    summary = bundle.get("summary") or {}
    candidates = list(bundle.get("candidates") or [])
    if fmt == "json":
        extra = dict(summary)
        if bundle.get("apply"):
            extra["apply"] = bundle["apply"]
        print(
            json.dumps(
                envelope(
                    command=command,
                    summary={
                        "run_id": bundle.get("run_id"),
                        "query": (bundle.get("meta") or {}).get("query"),
                        "kept": summary.get("kept"),
                        "new": summary.get("new"),
                        "exists": summary.get("exists"),
                        "blocked": summary.get("blocked"),
                        "partial": bool(bundle.get("partial")),
                    },
                    items=candidates,
                    paths={"run": bundle.get("path")},
                    flags={"hosts": (bundle.get("meta") or {}).get("hosts") or []},
                    report=extra,
                    exit_code=0,
                    partial=bool(bundle.get("partial")),
                ),
                indent=2,
            )
        )
        return
    table = Table(title="Web search")
    table.add_column("status")
    table.add_column("score")
    table.add_column("host")
    table.add_column("kind")
    table.add_column("title")
    for row in candidates:
        table.add_row(
            str(row.get("status") or ""),
            str(row.get("score") or ""),
            str(row.get("host") or ""),
            str(row.get("kind") or ""),
            str(row.get("title") or "")[:80],
        )
    console.print(table)
    path = bundle.get("path") or ""
    if path:
        console.print(f"Wrote [bold]{path}[/]")
    if bundle.get("partial"):
        console.print("[yellow]SearXNG returned no hits (partial).[/]")
