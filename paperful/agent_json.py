"""Machine channel for batch verbs. Human banners stay the default."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

SCHEMA = "paperful.agent.json.v1"

EXIT_OK = 0
EXIT_USER = 1
EXIT_ENV = 2
EXIT_PARTIAL = 3

REQUIRED_KEYS = (
    "schema",
    "command",
    "exit",
    "ok",
    "partial",
    "summary",
    "items",
    "paths",
    "flags",
)


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


_suppress_stdout: ContextVar[bool] = ContextVar("agent_json_suppress_stdout", default=False)


def stdout_suppressed() -> bool:
    return bool(_suppress_stdout.get())


@contextmanager
def suppress_stdout() -> Iterator[None]:
    """Skip writing the envelope (nested ``all`` substeps). Exit codes still apply."""
    token = _suppress_stdout.set(True)
    try:
        yield
    finally:
        _suppress_stdout.reset(token)


def emit_stdout(payload: dict[str, Any]) -> None:
    """One JSON object on stdout. No-op when nested under ``all --format json``."""
    if stdout_suppressed():
        return
    sys.stdout.write(dumps(payload) + "\n")
    sys.stdout.flush()
