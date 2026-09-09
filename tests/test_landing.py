"""OA landing-page → PDF URL helpers (offline)."""

from __future__ import annotations

import json

import httpx

from paperful.sources.landing import extract_pdf_urls, resolve_landings, rewrite_known_pdf_url
from tests.conftest import make_item


def _json(payload, status=200):
    return httpx.Response(status, content=json.dumps(payload).encode(), headers={"content-type": "application/json"})


def test_rewrite_known_pdf_url():
    assert rewrite_known_pdf_url("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1817752/") == (
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1817752/pdf/"
    )
    assert rewrite_known_pdf_url("https://europepmc.org/articles/PMC1817752") == (
        "https://europepmc.org/articles/PMC1817752?pdf=render"
    )
    assert rewrite_known_pdf_url("https://arxiv.org/abs/2101.00001") == "https://arxiv.org/pdf/2101.00001"
    assert rewrite_known_pdf_url("https://hal.science/hal-01234567") == "https://hal.science/hal-01234567/document"
    assert rewrite_known_pdf_url("https://dspace.example/handle/1874/1") is None


def test_extract_pdf_urls_meta_and_pii():
    html = """
    <html><head><meta name="citation_pdf_url" content="/a.pdf"></head>
    <body><a href="/science/article/pii/S123/pdfft?download=true">Download PDF</a></body></html>
    """
    urls = extract_pdf_urls(html, "https://www.sciencedirect.com/science/article/pii/S123")
    assert "https://www.sciencedirect.com/a.pdf" in urls
    assert any("pdfft" in u for u in urls)


def test_resolve_dspace_handle(ctx_factory):
    title = make_item().title
    item_url = "https://dspace.test/server/api/core/items/i1/bundles"
    bits_url = "https://dspace.test/server/api/core/bundles/b1/bitstreams"
    pdf = "https://dspace.test/server/api/core/bitstreams/x/content"

    def handler(req):
        path = req.url.path
        if path.endswith("/pid/find"):
            assert req.url.params["id"] == "1874/362673"
            return _json({"name": title, "_links": {"bundles": {"href": item_url}}})
        if path.endswith("/bundles"):
            return _json({"_embedded": {"bundles": [{"name": "ORIGINAL", "_links": {"bitstreams": {"href": bits_url}}}]}})
        if path.endswith("/bitstreams"):
            return _json({"_embedded": {"bitstreams": [{"name": "paper.pdf", "_links": {"content": {"href": pdf}}}]}})
        return httpx.Response(404)

    assert resolve_landings(ctx_factory(handler), ["https://dspace.test/handle/1874/362673"], title) == [pdf]


def test_resolve_dspace_skips_title_mismatch(ctx_factory):
    def handler(req):
        if req.url.path.endswith("/pid/find"):
            return _json({"name": "The Ambiguity of Accountability", "_links": {"bundles": {"href": "https://dspace.test/b"}}})
        return httpx.Response(404)

    assert resolve_landings(ctx_factory(handler), ["https://dspace.test/handle/1/2"], make_item().title) == []


def test_resolve_digital_commons_oai(ctx_factory):
    title = make_item().title
    pdf = "https://ink.test/context/sol_research/article/3959/viewcontent/paper.pdf"
    xml = f"""<?xml version="1.0"?>
    <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
      <GetRecord><record><metadata>
        <dc xmlns:dc="http://purl.org/dc/elements/1.1/">
          <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">{title}</dc:title>
          <dc:identifier xmlns:dc="http://purl.org/dc/elements/1.1/">{pdf}</dc:identifier>
        </dc>
      </metadata></record></GetRecord>
    </OAI-PMH>"""

    def handler(req):
        if req.url.path.rstrip("/") == "/do/oai":
            assert req.url.params["identifier"] == "oai:ink.test:sol_research-3959"
            return httpx.Response(200, text=xml, headers={"content-type": "text/xml"})
        return httpx.Response(404)

    assert resolve_landings(ctx_factory(handler), ["https://ink.test/sol_research/3959"], title) == [pdf]
