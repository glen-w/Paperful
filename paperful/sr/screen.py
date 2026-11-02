"""Screening ledger: include / exclude / maybe with reason codes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..fsio import append_jsonl

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


def latest_decisions(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Latest ledger line per identity. Earlier lines stay on disk."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        ident = str(row.get("identity") or "").strip()
        if ident:
            out[ident] = row
    return out


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
    if decision == "exclude":
        from .protocol import load_protocol

        allowed = [
            str(item).strip()
            for item in (load_protocol(state_dir, slug).get("exclude_reasons") or [])
            if str(item).strip()
        ]
        if reason.strip() not in allowed:
            raise ValueError(f"exclude reason {reason!r} is not on the protocol list")
    row = {
        "schema": SCHEMA,
        "identity": identity,
        "decision": decision,
        "reason": reason,
        "reviewer": reviewer,
        "at": datetime.now(tz=timezone.utc).isoformat(),
    }
    path = ledger_path(state_dir, slug)
    line = json.dumps(row, ensure_ascii=False)
    append_jsonl(path, line, lock=(state_dir, f"sr-{slug}-screen"))
