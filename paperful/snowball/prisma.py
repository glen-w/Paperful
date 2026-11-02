"""PRISMA-style counts for snowball queues. Additive; no recall percentage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

# Identified / screened / kept / added. Never a completeness %.
PRISMA_KEYS = ("identified", "screened", "kept", "added")


def prisma_counts(
    rows: Iterable[Any],
    *,
    added: int = 0,
    screened: int | None = None,
) -> dict[str, int]:
    """Count a candidate list. ``screened`` defaults to identified (every fetched work)."""
    items = list(rows)
    identified = len(items)
    kept = sum(1 for row in items if getattr(row, "keep", None) is True)
    if screened is None:
        screened = identified
    return {
        "identified": identified,
        "screened": max(0, int(screened)),
        "kept": kept,
        "added": max(0, int(added)),
    }


def _history_screened(history: Any) -> int | None:
    if not isinstance(history, list) or not history:
        return None
    total = 0
    found = False
    for row in history:
        if not isinstance(row, dict):
            continue
        if "screened" in row:
            found = True
            total += int(row.get("screened") or 0)
    return total if found else None


def prisma_from_stop(
    summary: dict[str, Any] | None = None,
    dest: Path | None = None,
) -> int | None:
    """Sum stop-rule ``screened`` iterations from summary or ``stop.json``."""
    if isinstance(summary, dict):
        stop = summary.get("stop")
        if isinstance(stop, dict):
            counted = _history_screened(stop.get("history"))
            if counted is not None:
                return counted
        counted = _history_screened(summary.get("stop_history"))
        if counted is not None:
            return counted
    if dest is None:
        return None
    path = dest / "stop.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return _history_screened(data.get("history"))
