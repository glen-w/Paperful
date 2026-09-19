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
    return _blocked_html(resp.text, str(resp.url), status=resp.status_code)


def _blocked_html(body: str, final_url: str, status: int = 200) -> bool:
    final = final_url.lower()
    if status in {429, 503} or "sorry" in final or "/sorry/" in final:
        return True
    return "captcha" in body.lower()[:3000] and "gs_r" not in body


def looks_like_results(html: str) -> bool:
    return "gs_r" in html or "gs_ri" in html


def session_ok(ctx: Context) -> tuple[bool, str]:
    """Cheap check: probe Scholar with exported cookies or a persistent profile."""
    from ..cookies import has_domain_cookies
    from ..session import profile_ready, vault_cookies_path

    cookie_path = ctx.config.scholar_cookie_path
    vault = vault_cookies_path(ctx.config)
    if (
        not cookie_path.is_file()
        and not vault.is_file()
        and not profile_ready(ctx.config)
    ):
        return False, f"cookie file missing ({cookie_path})"
    if ctx.browser is not None and ctx.browser.available():
        try:
            body, final = ctx.browser.fetch_html(_PROBE_URL)
        except Exception as exc:
            return False, f"browser request failed: {type(exc).__name__}"
        if _blocked_html(body, final):
            host = final.split("?", 1)[0]
            return False, f"blocked or CAPTCHA at {host}"
        if looks_like_results(body):
            return True, "ok (browser profile)"
        return False, "unexpected response (browser profile)"
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
        if ctx.browser is not None and ctx.browser.available():
            body, final_url = ctx.browser.fetch_html(url)
            final = final_url
        else:
            resp = ctx.client.get(url, timeout=30)
            body = resp.text
            final = str(resp.url)
            if resp.status_code >= 400:
                return Candidate.miss(NAME, Outcome.ERROR, f"HTTP {resp.status_code}")
    except httpx.HTTPError as exc:
        return Candidate.miss(
            NAME, Outcome.ERROR, f"request failed ({type(exc).__name__})"
        )
    except Exception as exc:
        return Candidate.miss(NAME, Outcome.ERROR, f"browser ({type(exc).__name__})")

    if _blocked_html(body, final):
        return Candidate.miss(NAME, Outcome.CAPTCHA, "scholar blocked/captcha")

    pdfs = extract_pdf_links(body, final)
    if not pdfs:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no free PDF link")
    return Candidate(
        url=pdfs[0],
        source=NAME,
        note="google scholar",
        referer=final,
        alternates=pdfs[1:4],
    )


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
        if (
            text.startswith("[pdf]")
            or text == "pdf"
            or href.lower().split("?")[0].endswith(".pdf")
        ):
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
