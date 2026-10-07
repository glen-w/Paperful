"""``paperful notes delete`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .library import LibraryError


def run_notes_delete(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    item: list[str],
    note_type: list[str],
    model: str,
    except_model: str,
    all_owned: bool,
    apply: bool,
    yes: bool,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli as cli_mod
    from .agent_json import batch_exit, envelope
    from .notes import NOTE_TYPES, apply_delete, collect, select

    if not item and cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    if all_owned and (note_type or model.strip()):
        console.print("[red]Do not combine --all with --type or --model.[/]")
        raise typer.Exit(1)
    types: frozenset[str] | None = None
    if note_type:
        types = frozenset(t.strip().lower() for t in note_type if t.strip())
        unknown = types - NOTE_TYPES
        if unknown:
            console.print(f"[red]Unknown --type: {', '.join(sorted(unknown))}[/]")
            raise typer.Exit(1)
    if not all_owned and types is None and not model.strip() and not except_model.strip():
        console.print(
            "[red]Give --type, --model / --except-model, or --all.[/]"
        )
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
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
    if not item and not collection and not library:
        cli_mod._refuse_missing_scope()
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg, quiet=json_out)
    loaded = cli_mod._load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library) or not collection,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items = loaded.items
    scope = loaded.label
    if item:
        want = set(item)
        items = [it for it in items if it.key in want]
        if not items:
            console.print("[red]No matching --item keys in scope.[/]")
            raise typer.Exit(1)
    cols = []
    if collection:
        for spec in collection:
            try:
                cols.append(backend.resolve_collection(spec))
            except LookupError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1) from exc
    hits = collect(backend, items, cfg, collections=cols)
    matched = select(
        hits,
        types=types,
        model=model,
        except_model=except_model,
        all_owned=all_owned,
    )
    if apply and all_owned and not yes:
        if not cli_mod.sys.stdin.isatty():
            console.print("[red]--apply --all needs a TTY confirm or --yes.[/]")
            raise typer.Exit(1)
        if not typer.confirm(f"Trash {len(matched)} Paperful note(s) in {scope}?"):
            raise typer.Exit(1)
    trashed = 0
    errors: list[str] = []
    if apply:
        if not backend.supports_write():
            cli_mod._exit_env(cli_mod._no_write(backend), cfg)
        try:
            trashed, errors = apply_delete(backend, matched)
        except LibraryError as exc:
            cli_mod._exit_env(str(exc), cfg)
        cli_mod._flush(backend)
    code = batch_exit(ok=trashed, failed=len(errors)) if apply else 0
    payload = envelope(
        command="notes delete",
        summary={
            "matched": len(matched),
            "trashed": trashed,
            "errors": len(errors),
            "skipped_not_paperful": max(0, len(hits) - len(matched)) if all_owned else 0,
        },
        items=[
            {
                "noteKey": h.note_key,
                "parentKey": h.parent_key,
                "title": h.title,
                "type": h.note_type,
                "model": h.model,
                "standalone": h.standalone,
            }
            for h in matched
        ],
        flags={
            "apply": apply,
            "all": all_owned,
            "types": sorted(types) if types else [],
            "model": model,
            "except_model": except_model,
        },
        exit_code=code,
    )

    def _human_notes() -> None:
        console.print(f"Scope: [bold]{scope}[/] — {len(matched)} Paperful note(s)")
        if matched:
            table = Table(title="notes delete" + ("" if apply else " (dry-run)"))
            table.add_column("Note")
            table.add_column("Parent")
            table.add_column("Type")
            table.add_column("Model")
            for h in matched[:100]:
                table.add_row(h.note_key, h.parent_key or "(collection)", h.note_type, h.model)
            console.print(table)
        if apply:
            console.print(f"Trashed {trashed}. Errors {len(errors)}.")
            for err in errors[:20]:
                console.print(f"[yellow]{err}[/]")
        else:
            console.print("Dry-run. Pass [bold]--apply[/] to trash these notes.")

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_notes)

