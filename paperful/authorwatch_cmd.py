"""``paperful authorwatch`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .config import Config, parse_pdfs
from .library import LibraryError
from .runreport import write_command_report, write_run_report
from .store import Manifest
from . import cli_runtime as cli_mod


def _authorwatch_call(action: Any) -> Any:
    from .authorwatch import AuthorwatchError

    try:
        return action()
    except AuthorwatchError as exc:
        console = cli_mod.console
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc

def run_authorwatch_save(
    console: Console,
    name: Any,
    config: Any,
) -> None:
    """Create an empty people list. No API keys."""
    from . import cli_runtime as cli_mod

    from .authorwatch import save_list

    cfg = cli_mod._cfg(config)
    path = _authorwatch_call(lambda: save_list(cfg, name))
    console.print(f"Wrote [bold]{path}[/]")

def run_authorwatch_add(
    console: Console,
    name: Any,
    orcid: Any,
    display_name: Any,
    affiliation: Any,
    config: Any,
) -> None:
    """Append a person. --orcid is enough; --name stays unresolved until resolve."""
    from . import cli_runtime as cli_mod

    from .authorwatch import add_person

    cfg = cli_mod._cfg(config)
    person = _authorwatch_call(
        lambda: add_person(
            cfg,
            name,
            orcid=orcid,
            display_name=display_name,
            affiliation_host=affiliation,
        )
    )
    console.print(
        f"Added {person.display_name or person.id} · {person.status} · {person.identity()}"
    )

def run_authorwatch_remove(
    console: Console,
    name: Any,
    orcid: Any,
    person_id: Any,
    config: Any,
) -> None:
    """Drop a member by ORCID or id."""
    from . import cli_runtime as cli_mod

    from .authorwatch import remove_person

    cfg = cli_mod._cfg(config)
    person = _authorwatch_call(
        lambda: remove_person(cfg, name, orcid=orcid, person_id=person_id)
    )
    console.print(f"Removed {person.display_name or person.id}")

def run_authorwatch_show(
    console: Console,
    name: Any,
    config: Any,
) -> None:
    """People counts, held candidates, baseline, next step. Does not open the library."""
    from . import cli_runtime as cli_mod

    from .authorwatch import show_list

    cfg = cli_mod._cfg(config)
    _authorwatch_call(lambda: show_list(cfg, name, console=console))

def run_authorwatch_resolve(
    console: Console,
    name: Any,
    config: Any,
) -> None:
    """Fill missing ORCID/OpenAlex ids. Ambiguous names stay held."""
    from . import cli_runtime as cli_mod

    from .authorwatch import resolve_people

    cfg = cli_mod._cfg(config)
    people = _authorwatch_call(lambda: resolve_people(cfg, name))
    ok = sum(1 for row in people if row.is_ok())
    held = sum(1 for row in people if row.status == "held")
    unresolved = sum(1 for row in people if row.status == "unresolved")
    console.print(f"ok {ok} · held {held} · unresolved {unresolved}")

def run_authorwatch_suggest(
    console: Console,
    name: Any,
    collection: Any,
    method: Any,
    limit: Any,
    config: Any,
) -> None:
    """Propose people to follow from a collection (local corpus / OpenAlex)."""
    from . import cli_runtime as cli_mod

    from .authorwatch_suggest import suggest_people

    cfg = cli_mod._cfg(config)
    rows = _authorwatch_call(
        lambda: suggest_people(
            cfg,
            name,
            collection=collection,
            method=method,
            limit=limit,
        )
    )
    console.print(f"Added {len(rows)} suggestion(s)")

def run_authorwatch_accept(
    console: Console,
    name: Any,
    suggestion_id: Any,
    all_pending: Any,
    dismiss_rest: Any,
    seed_from: Any,
    config: Any,
) -> None:
    """Move checked suggestions onto the people list."""
    from . import cli_runtime as cli_mod

    from .authorwatch import accept_suggestions, run_list

    cfg = cli_mod._cfg(config)
    accepted = _authorwatch_call(
        lambda: accept_suggestions(
            cfg,
            name,
            ids=set(suggestion_id),
            all_pending=all_pending,
            dismiss_rest=dismiss_rest,
        )
    )
    console.print(f"Accepted {len(accepted)} person(s)")
    if seed_from:
        _authorwatch_call(
            lambda: run_list(
                cfg,
                name,
                console=console,
                backfill_from=seed_from,
            )
        )

def run_authorwatch_delete(
    console: Console,
    name: Any,
    yes: Any,
    config: Any,
) -> None:
    """Delete a list and its ledger."""
    from . import cli_runtime as cli_mod

    from .authorwatch import delete_list

    cfg = cli_mod._cfg(config)
    _authorwatch_call(lambda: delete_list(cfg, name, yes=yes))
    console.print(f"Deleted list {name}")

def run_authorwatch_import(
    console: Console,
    name: Any,
    path: Any,
    source: Any,
    config: Any,
) -> None:
    """Import people from a file. Social --source without --file prints the export recipe."""
    from . import cli_runtime as cli_mod

    from .authorwatch import import_file

    cfg = cli_mod._cfg(config)
    added = _authorwatch_call(
        lambda: import_file(cfg, name, path=path, source=source)
    )
    console.print(f"Imported {len(added)} row(s)")

def run_authorwatch_run(
    console: Console,
    name: Any,
    backfill_from: Any,
    max_authors: Any,
    per_author_limit: Any,
    config: Any,
) -> None:
    """Cursor baseline (proposes 0) unless --backfill-from. Never creates library items."""
    from . import cli_runtime as cli_mod

    from .authorwatch import run_list

    cfg = cli_mod._cfg(config)
    _authorwatch_call(
        lambda: run_list(
            cfg,
            name,
            console=console,
            backfill_from=backfill_from,
            max_authors=max_authors,
            per_author_limit=per_author_limit,
        )
    )

def run_authorwatch_briefing(
    console: Console,
    name: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Write markdown from the inbox plus OpenAlex people context. Does not create items."""
    from . import cli_runtime as cli_mod

    from .agent_json import envelope
    from .authorwatch import gather_briefing, write_briefing

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)

    def _run() -> None:
        data = gather_briefing(cfg, name)
        path = write_briefing(cfg, name, data=data)

        def _human() -> None:
            console.print(f"Wrote [bold]{path}[/]")
            console.print(
                f"People enriched: {data.get('enriched_people', 0)} "
                f"(of {data.get('ok_people', 0)} ok)"
            )

        payload = envelope(
            command="authorwatch briefing",
            summary={
                "list": name,
                "proposed": len(data.get("proposed") or []),
                "ok_people": data.get("ok_people", 0),
                "enriched_people": data.get("enriched_people", 0),
                "people": data.get("people") or [],
            },
            paths={"briefing": str(path)},
            flags={"read_only": True},
        )
        cli_mod._emit_agent(payload, json_out=json_out, human=_human)

    _authorwatch_call(_run)

def run_authorwatch_digest(
    console: Console,
    name: Any,
    config: Any,
) -> None:
    """Write digest.md from the inbox. Does not create items."""
    from . import cli_runtime as cli_mod

    from .authorwatch import write_digest

    cfg = cli_mod._cfg(config)
    path = _authorwatch_call(lambda: write_digest(cfg, name))
    console.print(f"Wrote [bold]{path}[/]")

def run_authorwatch_apply(
    console: Console,
    name: Any,
    collection: Any,
    apply: Any,
    config: Any,
) -> None:
    """Create inbox rows in -C. Independent of [snowball] enabled."""
    from . import cli_runtime as cli_mod

    from .authorwatch import apply_list

    cfg = cli_mod._cfg(config)
    backend = None
    if apply:
        cli_mod._require_manager(cfg)
        backend = cli_mod._connect(cfg)
        if not backend.supports_write():
            cli_mod._exit_env(cli_mod._no_write(backend), cfg)

    def _go() -> Any:
        return apply_list(
            cfg,
            name,
            collection,
            console=console,
            apply=apply,
            backend=backend,
        )

    result = _authorwatch_call(_go)
    if result.failed and result.created:
        raise typer.Exit(3)

