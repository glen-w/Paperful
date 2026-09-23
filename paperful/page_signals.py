"""Short labels for a page that did not yield a PDF.

Playwright's click-and-download pass and the browser-use agent share these
labels so a later success can be compared with the earlier miss.
"""

from __future__ import annotations

from urllib.parse import urlparse

# First match wins. Captcha and Cloudflare stay distinct from a paywall so a
# run report can show which block is common.
_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "captcha",
        (
            "captcha",
            "robot check",
            "are you a robot",
            "unusual traffic",
            "verify you are human",
        ),
    ),
    (
        "cloudflare",
        (
            "cloudflare",
            "cloudfront",
            "security verification",
            "performing security verification",
            "error 418",
        ),
    ),
    (
        "blocked",
        (
            "request blocked",
            "access denied",
            "403 forbidden",
            "http 403",
            "content not available",
        ),
    ),
    (
        "paywall",
        (
            "paywall",
            "buy article",
            "buy this article",
            "purchase access",
            "add to cart",
            "subscription required",
            "subscribe to continue",
            "subscribe to read",
            "sign in to read",
        ),
    ),
    (
        "login",
        (
            "log in",
            "login",
            "sign in",
            "institutional login",
        ),
    ),
)


def host_label(url: str | None) -> str:
    """Hostname without a leading ``www.``, or empty when the URL has none."""
    if not url:
        return ""
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def classify_page_block(text: str | None) -> str | None:
    """Return a block label when ``text`` looks like a wall, else None."""
    if not text:
        return None
    low = text.lower()
    for label, hints in _LABELS:
        if any(hint in low for hint in hints):
            return label
    return None


def miss_label(note: str) -> str:
    """Stable bucket for a browser-agent miss note (drops host and snippet)."""
    head = note.split(";", 1)[0].strip()
    head = head.split(" @", 1)[0].strip()
    return head or "unknown"


def format_miss(label: str, url: str | None, *, extra: str = "") -> str:
    """``paywall @springer.com; steps 4/8`` with parentheses stripped from extra."""
    host = host_label(url)
    note = f"{label} @{host}" if host else label
    cleaned = " ".join((extra or "").split()).replace("(", "[").replace(")", "]")
    if cleaned:
        if len(cleaned) > 90:
            cleaned = cleaned[:87] + "..."
        note = f"{note}; {cleaned}"
    return note
