"""Unit tests for empty-remote bibliography recovery helpers."""

from __future__ import annotations

import pytest

from paperful.snowball import bibliography as bib
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
    assert bib._match_title(client, "Marine governance in the high seas", 2020) is None


# ---- parse_bibliography_entries -------------------------------------------------


def test_last_references_heading_wins_over_an_earlier_mention():
    text = (
        "References\n"
        "See the appendix.\n\n"
        "Body text.\n"
        "References\n"
        "[1] Ada. (2019). Kept title. Journal.\n"
        "[2] Bea. (2020). Also kept. Journal.\n"
    )
    titles = [e["title"] for e in parse_bibliography_entries(text)]
    assert titles == ["Kept title", "Also kept"]


def test_footnote_numbering_is_used_when_brackets_are_absent():
    text = (
        "Notes\n"
        "1. Ada. (2018). Footnote one. Journal.\n"
        "2. Bea. (2019). Footnote two. Journal.\n"
        "3. Cy. (2020). Footnote three. https://doi.org/10.1000/C\n"
    )
    entries = parse_bibliography_entries(text)
    assert [e["year"] for e in entries] == [2018, 2019, 2020]
    assert entries[2]["doi"] == "10.1000/c"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "No heading here at all. (2019). A title.",
        "References\n",
    ],
)
def test_no_usable_section_returns_nothing(text):
    assert parse_bibliography_entries(text) == []


def test_entries_without_doi_or_title_are_dropped():
    text = "References\n[1] just some words\n[2] Bea. (2020). Real title. Journal.\n"
    assert [e["title"] for e in parse_bibliography_entries(text)] == ["Real title"]


def test_unsplit_body_falls_back_to_a_single_entry():
    text = "Bibliography\nAda. (2021). Only one reference here. Marine Policy 3."
    entries = parse_bibliography_entries(text)
    assert len(entries) == 1
    assert entries[0]["title"] == "Only one reference here"
    assert entries[0]["year"] == 2021


def test_trailing_venue_crumb_is_trimmed_from_title():
    entry = bib._parse_entry("Ada. (2022). High seas governance. Marine Policy 12, 1-9.")
    assert entry["title"] == "High seas governance"


# ---- landing HTML -------------------------------------------------------------


def test_landing_prefers_the_doi_rich_section_and_dedupes():
    html = """
    <div class="sidebar"><h2>Notes</h2><p>nothing here</p></div>
    <section id="references">
      <h2>References</h2>
      <ol>
        <li>Ada (2019). <a href="https://doi.org/10.1000/A">link</a></li>
        <li>Bea (2020). <a href="https://doi.org/10.1000/a">dup</a></li>
        <li>Cy (2021). <a href="https://doi.org/10.1000/b">link</a></li>
      </ol>
    </section>
    """
    rows = bib.parse_landing_bibliography(html)
    assert [r["doi"] for r in rows] == ["10.1000/a", "10.1000/b"]


def test_landing_list_keeps_a_reference_that_has_no_doi():
    html = """
    <section id="references"><h2>References</h2><ol>
      <li>Ada Smith (2019). Ocean governance after BBNJ. Marine Policy.
          <a href="https://doi.org/10.1000/a">https://doi.org/10.1000/a</a></li>
      <li>Bea Jones (2020). Title with no DOI here. Ocean Yearbook.</li>
      <li>Cy Park (2021). Linked only by href. Frontiers.
          <a href="https://doi.org/10.1000/c">Crossref</a></li>
    </ol></section>
    """
    rows = bib.parse_landing_bibliography(html)
    assert [r["doi"] for r in rows if r["doi"]] == ["10.1000/a", "10.1000/c"]
    title_only = [r for r in rows if not r["doi"]]
    assert [(r["title"], r["year"]) for r in title_only] == [("Title with no DOI here", 2020)]


def test_landing_caps_the_doi_list():
    links = "".join(
        f'<li><a href="https://doi.org/10.1000/{i}">x</a></li>'
        for i in range(bib.LANDING_DOI_CAP + 25)
    )
    html = f'<section id="references"><h2>References</h2><ol>{links}</ol></section>'
    assert len(bib.parse_landing_bibliography(html)) == bib.LANDING_DOI_CAP


def test_landing_without_a_section_parses_page_text():
    html = "<p>References</p><p>[1] Ada. (2019). Plain page title. Journal.</p><p>[2] Bea. (2020). Second. Journal.</p>"
    titles = [r["title"] for r in bib.parse_landing_bibliography(html)]
    assert "Plain page title" in titles


def test_landing_empty_html():
    assert bib.parse_landing_bibliography("") == []


# ---- URL helpers --------------------------------------------------------------


@pytest.mark.parametrize(
    "work, expected",
    [
        (
            {"primary_location": {"landing_page_url": "https://pub.test/a"}, "doi": "https://doi.org/10.1000/x"},
            "https://pub.test/a",
        ),
        ({"primary_location": {"landing_page_url": "ftp://nope"}, "doi": "10.1000/X"}, "https://doi.org/10.1000/x"),
        ({"ids": {"doi": "https://doi.org/10.1000/y"}}, "https://doi.org/10.1000/y"),
        ({}, ""),
    ],
)
def test_landing_url(work, expected):
    assert bib.landing_url(work) == expected


def test_open_pdf_url_uses_primary_pdf_when_oa_url_is_not_a_pdf():
    work = {
        "open_access": {"oa_url": "https://repo.test/landing"},
        "primary_location": {"pdf_url": "https://repo.test/file/pdf/9"},
    }
    assert open_pdf_url(work) == "https://repo.test/file/pdf/9"


# ---- OpenAlex resolution ------------------------------------------------------


def _search_client(hits, *, fail: bool = False):
    def getter(path, params):
        if fail:
            raise RuntimeError("down")
        return {"results": hits, "meta": {"count": len(hits)}}

    return OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)


def _hit(oa, title, year=2020):
    return {"id": f"https://openalex.org/{oa}", "display_name": title, "publication_year": year}


def test_title_match_accepts_a_single_clear_hit():
    client = _search_client([_hit("W1", "Deep sea mining and the common heritage")])
    got = bib._match_title(client, "Deep sea mining and the common heritage", 2020)
    assert got["id"].endswith("W1")


@pytest.mark.parametrize(
    "hits, title, year",
    [
        ([_hit("W1", "Deep sea mining and the common heritage")], "short", 2020),
        ([_hit("W1", "Deep sea mining and the common heritage", 2011)], "Deep sea mining and the common heritage", 2020),
        ([_hit("W1", "Something else entirely about fisheries")], "Deep sea mining and the common heritage", 2020),
    ],
    ids=["too-short", "year-mismatch", "low-similarity"],
)
def test_title_match_rejects(hits, title, year):
    assert bib._match_title(_search_client(hits), title, year) is None


def test_title_match_swallows_search_errors():
    assert bib._match_title(_search_client([], fail=True), "Deep sea mining and the common heritage", None) is None


def test_resolve_dois_dedupes_skips_failures_and_tags_source():
    works = {
        "10.1/a": {"id": "https://openalex.org/W1"},
        "10.1/a-alias": {"id": "https://openalex.org/W1"},
        "10.1/b": {"id": "https://openalex.org/W2"},
    }

    def getter(path, params):
        doi = path.split("/works/https://doi.org/", 1)[1]
        if doi == "10.1/boom":
            raise RuntimeError("bad")
        return works.get(doi, {})

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    out = bib._resolve_dois(client, ["10.1/a", "10.1/boom", "10.1/a-alias", "10.1/missing", "10.1/b"], source="landing")
    assert [w["id"].rsplit("/", 1)[1] for w in out] == ["W1", "W2"]
    assert {w["_recovery"] for w in out} == {"landing"}
