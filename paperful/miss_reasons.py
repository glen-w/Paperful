"""Grey-fetch miss labels. Counts and reasons only; no recall percentage."""

from __future__ import annotations

REASON_HOST_BLOCKED = "host_blocked"
REASON_HTML_NOT_PDF = "html_not_pdf"
REASON_ENGINE_SUSPENDED = "engine_suspended"

MISS_REASONS = frozenset(
    {REASON_HOST_BLOCKED, REASON_HTML_NOT_PDF, REASON_ENGINE_SUSPENDED}
)


def reason_from_attempts(attempts: list[str]) -> str:
    """Label a finished miss from attempt notes the fetcher already recorded."""
    text = "\n".join(attempts)
    if "HTTP 401" in text or "HTTP 403" in text:
        return REASON_HOST_BLOCKED
    low = text.lower()
    if "not a pdf" in low and "html" in low:
        return REASON_HTML_NOT_PDF
    if "html_not_pdf" in low or "refuse:" in low:
        return REASON_HTML_NOT_PDF
    return ""
