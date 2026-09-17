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
    return httpx.Response(
        status,
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )


def test_doi_from_url_variants():
    assert doi_from_url("https://doi.org/10.1000/xyz").doi == "10.1000/xyz"
    assert doi_from_url("https://dx.doi.org/10.1000/xyz").doi == "10.1000/xyz"
    assert (
        doi_from_url("https://example.org/paper?doi=10.1000/abc").doi == "10.1000/abc"
    )
    assert (
        doi_from_url("https://consensus.app/papers/10.1000/cons/").doi == "10.1000/cons"
    )
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


def test_work_by_doi_crossref():
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        if "crossref.org" in (req.url.host or ""):
            return _json(
                {
                    "message": {
                        "DOI": "10.1000/test.doi",
                        "title": [title],
                        "issued": {"date-parts": [[2019]]},
                        "container-title": ["Marine Policy"],
                        "author": [{"family": "Smith"}],
                    }
                }
            )
        return httpx.Response(404)

    from paperful.resolve import work_by_doi

    work = work_by_doi(mock_client(handler), "10.1000/test.doi", "a@b.c")
    assert work and work.title == title and work.venue == "Marine Policy"
    assert work.date == "2019"


def test_verify_doi_ok_suspect_unknown():
    from paperful.resolve import verify_doi

    title = "A sufficiently long test title about marine governance"

    def ok_handler(req):
        return _json(
            {
                "message": {
                    "DOI": "10.1000/test.doi",
                    "title": [title],
                    "issued": {"date-parts": [[2019]]},
                }
            }
        )

    item = make_item(title=title)
    assert verify_doi(mock_client(ok_handler), item, email="a@b.c").status == "ok"

    def mismatch(req):
        return _json(
            {
                "message": {
                    "DOI": "10.1000/test.doi",
                    "title": ["Completely unrelated other paper"],
                    "issued": {"date-parts": [[2019]]},
                }
            }
        )

    assert verify_doi(mock_client(mismatch), item, email="a@b.c").status == "suspect"

    def down(req):
        return httpx.Response(500)

    assert verify_doi(mock_client(down), item, email="a@b.c").status == "unknown"


def test_prepare_swaps_suspect_doi():
    from paperful.resolve import prepare_identifiers

    title = "A sufficiently long test title about marine governance"

    def handler(req):
        host = req.url.host or ""
        path = req.url.path
        if "crossref.org" in host and "/works/" in path and not path.endswith("/works"):
            return _json(
                {
                    "message": {
                        "DOI": "10.1/wrong",
                        "title": ["Totally different"],
                        "issued": {"date-parts": [[2010]]},
                    }
                }
            )
        if "crossref.org" in host:
            return _json(
                {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.9/right",
                                "title": [title],
                                "issued": {"date-parts": [[2019]]},
                            }
                        ]
                    }
                }
            )
        return httpx.Response(404)

    item = make_item(doi="10.1/wrong", title=title, url=None)
    notes = prepare_identifiers(
        mock_client(handler), item, email="a@b.c", min_score=0.9, suspect_score=0.7
    )
    assert item.library_doi == "10.1/wrong"
    assert item.doi == "10.9/right"
    assert item.doi_verified == "swapped"
    assert any(n.startswith("swap:") for n in notes)


def test_prepare_unknown_keeps_original_doi():
    from paperful.resolve import prepare_identifiers

    item = make_item(doi="10.1/x", url=None)
    notes = prepare_identifiers(
        mock_client(lambda r: httpx.Response(500)), item, email="a@b.c"
    )
    assert item.doi == "10.1/x"
    assert item.doi_verified == "unknown"
    assert any(n.startswith("verify:unknown") for n in notes)


def test_prepare_skips_verify_when_disabled():
    from paperful.resolve import prepare_identifiers

    item = make_item(doi="10.1/x", url=None)
    notes = prepare_identifiers(
        mock_client(lambda r: httpx.Response(500)), item, email="a@b.c", verify=False
    )
    assert item.doi == "10.1/x"
    assert item.doi_verified == "unknown"
    assert notes == []


def test_pmid_to_doi():
    from paperful.resolve import pmid_to_doi

    def handler(req):
        assert "idconv" in str(req.url)
        return _json({"records": [{"pmid": "1", "doi": "10.1000/from-pmid"}]})

    assert pmid_to_doi(mock_client(handler), "1", "a@b.c") == "10.1000/from-pmid"
