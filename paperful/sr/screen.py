"""Screening ledger: include / exclude / maybe with reason codes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..fsio import atomic_write_text, file_lock

SCHEMA = "paperful.sr.screen.v1"
SCREEN_KEYS = frozenset({"schema", "identity", "decision", "reason", "reviewer", "at"})


def ledger_path(state_dir: Path, slug: str) -> Path:
    from .protocol import review_dir

    return review_dir(state_dir, slug) / "screening.jsonl"


def load_screen_ledger(state_dir: Path, slug: str) -> list[dict[str, Any]]:
    path = ledger_path(state_dir, slug)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append_screen_decision(
    state_dir: Path,
    slug: str,
    *,
    identity: str,
    decision: str,
    reason: str,
    reviewer: str,
) -> None:
    if decision not in {"include", "exclude", "maybe"}:
        raise ValueError(f"invalid decision {decision!r}")
    row = {
        "schema": SCHEMA,
        "identity": identity,
        "decision": decision,
        "reason": reason,
        "reviewer": reviewer,
        "at": datetime.now(tz=timezone.utc).isoformat(),
    }
    path = ledger_path(state_dir, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with file_lock(state_dir, f"sr-{slug}-screen"):
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
