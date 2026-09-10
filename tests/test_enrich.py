"""Title/URL → DOI enrichment (mocked HTTP)."""

from __future__ import annotations

import json

import httpx

from paperful.resolve import (
    doi_from_page_meta,
    doi_from_url,
    enrich_identifiers,
    openalex_title_lookup,
    semanticscholar_title_lookup,
)
from tests.conftest import make_item, mock_client


def _json(payload, status=200):
    return httpx.Response(status, content=json.dumps(payload).encode(), headers={"content-type": "application/json"})


def test_doi_from_url_variants():
    assert doi_from_url("https://doi.org/10.1000/xyz").doi == "10.1000/xyz"
    assert doi_from_url("https://dx.doi.org/10.1000/xyz").doi == "10.1000/xyz"
    assert doi_from_url("https://example.org/paper?doi=10.1000/abc").doi == "10.1000/abc"
    assert doi_from_url("https://consensus.app/papers/10.1000/cons/").doi == "10.1000/cons"
    assert doi_from_url("https://www.npr.org/story") is None


def test_doi_from_page_meta():
    html = """
    <html><head>
      <meta name="citation_doi" content="10.5555/meta.doi">
    </head></html>
    """

    def handler(req):
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    m = doi_from_page_meta(mock_client(handler), "https://consensus.app/p/1")
    assert m and m.doi == "10.5555/meta.doi" and m.source == "meta"


def test_openalex_title_lookup():
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        assert "openalex.org" in str(req.url)
        return _json(
            {
                "results": [
                    {
                        "doi": "https://doi.org/10.1000/oa",
                        "display_name": title,
                        "publication_year": 2019,
                        "authorships": [{"author": {"display_name": "Jane Smith"}}],
                    }
                ]
            }
        )

    m = openalex_title_lookup(mock_client(handler), title, "Smith", 2019, "a@b.c", 0.9)
    assert m and m.doi == "10.1000/oa" and m.source == "openalex"


def test_semanticscholar_title_lookup():
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        return _json(
            {
                "data": [
                    {
                        "title": title,
                        "year": 2019,
                        "externalIds": {"DOI": "10.1000/ss"},
                        "authors": [{"name": "Jane Smith"}],
                    }
                ]
            }
        )

    m = semanticscholar_title_lookup(mock_client(handler), title, "Smith", 2019, 0.9)
    assert m and m.doi == "10.1000/ss"


def test_enrich_identifiers_crossref_then_openalex_fallback():
    title = "A sufficiently long test title about marine governance"
    calls = []

    def handler(req):
        host = req.url.host or ""
        calls.append(host)
        if "crossref.org" in host:
            return _json({"message": {"items": []}})
        if "openalex.org" in host:
            return _json(
                {
                    "results": [
                        {
                            "doi": "https://doi.org/10.1000/fallback",
                            "display_name": title,
                            "publication_year": 2019,
                            "authorships": [],
                        }
                    ]
                }
            )
        return httpx.Response(404)

    item = make_item(doi=None, url=None, title=title)
    notes = enrich_identifiers(mock_client(handler), item, email="a@b.c", min_score=0.9)
    assert item.doi == "10.1000/fallback" and item.doi_source == "openalex"
    assert "crossref:no-match" in notes
    assert any(n.startswith("openalex:matched") for n in notes)


def test_enrich_skips_webpages():
    item = make_item(doi=None, item_type="webpage", url="https://news.example/a")
    notes = enrich_identifiers(mock_client(lambda r: httpx.Response(500)), item)
    assert notes == [] and item.doi is None


def test_enrich_url_doi_short_circuits():
    item = make_item(doi=None, url="https://doi.org/10.1000/from-url")
    notes = enrich_identifiers(mock_client(lambda r: httpx.Response(500)), item)
    assert item.doi == "10.1000/from-url" and notes == ["url:matched"]


def test_enrich_semanticscholar_after_openalex_miss():
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        host = req.url.host or ""
        if "crossref.org" in host:
            return _json({"message": {"items": []}})
        if "openalex.org" in host:
            return _json({"results": []})
        if "semanticscholar.org" in host:
            return _json(
                {
                    "data": [
                        {
                            "title": title,
                            "year": 2019,
                            "externalIds": {"DOI": "10.1000/ss-fallback"},
                            "authors": [{"name": "Jane Smith"}],
                        }
                    ]
                }
            )
        return httpx.Response(404)

    item = make_item(doi=None, url=None, title=title)
    notes = enrich_identifiers(mock_client(handler), item, email="a@b.c", min_score=0.9)
    assert item.doi == "10.1000/ss-fallback" and item.doi_source == "semanticscholar"
    assert "openalex:no-match" in notes
    assert any(n.startswith("semanticscholar:matched") for n in notes)


def test_enrich_aggregator_meta_then_title_fallback():
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        host = req.url.host or ""
        if "consensus.app" in host:
            return httpx.Response(
                200,
                text="<html><head></head><body>no doi meta</body></html>",
                headers={"content-type": "text/html"},
            )
        if "crossref.org" in host:
            return _json(
                {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1000/from-cr",
                                "title": [title],
                                "issued": {"date-parts": [[2019]]},
                            }
                        ]
                    }
                }
            )
        return httpx.Response(404)

    item = make_item(doi=None, url="https://consensus.app/papers/xyz", title=title)
    notes = enrich_identifiers(mock_client(handler), item, email="a@b.c", min_score=0.9)
    assert "meta:no-doi" in notes
    assert item.doi == "10.1000/from-cr"
