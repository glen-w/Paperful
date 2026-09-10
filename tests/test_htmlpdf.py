"""htmlpdf source unit tests (no Chromium required for default suite)."""

from __future__ import annotations

import pytest

from paperful.sources import htmlpdf
from paperful.sources.base import Outcome
from tests.conftest import PDF_BYTES, make_item


def test_htmlpdf_skips_journal_with_doi(ctx_factory):
    ctx = ctx_factory(lambda r: None)
    cand = htmlpdf.find(
        make_item(item_type="journalArticle", url="https://news.test/a"), ctx
    )
    assert cand.outcome is Outcome.SKIPPED


def test_htmlpdf_skips_without_playwright(ctx_factory, monkeypatch):
    monkeypatch.setattr(htmlpdf, "playwright_available", lambda: False)
    ctx = ctx_factory(lambda r: None)
    cand = htmlpdf.find(
        make_item(
            key="W", doi=None, item_type="webpage", url="https://www.npr.org/story"
        ),
        ctx,
    )
    assert cand.outcome is Outcome.SKIPPED
    assert "paperful[htmlpdf]" in cand.note


def test_htmlpdf_uses_embedded_render(ctx_factory, monkeypatch):
    monkeypatch.setattr(htmlpdf, "playwright_available", lambda: True)
    monkeypatch.setattr(
        htmlpdf,
        "_render_pdf",
        lambda url, ua: (PDF_BYTES, url, "chromium print"),
    )
    ctx = ctx_factory(lambda r: None)
    cand = htmlpdf.find(
        make_item(
            key="W", doi=None, item_type="blogPost", url="https://blog.test/post"
        ),
        ctx,
    )
    assert cand.outcome is Outcome.FOUND
    assert cand.content == PDF_BYTES
    assert cand.source == "htmlpdf"


def test_htmlpdf_paywall_note(ctx_factory, monkeypatch):
    monkeypatch.setattr(htmlpdf, "playwright_available", lambda: True)
    monkeypatch.setattr(
        htmlpdf,
        "_render_pdf",
        lambda url, ua: (b"", url, "paywall"),
    )
    ctx = ctx_factory(lambda r: None)
    cand = htmlpdf.find(
        make_item(
            key="W", doi=None, item_type="newspaperArticle", url="https://news.test/pay"
        ),
        ctx,
    )
    assert cand.outcome is Outcome.NOT_FOUND
    assert "paywall" in cand.note


def test_htmlpdf_allows_report_without_doi(ctx_factory, monkeypatch):
    monkeypatch.setattr(htmlpdf, "playwright_available", lambda: True)
    monkeypatch.setattr(
        htmlpdf,
        "_render_pdf",
        lambda url, ua: (PDF_BYTES, url, "chromium print"),
    )
    ctx = ctx_factory(lambda r: None)
    cand = htmlpdf.find(
        make_item(
            key="R",
            doi=None,
            item_type="report",
            url="https://www.un.org/bbnj/prepcom",
        ),
        ctx,
    )
    assert cand.outcome is Outcome.FOUND


def test_htmlpdf_skips_report_with_doi(ctx_factory):
    ctx = ctx_factory(lambda r: None)
    cand = htmlpdf.find(
        make_item(
            key="R",
            doi="10.1000/x",
            item_type="report",
            url="https://www.un.org/bbnj/prepcom",
        ),
        ctx,
    )
    assert cand.outcome is Outcome.SKIPPED


def test_htmlpdf_uses_browser_session_when_available(ctx_factory):
    class StubBrowser:
        def available(self) -> bool:
            return True

        def render_pdf(self, url, hints, timeout_ms=45_000):
            return PDF_BYTES, url, "chromium print"

    ctx = ctx_factory(lambda r: None)
    ctx.browser = StubBrowser()
    cand = htmlpdf.find(
        make_item(
            key="W", doi=None, item_type="webpage", url="https://news.test/a"
        ),
        ctx,
    )
    assert cand.outcome is Outcome.FOUND
    assert cand.content == PDF_BYTES


@pytest.mark.skipif(
    not htmlpdf.playwright_available(), reason="playwright not installed"
)
def test_htmlpdf_live_render_smoke(ctx_factory):
    """Optional live Chromium print (no network) when Playwright + browser are available."""
    from playwright.sync_api import sync_playwright

    html = "<html><body><h1>Paperful htmlpdf smoke</h1><p>Hello.</p></body></html>"

    def _render(url, ua):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=ua)
                page.set_content(html, wait_until="domcontentloaded")
                pdf = page.pdf(format="A4")
                return pdf, "about:blank", "chromium print"
            finally:
                browser.close()

    import paperful.sources.htmlpdf as mod

    original = mod._render_pdf
    mod._render_pdf = _render
    try:
        ctx = ctx_factory(lambda r: None)
        ctx.config.min_pdf_bytes = 100
        cand = htmlpdf.find(
            make_item(
                key="S", doi=None, item_type="webpage", url="https://example.org/smoke"
            ),
            ctx,
        )
        assert cand.outcome is Outcome.FOUND
        assert cand.content and cand.content.lstrip().startswith(b"%PDF")
    finally:
        mod._render_pdf = original
