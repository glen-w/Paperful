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
            "problem providing the content",
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


_LOGIN_URL_HINTS = ("/cas/login", "federation.sciences-po.fr", "shibboleth")
_LOGIN_BODY_HINTS = (
    "central authentication service",
    "entrez votre identifiant",
    "shibboleth",
    "wayf",
    "select your institution",
)
_SEARCH_HOSTS = (
    "google.com",
    "bing.com",
    "duckduckgo.com",
    "yahoo.com",
    "baidu.com",
    "yandex.com",
    "yandex.ru",
    "scholar.google.com",
)


def host_label(url: str | None) -> str:
    """Hostname without a leading ``www.``, or empty when the URL has none."""
    if not url:
        return ""
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def looks_like_login_page(url: str, body: str) -> bool:
    """True for campus SSO / CAS / Shibboleth interstitials."""
    url_l = (url or "").lower()
    if any(x in url_l for x in _LOGIN_URL_HINTS):
        return True
    body_l = (body or "")[:4000].lower()
    if any(h in body_l for h in _LOGIN_BODY_HINTS):
        return True
    if (
        "idm.oclc.org" in url_l
        and "/login" in url_l
        and ("password" in body_l or "identifiant" in body_l)
    ):
        return True
    return False


def looks_like_vault_login_miss(note: str) -> bool:
    """True for vault browser misses that landed on campus SSO / CAS.

    Matches ``login @host`` and older ``no download control @federation…``
    notes where French CAS copy never hit ``classify_page_block``.
    """
    raw = (note or "").strip()
    if not raw:
        return False
    if miss_label(raw).lower() == "login":
        return True
    low = raw.lower()
    return any(h in low for h in _LOGIN_URL_HINTS)


def is_search_engine_host(host: str) -> bool:
    host = (host or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return any(host == s or host.endswith("." + s) for s in _SEARCH_HOSTS)


def same_site(left: str, right: str) -> bool:
    """True when two URLs share a host, or one hostname is under the other."""
    a, b = host_label(left), host_label(right)
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


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
