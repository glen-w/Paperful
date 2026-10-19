"""``paperful collections`` implementation (CLI parses flags only)."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import Config
from .library import LibraryBackend


def _print_collections_table(
    console: Console, cfg: Config, backend: LibraryBackend
) -> None:
    from . import cli_runtime as cli_mod

    with cli_mod._spinner("Counting collections…"):
        cols = backend.collections()
        counts = backend.collection_counts()
    table = Table(title=f"{cfg.manager} collections (counts include subcollections)")
    table.add_column("Path")
    table.add_column("Items", justify="right")
    table.add_column("No PDF", justify="right")
    table.add_column("Key", style="dim")
    for c in sorted(cols.values(), key=lambda c: c.path.lower()):
        n, missing = counts.get(c.key, (0, 0))
        depth = c.path.count("/")
        table.add_row(("  " * depth) + c.name, str(n), str(missing), c.key)
    console.print(table)


def run_collections_show(
    console: Console,
    *,
    config: Path | None,
) -> None:
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg)
    _print_collections_table(console, cfg, backend)


def run_collections_add(
    console: Console,
    *,
    collection: list[str],
    keys_file: Path,
    apply: bool,
    dry_run: bool,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod

    from .agent_json import envelope
    from .agent_ops import collections_add_exit
    from .collections_add import apply_adds, classify_rows, keys_from_file, write_summary

    if apply and dry_run:
        console.print("[red]Pass either --dry-run or --apply, not both.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(cfg, profile=profile, run_config=run_config, collection=collection)
    collection, _library, _yf, _yt, _types = cli_mod._take_scope(bound)
    if not collection:
        cli_mod._refuse_missing_scope()
    keys = keys_from_file(keys_file)
    if not keys:
        console.print("No keys to add.")
        raise typer.Exit(0)
    backend = cli_mod._connect(cfg, quiet=json_out)
    try:
        target = backend.resolve_collection(collection[0])
    except LookupError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    batch = classify_rows(
        keys,
        backend,
        collection_key=target.key,
        collection_path=target.path,
    )
    if apply:
        cli_mod._require_manager(cfg)
        if not backend.supports_write():
            cli_mod._exit_env("collections add --apply needs library write support.", cfg)
        apply_adds(backend, batch, target.key)
        cli_mod._flush(backend)
    folder = write_summary(cfg.state_dir, target.path, batch)
    counts = batch.counts()
    payload = envelope(
        command="collections add",
        summary=counts,
        items=[asdict(row) for row in batch.rows],
        paths={"summary": str(folder)},
        flags={"apply": apply, "dry_run": not apply},
        exit_code=collections_add_exit(
            apply=apply, added=int(counts["added"]), failed=int(counts["failed"])
        ),
    )

    def _human_add() -> None:
        table = Table(title="collections add")
        table.add_column("Key")
        table.add_column("Status")
        table.add_column("Title")
        table.add_column("Detail")
        for row in batch.rows:
            table.add_row(row.key, row.status, (row.title or "")[:50], row.detail)
        console.print(table)
        pending = int(counts["add"])
        console.print(
            f"added {counts['added']} · already-in {counts['already_in']} · "
            f"not-found {counts['not_found']}"
            + (f" · would-add {pending}" if not apply else "")
            + (f" · failed {counts['failed']}" if counts["failed"] else "")
            + (" (dry-run)" if not apply else "")
        )
        console.print(f"Summary: {folder}")

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_add)


def run_collections_children_paths(
    *,
    parent: str,
    exclude_name: str | None,
    config: Path | None,
) -> list[str]:
    """Direct children of a collection path, one path per line (sorted)."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg, quiet=True)
    cols = backend.collections()
    ocean = backend.resolve_collection(parent)
    out: list[str] = []
    for c in sorted(cols.values(), key=lambda x: x.path):
        if c.parent != ocean.key:
            continue
        if exclude_name and c.name == exclude_name:
            continue
        out.append(c.path)
    return out
