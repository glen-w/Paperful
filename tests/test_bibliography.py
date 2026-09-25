"""Unit tests for empty-remote bibliography recovery helpers."""

from __future__ import annotations

from paperful.snowball.bibliography import (
    dehyphenate,
    open_pdf_url,
    parse_bibliography_entries,
    recover_referenced_works,
)
from paperful.snowball.openalex import OpenAlexClient


def test_dehyphenate_and_parse_numbered_entries():
    text = """
Intro.

References
[1] Ada. (2019). First paper title. Journal.
https://doi.org/10.1000/a
[2] Bea. (2020). Second paper ti-
tle split. Journal.
"""
    assert "title split" in dehyphenate(text)
    entries = parse_bibliography_entries(text)
    assert len(entries) == 2
    assert entries[0]["doi"] == "10.1000/a"
    assert entries[0]["title"] == "First paper title"
    assert entries[0]["year"] == 2019
    assert entries[1]["title"] == "Second paper title split"
    assert entries[1]["year"] == 2020


def test_open_pdf_url_prefers_oa_pdf():
    work = {
        "open_access": {"oa_url": "https://example.test/a.pdf"},
        "primary_location": {"pdf_url": "https://example.test/other.pdf"},
    }
    assert open_pdf_url(work) == "https://example.test/a.pdf"
    assert open_pdf_url({"open_access": {"oa_url": "https://example.test/landing"}}) == (
        "https://example.test/landing"
    )
    assert open_pdf_url({}) == ""


def test_recover_skips_when_openalex_refs_present():
    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=lambda p, q: {})
    called: list[str] = []
    client.s2_getter = lambda doi: called.append(doi) or {}
    client.pdf_fetcher = lambda url: called.append(url) or ""
    work = {
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1000/seed",
        "referenced_works": ["https://openalex.org/W2"],
        "open_access": {"oa_url": "https://example.test/a.pdf"},
    }
    assert recover_referenced_works(client, work) == []
    assert called == []


def test_title_match_requires_clear_lead():
    hits = [
        {
            "id": "https://openalex.org/WA",
            "display_name": "Marine governance in the high seas",
            "publication_year": 2020,
            "cited_by_count": 1,
        },
        {
            "id": "https://openalex.org/WB",
            "display_name": "Marine governance on the high seas",
            "publication_year": 2020,
            "cited_by_count": 2,
        },
    ]

    def getter(path: str, params: dict) -> dict:
        if "search" in params:
            return {"results": hits, "meta": {"count": 2}}
        return {}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    from paperful.snowball import bibliography as bib

    assert bib._match_title(client, "Marine governance in the high seas", 2020) is None
