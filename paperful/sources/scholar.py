"""Google Scholar: look for free [PDF] / [HTML] links in a title or DOI query.

Fragile: Scholar serves CAPTCHAs to automated clients. Treat CAPTCHA/blocks as
transient errors so the item is retried later; disable the source in config if noisy.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

from ..zot import Item
from .base import Candidate, Context, Outcome

NAME = "scholar"
_PROBE_URL = "https://scholar.google.com/scholar?q=information&hl=en&as_sdt=0%2C5"

_SKIP_HOSTS = (
    "scholar.google.",
    "accounts.google.",
    "doi.org",
    "dx.doi.org",
    "sciencedirect.com/science/article/abs/",  # abs pages are not PDFs
    "link.springer.com/article/",  # landing, not file
    "onlinelibrary.wiley.com/doi/abs/",
    "tandfonline.com/doi/abs/",
    "jstor.org/stable/",
)


def is_blocked(resp: httpx.Response) -> bool:
    final = str(resp.url).lower()
    body = resp.text
    if resp.status_code in {429, 503} or "sorry" in final or "/sorry/" in final:
        return True
    return "captcha" in body.lower()[:3000] and "gs_r" not in body


def looks_like_results(html: str) -> bool:
    return "gs_r" in html or "gs_ri" in html


def session_ok(ctx: Context) -> tuple[bool, str]:
    """Cheap check: probe Scholar with exported browser cookies."""
    from ..cookies import has_domain_cookies

    cookie_path = ctx.config.scholar_cookies or (ctx.config.state_dir / "scholar-cookies.txt")
    if not cookie_path.is_file():
        return False, f"cookie file missing ({cookie_path})"
    if not has_domain_cookies(ctx.client, "google"):
        return False, "scholar cookies not loaded into client"
    try:
        resp = ctx.client.get(_PROBE_URL, timeout=30)
    except httpx.HTTPError as exc:
        return False, f"request failed: {type(exc).__name__}"
    if is_blocked(resp):
        host = str(resp.url).split("?", 1)[0]
        return False, f"blocked or CAPTCHA (HTTP {resp.status_code} at {host})"
    if looks_like_results(resp.text):
        return True, f"ok ({resp.status_code})"
    return False, f"unexpected response ({resp.status_code})"


def find(item: Item, ctx: Context) -> Candidate:
    query = item.doi or item.title
    if not query or (not item.doi and len(item.title) < 20):
        return Candidate.miss(NAME, Outcome.SKIPPED, "no query")
    q = f'"{item.doi}"' if item.doi else item.title
    url = f"https://scholar.google.com/scholar?q={quote_plus(q)}&hl=en&as_sdt=0%2C5"
    try:
        resp = ctx.client.get(url, timeout=30)
    except httpx.HTTPError as exc:
        return Candidate.miss(NAME, Outcome.ERROR, f"request failed ({type(exc).__name__})")

    body = resp.text
    if is_blocked(resp):
        return Candidate.miss(NAME, Outcome.CAPTCHA, "scholar blocked/captcha")
    if resp.status_code >= 400:
        return Candidate.miss(NAME, Outcome.ERROR, f"HTTP {resp.status_code}")

    pdfs = extract_pdf_links(body, str(resp.url))
    if not pdfs:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no free PDF link")
    return Candidate(url=pdfs[0], source=NAME, note="google scholar", referer=str(resp.url), alternates=pdfs[1:4])


def extract_pdf_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []

    def add(href: str | None) -> None:
        if not href:
            return
        abs_url = urljoin(base_url, href.strip())
        low = abs_url.lower()
        # Keep Google redirectors so we can unwrap them below; skip other GS chrome.
        if "scholar.google." in low and "url=" not in low:
            return
        if any(h in low for h in _SKIP_HOSTS if "scholar.google" not in h):
            return
        if abs_url not in found:
            found.append(abs_url)

    # Sidebar / "All versions" PDF buttons
    for a in soup.select("div.gs_or_ggsm a, a.gs_or_ggsm"):
        add(a.get("href"))
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True).lower()
        href = a["href"]
        if text.startswith("[pdf]") or text == "pdf" or href.lower().split("?")[0].endswith(".pdf"):
            add(href)
    # Strip Google redirector
    cleaned: list[str] = []
    for u in found:
        m = re.search(r"[?&]url=([^&]+)", u)
        if "scholar.google." in u and m:
            from urllib.parse import unquote

            cleaned.append(unquote(m.group(1)))
        else:
            cleaned.append(u)
    # De-dupe preserving order
    out: list[str] = []
    for u in cleaned:
        if u not in out and not any(h in u.lower() for h in _SKIP_HOSTS):
            out.append(u)
    return out
