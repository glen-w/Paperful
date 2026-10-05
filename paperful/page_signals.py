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


# Exact miss buckets that should silence a vault host for the rest of a run.
# Prefix-only would wrongly match ``clicked download control, no PDF``.
_DEAD_VAULT_MISS_LABELS = frozenset({"login", "captcha", "no download control"})


def miss_host(note: str) -> str:
    """Hostname from a ``label @host`` miss note, or empty when absent."""
    head = (note or "").split(";", 1)[0].strip()
    if " @" not in head:
        return ""
    host = head.split(" @", 1)[1].strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def looks_like_dead_vault_miss(note: str) -> bool:
    """True when a vault miss should block that final host for the run."""
    raw = (note or "").strip()
    if not raw:
        return False
    label = miss_label(raw).lower()
    if label in _DEAD_VAULT_MISS_LABELS:
        return True
    # Older CAS notes that never classified as ``login``.
    return looks_like_vault_login_miss(raw)


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


_COOKIE_HINTS = (
    "cookie consent",
    "we use cookies",
    "accept all cookies",
    "manage cookies",
    "this website uses cookies",
)
_ACCESS_HINTS = (
    "access options",
    "choose your access",
    "purchase options",
    "view full text options",
)
_PDF_OFFER_HINTS = (
    "download pdf",
    "view pdf",
    "download this article",
    "full text pdf",
    "pdf download",
)
_PRINT_BLOCK_LABELS = frozenset({"captcha", "cloudflare", "blocked", "paywall"})


def title_overlap(title: str | None, body: str | None) -> bool:
    """True when enough of the item title appears in the page text."""
    from .dedupe import normalize_dedupe_title

    tokens = [tok for tok in normalize_dedupe_title(title).split() if len(tok) > 3]
    if len(tokens) < 3:
        tokens = normalize_dedupe_title(title).split()
    if not tokens:
        return False
    low = (body or "").lower()
    hits = sum(1 for tok in tokens if tok in low)
    return hits >= max(2, int(len(tokens) * 0.6))


def print_page_refusal(
    url: str | None,
    body: str | None,
    *,
    title: str = "",
    require_article: bool = False,
) -> str | None:
    """Why this HTML must not be printed, or None when a snapshot is allowed.

    Refuses cookie walls, access-option landings, login/paywall/captcha pages,
    and pages that still offer a native PDF download. ``require_article`` also
    demands title overlap and a body long enough to be the article.
    """
    text = body or ""
    low = text.lower()
    block = classify_page_block(text)
    if block in _PRINT_BLOCK_LABELS:
        return block
    if looks_like_login_page(url or "", text):
        return "login"
    if any(hint in low for hint in _COOKIE_HINTS) and len(low) < 1800:
        return "cookie-wall"
    if any(hint in low for hint in _ACCESS_HINTS) and len(text) < 2500:
        return "access-options"
    if any(hint in low for hint in _PDF_OFFER_HINTS):
        return "native-pdf-offered"
    if require_article:
        if len(text) < 1500:
            return "short-page"
        if not title_overlap(title, text):
            return "title-mismatch"
    return None


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
