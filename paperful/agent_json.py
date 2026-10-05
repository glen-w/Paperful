"""Machine channel for batch verbs. Human banners stay the default."""

from __future__ import annotations

import json
from typing import Any

SCHEMA = "paperful.agent.json.v1"

EXIT_OK = 0
EXIT_USER = 1
EXIT_ENV = 2
EXIT_PARTIAL = 3


def envelope(
    *,
    command: str,
    summary: dict[str, Any],
    items: list[dict[str, Any]] | None = None,
    paths: dict[str, Any] | None = None,
    flags: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
    exit_code: int = EXIT_OK,
    partial: bool | None = None,
) -> dict[str, Any]:
    """Stable stdout JSON for ``--format json``."""
    is_partial = bool(partial) if partial is not None else exit_code == EXIT_PARTIAL
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "command": command,
        "exit": exit_code,
        "ok": exit_code == EXIT_OK,
        "partial": is_partial,
        "summary": summary,
        "items": items or [],
        "paths": paths or {},
        "flags": flags or {},
    }
    if report is not None:
        body["report"] = report
    return body


def batch_exit(*, ok: int, failed: int) -> int:
    """One code for mixed batches. Empty success is still 0."""
    if failed and ok:
        return EXIT_PARTIAL
    if failed:
        return EXIT_USER
    return EXIT_OK


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
