"""Ask mode: simple (today's path) or advanced (score-then-answer)."""

from __future__ import annotations

from ..config import Config, parse_rag_ask_mode

ASK_MODES = ("simple", "advanced")


def resolve_ask_mode(cfg: Config, override: str | None = None) -> str:
    """Per-run override wins; blank or omitted uses ``[rag].ask_mode``."""
    if override is not None and str(override).strip():
        return parse_rag_ask_mode(str(override))
    return parse_rag_ask_mode(cfg.rag_ask_mode)
