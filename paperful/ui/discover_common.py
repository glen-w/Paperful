"""Shared Discover route helpers (no FastAPI registration)."""

from __future__ import annotations

import re

from fastapi.responses import JSONResponse

from . import commands
from .context import UiContext


def last_review_token(ui: UiContext, verb: str) -> str:
    for rec in commands.list_commands(ui.cfg, limit=20):
        if rec.get("verb") == verb and rec.get("review_token"):
            return str(rec["review_token"])
    return ""


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def safe_id(raw: object) -> str:
    """A run id from a form or query string, or ``""`` when it is not one.

    Run ids become folder names under ``state/``. Anything with a path
    separator or ``..`` is treated as missing, which every caller handles.
    """
    text = str(raw or "").strip()
    return text if _ID_RE.match(text) and ".." not in text else ""


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
