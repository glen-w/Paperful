"""Shared Discover route helpers (no FastAPI registration)."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from . import commands
from .context import UiContext


def last_review_token(ui: UiContext, verb: str) -> str:
    for rec in commands.list_commands(ui.cfg, limit=20):
        if rec.get("verb") == verb and rec.get("review_token"):
            return str(rec["review_token"])
    return ""


def safe_list_name(raw: object, default: str = "") -> str | None:
    """Return a validated authorwatch list name, ``default`` when blank, or
    ``None`` when the value fails ``authorwatch._NAME_RE``.

    List names are reflected into templates and used as directory names, so
    every GET/POST that reads one must go through here before rendering.
    """
    from ..authorwatch import _NAME_RE

    name = str(raw or "").strip()
    if not name:
        return default
    if not _NAME_RE.match(name):
        return None
    return name


def bad_list_name() -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": "invalid list name (letters, digits, '.', '_', '-' only)",
        },
        status_code=400,
    )
