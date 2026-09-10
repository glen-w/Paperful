"""Render web/news/blog HTML pages to PDF via Playwright Chromium (optional extra)."""

from __future__ import annotations

from ..zot import Item
from .base import Candidate, Context, Outcome

NAME = "htmlpdf"

_WEB_TYPES = frozenset(
    {
        "webpage",
        "blogPost",
        "forumPost",
        "newspaperArticle",
        "magazineArticle",
    }
)
_DOC_TYPES = frozenset({"document", "report"})
_SKIP_HOSTS = (
    "doi.org",
    "scholar.google",
    "zotero.org",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "facebook.com",
    "consensus.app",
    "semanticscholar.org",
    "researchgate.net",
)
_PAYWALL_HINTS = (
    "subscribe to continue",
    "create an account to read",
    "sign in to read",
    "metered paywall",
    "subscription required",
    "pour lire la suite",
    "articles restants",
)


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def find(item: Item, ctx: Context) -> Candidate:
    if item.item_type not in _WEB_TYPES and not (
        item.item_type in _DOC_TYPES and item.url and not item.doi
    ):
        return Candidate.miss(NAME, Outcome.SKIPPED, "not a web/news item")
    url = (item.url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return Candidate.miss(NAME, Outcome.SKIPPED, "no URL")
    if any(h in url.lower() for h in _SKIP_HOSTS):
        return Candidate.miss(NAME, Outcome.SKIPPED, "resolver/aggregator URL")
    use_browser = ctx.browser is not None and ctx.browser.available()
    if not use_browser and not playwright_available():
        return Candidate.miss(
            NAME,
            Outcome.SKIPPED,
            "install paperful[htmlpdf] + playwright install chromium",
        )

    try:
        if use_browser:
            pdf_bytes, final_url, note = ctx.browser.render_pdf(url, _PAYWALL_HINTS)
        else:
            pdf_bytes, final_url, note = _render_pdf(url, ctx.config.user_agent)
    except Exception as exc:  # Playwright / browser errors
        return Candidate.miss(NAME, Outcome.ERROR, type(exc).__name__)

    if note == "paywall":
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "paywall-like page")
    if not pdf_bytes or not pdf_bytes.lstrip().startswith(b"%PDF"):
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "render produced no PDF")
    if len(pdf_bytes) < ctx.config.min_pdf_bytes:
        return Candidate.miss(
            NAME, Outcome.NOT_FOUND, f"too small ({len(pdf_bytes)} bytes)"
        )

    return Candidate(
        url=final_url or url,
        source=NAME,
        note=note or "chromium print",
        content=pdf_bytes,
    )


def _render_pdf(url: str, user_agent: str) -> tuple[bytes, str, str]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=user_agent)
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            body = ""
            try:
                body = page.inner_text("body")[:4000].lower()
            except Exception:
                pass
            if any(h in body for h in _PAYWALL_HINTS):
                return b"", str(page.url), "paywall"
            pdf = page.pdf(
                format="A4",
                print_background=True,
                margin={
                    "top": "12mm",
                    "bottom": "12mm",
                    "left": "12mm",
                    "right": "12mm",
                },
            )
            return pdf, str(page.url), "chromium print"
        finally:
            browser.close()
