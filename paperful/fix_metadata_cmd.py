"""``paperful fix-metadata`` implementation (CLI parses flags only)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .config import Config
from .library import LibraryError
from .runreport import write_command_report
from .store import Manifest

def run_fix_metadata(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    apply: bool | None,
    overwrite: bool | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli as cli_mod
    from .metadata import apply_patches, collect_patches, write_patches
    from .pipeline import make_client

    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(
        cfg,
        use_apply=True,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        apply=apply,
        overwrite=overwrite,
    )
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    limit = bound.limit
    apply = bound.apply
    overwrite = bound.overwrite
    if not collection and not library:
        cli_mod._refuse_missing_scope()
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg, quiet=json_out)
    manifest = Manifest(cfg.manifest_path)
    client = make_client(cfg)
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
    if limit:
        items = items[:limit]
    started = time.time()
    with cli_mod._item_progress(json_out=json_out) as progress:
        patches = collect_patches(
            client,
            cfg,
            items,
            backend=backend,
            manifest=manifest,
            overwrite=overwrite,
            track=cli_mod._track(progress, "Checking metadata"),
        )
    write_patches(cfg.patches_path, patches)
    field_counts: dict[str, int] = {}
    for p in patches:
        for key in p.after:
            field_counts[key] = field_counts.get(key, 0) + 1
    applied_n: int | None = None
    errors: list[str] = []
    if apply:
        if not backend.supports_write():
            cli_mod._exit_env(cli_mod._no_write(backend), cfg)
        try:
            with cli_mod._item_progress(json_out=json_out) as progress:
                applied_n, errors = apply_patches(
                    backend,
                    patches,
                    track=cli_mod._track(progress, "Applying patches"),
                )
        except LibraryError as exc:
            cli_mod._exit_env(str(exc), cfg)
        cli_mod._flush(backend)
    _write_fix_report(
        cfg,
        scope,
        patches,
        field_counts,
        applied=applied_n,
        errors=errors,
        apply=bool(apply),
        started=started,
    )
    from .agent_json import batch_exit, envelope

    code = 0
    if apply:
        code = batch_exit(ok=int(applied_n or 0), failed=len(errors))
    payload = envelope(
        command="fix-metadata",
        summary={
            "patches_proposed": len(patches),
            "fields_corrected_by_kind": field_counts,
            **({"patches_applied": applied_n} if applied_n is not None else {}),
            "errors": len(errors),
        },
        items=[
            {
                "itemKey": p.itemKey,
                "title": p.title,
                "status": "patched",
                "after": p.after,
            }
            for p in patches
        ],
        paths={"patches": str(cfg.patches_path)},
        flags={"apply": bool(apply), "overwrite": bool(overwrite)},
        exit_code=code,
    )

    def _human_fix() -> None:
        console.print(f"Scope: [bold]{scope}[/] — {len(patches)} proposed patches")
        if patches:
            table = Table(title="Proposed patches")
            table.add_column("Key", style="dim")
            table.add_column("Title")
            table.add_column("After")
            for p in patches:
                table.add_row(
                    p.itemKey,
                    p.title[:40],
                    ", ".join(f"{k}={v}" for k, v in p.after.items())[:80],
                )
            console.print(table)
        console.print(f"[dim]Wrote {len(patches)} lines to {cfg.patches_path}[/]")
        _print_fix_summary(
            console,
            len(patches),
            field_counts,
            applied=applied_n,
            errors=errors,
        )
        if not apply:
            console.print(
                "Dry-run. Pass [bold]--apply[/] to write these fields into the library."
            )

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_fix)

def _print_fix_summary(
    console: Console,
    proposed: int,
    field_counts: dict[str, int],
    *,
    applied: int | None,
    errors: list[str],
) -> None:
    kinds = ", ".join(f"{k}={v}" for k, v in sorted(field_counts.items())) or "none"
    console.print("\n[bold]Fix-metadata summary[/]")
    console.print(f"Fields corrected (proposed): {proposed} patches  ({kinds})")
    if applied is not None:
        console.print(f"Applied: {applied}/{proposed}")
    if errors:
        console.print(f"Errors: {len(errors)}")
        for err in errors[:20]:
            console.print(f"[yellow]{err}[/]")
        if len(errors) > 20:
            console.print(f"[dim]… and {len(errors) - 20} more[/]")

def _write_fix_report(
    cfg: Config,
    scope: str,
    patches: list,
    field_counts: dict[str, int],
    *,
    applied: int | None,
    errors: list[str],
    apply: bool,
    started: float | None = None,
) -> None:
    summary: dict[str, Any] = {
        "fields_corrected": sum(field_counts.values()),
        "fields_corrected_by_kind": field_counts,
        "patches_proposed": len(patches),
        "errors_by_type": {"apply_failed": len(errors)} if errors else {},
        "pdfs_downloaded": 0,
        "sources_checked": {},
    }
    if applied is not None:
        summary["patches_applied"] = applied
    write_command_report(
        cfg,
        command="fix-metadata",
        scope=scope,
        summary=summary,
        items=[
            {
                "itemKey": p.itemKey,
                "title": p.title,
                "status": "patched",
                "fields_corrected": list(p.after.keys()),
                "after": p.after,
                "before": p.before,
            }
            for p in patches
        ],
        flags={"apply": apply},
        started=started,
        errors=errors,
        extra_paths={"patches": str(cfg.patches_path)},
    )
