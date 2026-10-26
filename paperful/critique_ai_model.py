"""Optional model-backed AI-text score for critique.

Not a core dependency. Tries Binoculars (Hans et al., ICML 2024) if installed;
otherwise returns None so the pack can record ``ai_model_unavailable``.
Never used as proof of authorship.
"""

from __future__ import annotations

from typing import Any


def run_ai_model(text: str) -> dict[str, Any] | None:
    """Return ``{backend, score}`` or None if the extra is missing / fails."""
    try:
        from binoculars import Binoculars  # type: ignore
    except ImportError:
        return None
    try:
        bino = Binoculars()
        raw = bino.compute_score(text)
    except Exception:
        return None
    if isinstance(raw, (list, tuple)):
        if not raw:
            return None
        raw = raw[0]
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    return {"backend": "binoculars", "score": score}
