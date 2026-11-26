"""Typer command signatures, one module per verb family.

Imported by cli.py after the app tree exists. The modules load in this
order so ``--help`` lists commands as before.
"""

from __future__ import annotations

from paperful.cli import JOBS, app
from paperful.cli_bind import (
    _shared,
    core,
    tidy,
    find,
    mirror,
    ask,
    snowball,
    watch,
    metrics,
)

# cli.py re-exports every signature; tests and the workbench reach them there.
for _module in (
    _shared,
    core,
    tidy,
    find,
    mirror,
    ask,
    snowball,
    watch,
    metrics,
):
    for _name, _value in vars(_module).items():
        if not _name.startswith("__"):
            globals().setdefault(_name, _value)


def _reconcile_jobs() -> None:
    """Keep JOBS aligned with registered top-level Typer commands.

    Curated categories stay as written. Any command missing from JOBS is
    appended to utility so ``paperful jobs`` and CI cannot drift when a new
    ``@app.command`` is added. Stale JOBS entries (listed but not registered)
    raise so typos surface at import time.
    """
    from typer.main import get_command

    registered = set(getattr(get_command(app), "commands", {}))
    listed = [verb for verbs in JOBS.values() for verb in verbs]
    if len(listed) != len(set(listed)):
        dupes = sorted({v for v in listed if listed.count(v) > 1})
        raise RuntimeError(f"JOBS has duplicate verbs: {dupes}")
    listed_set = set(listed)
    orphans = sorted(registered - listed_set)
    if orphans:
        JOBS["utility"] = tuple((*JOBS["utility"], *orphans))
    stale = sorted(listed_set - registered)
    if stale:
        raise RuntimeError(
            f"JOBS lists commands that are not registered: {stale}. "
            "Remove them from JOBS or restore the @app.command."
        )


_reconcile_jobs()
