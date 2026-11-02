"""Shared Discover route helpers (no FastAPI registration)."""

from __future__ import annotations

from . import commands
from .context import UiContext


def last_review_token(ui: UiContext, verb: str) -> str:
    for rec in commands.list_commands(ui.cfg, limit=20):
        if rec.get("verb") == verb and rec.get("review_token"):
            return str(rec["review_token"])
    return ""
