"""Book-chapter container titles and landing HTML bibliography recovery."""

from __future__ import annotations

from paperful.resolve import WorkMeta, container_titles_for_type, work_by_doi
from paperful.snowball.bibliography import (
    landing_url,
    parse_bibliography_entries,
    parse_landing_bibliography,
    recover_referenced_works,
)
from paperful.snowball.ingest import create_new
from paperful.snowball.openalex import OpenAlexClient
from tests.conftest import make_item, mock_client


def _json(payload: dict):
    import httpx

    return httpx.Response(200, json=payload)


def test_container_titles_book_chapter_prefers_book_over_series():
    venue, book, series = container_titles_for_type(
        "book-chapter",
        [
            "The Palgrave Macmillan Animal Ethics Series",
            "Animals in EU Economic Law",
        ],
    )
    assert venue == "Animals in EU Economic Law"
    assert book == "Animals in EU Economic Law"
    assert series == "The Palgrave Macmillan Animal Ethics Series"


def test_container_titles_journal_uses_first():
    venue, book, series = container_titles_for_type(
        "journal-article", ["Marine Policy"]
    )
    assert venue == "Marine Policy"
    assert book is None
    assert series is None


def test_work_by_doi_book_chapter_fields():
    title = "Protecting Marine Life: Legal Gaps and Policy Contradictions"

    def handler(req):
        if "crossref.org" in (req.url.host or ""):
            return _json(
                {
                    "message": {
                        "DOI": "10.1007/978-3-032-16171-0_4",
                        "type": "book-chapter",
                        "title": [title],
                        "page": "71-99",
                        "issued": {"date-parts": [[2026, 6, 1]]},
                        "container-title": [
                            "The Palgrave Macmillan Animal Ethics Series",
                            "Animals in EU Economic Law",
                        ],
                        "author": [{"given": "Denys-Sacha", "family": "Robin"}],
                    }
                }
            )
        return _json({})

    work = work_by_doi(mock_client(handler), "10.1007/978-3-032-16171-0_4", "a@b.c")
    assert isinstance(work, WorkMeta)
    assert work.work_type == "book-chapter"
    assert work.venue == "Animals in EU Economic Law"
    assert work.book_title == "Animals in EU Economic Law"
    assert work.series_title == "The Palgrave Macmillan Animal Ethics Series"
    assert work.pages == "71-99"
    assert work.first_author == "Robin"


def test_parse_notes_footnote_entries():
    text = """
Abstract text.

Notes
1. See the regulation. Kroodsma. (2018). Tracking the Global Footprint. Science.
https://doi.org/10.1126/science.aao5646
2. FAO. (2022). The State of World Fisheries. https://doi.org/10.4060/cc0461en
"""
    entries = parse_bibliography_entries(text)
    assert len(entries) >= 2
    dois = {e["doi"] for e in entries if e.get("doi")}
    assert "10.1126/science.aao5646" in dois
    assert "10.4060/cc0461en" in dois


SPRINGER_NOTES_HTML = """
<html><body>
<h1>Protecting Marine Life</h1>
<section data-title="Notes">
<ol>
<li>See article 12 of the Order.</li>
<li>Kroodsma et al. 2018. Tracking the Global Footprint of Fisheries.
<a href="https://doi.org/10.1126/science.aao5646">https://doi.org/10.1126/science.aao5646</a></li>
<li>FAO. 2022. The State of World Fisheries.
<a href="https://doi.org/10.4060/cc0461en">10.4060/cc0461en</a></li>
</ol>
</section>
</body></html>
"""


def test_parse_landing_bibliography_extracts_dois():
    entries = parse_landing_bibliography(SPRINGER_NOTES_HTML)
    dois = [e["doi"] for e in entries if e.get("doi")]
    assert dois == ["10.1126/science.aao5646", "10.4060/cc0461en"]


def test_parse_landing_from_fixture_file():
    from pathlib import Path

    html = (Path(__file__).parent / "fixtures" / "springer_chapter_notes.html").read_text(
        encoding="utf-8"
    )
    dois = [e["doi"] for e in parse_landing_bibliography(html) if e.get("doi")]
    assert "10.1126/science.aao5646" in dois
    assert "10.4060/cc0461en" in dois
    assert "10.1038/s41467-020-18505-6" in dois


def test_landing_url_prefers_primary_location():
    work = {
        "doi": "https://doi.org/10.1007/978-3-032-16171-0_4",
        "primary_location": {
            "landing_page_url": "https://link.springer.com/chapter/10.1007/978-3-032-16171-0_4"
        },
    }
    assert landing_url(work).endswith("978-3-032-16171-0_4")


def test_recover_from_landing_html():
    resolved: dict[str, dict] = {
        "10.1126/science.aao5646": {
            "id": "https://openalex.org/W100",
            "doi": "https://doi.org/10.1126/science.aao5646",
            "display_name": "Tracking the Global Footprint of Fisheries",
        },
        "10.4060/cc0461en": {
            "id": "https://openalex.org/W200",
            "doi": "https://doi.org/10.4060/cc0461en",
            "display_name": "The State of World Fisheries",
        },
    }

    def getter(path: str, params: dict) -> dict:
        return {}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    client.s2_getter = lambda doi: None
    client.epmc_getter = lambda doi: None
    client.work_by_doi = lambda doi: resolved.get(doi)  # type: ignore[method-assign]
    client.html_fetcher = lambda url: SPRINGER_NOTES_HTML
    client.pdf_fetcher = lambda url: ""

    work = {
        "id": "https://openalex.org/W7167089531",
        "doi": "https://doi.org/10.1007/978-3-032-16171-0_4",
        "referenced_works": [],
        "primary_location": {
            "landing_page_url": "https://link.springer.com/chapter/10.1007/978-3-032-16171-0_4"
        },
        "open_access": {},
    }
    works = recover_referenced_works(client, work)
    assert len(works) == 2
    assert all(w.get("_recovery") == "landing" for w in works)
    assert {w["id"] for w in works} == {
        "https://openalex.org/W100",
        "https://openalex.org/W200",
    }


def test_recover_landing_miss_falls_through_to_pdf():
    pdf_text = """
References
[1] Ada. (2019). First paper title. Journal.
https://doi.org/10.1000/from-pdf
"""
    resolved = {
        "10.1000/from-pdf": {
            "id": "https://openalex.org/WPDF",
            "doi": "https://doi.org/10.1000/from-pdf",
            "display_name": "First paper title",
        }
    }
    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=lambda p, q: {}
    )
    client.s2_getter = lambda doi: None
    client.epmc_getter = lambda doi: None
    client.html_fetcher = lambda url: "<html><body><p>no biblio here</p></body></html>"
    client.pdf_fetcher = lambda url: pdf_text
    client.work_by_doi = lambda doi: resolved.get(doi)  # type: ignore[method-assign]
    work = {
        "doi": "https://doi.org/10.1000/seed",
        "referenced_works": [],
        "open_access": {"oa_url": "https://example.test/a.pdf"},
        "primary_location": {"landing_page_url": "https://example.test/chapter"},
    }
    works = recover_referenced_works(client, work)
    assert len(works) == 1
    assert works[0]["_recovery"] == "pdf"
    assert works[0]["id"] == "https://openalex.org/WPDF"


def test_parse_landing_heading_sibling_notes():
    html = """
    <html><body>
    <h2>Notes</h2>
    <ol>
      <li>One. <a href="https://doi.org/10.1000/a">doi</a></li>
      <li>Two. <a href="https://doi.org/10.1000/b">doi</a></li>
    </ol>
    <h2>Share</h2>
    <p>noise</p>
    </body></html>
    """
    dois = [e["doi"] for e in parse_landing_bibliography(html) if e.get("doi")]
    assert dois == ["10.1000/a", "10.1000/b"]


def test_fill_replaces_series_only_venue_with_book_title():
    from paperful.snowball.candidate import Candidate
    from paperful.snowball.fill import _fill_empty

    row = Candidate(
        run_id="r",
        seed={},
        hop=0,
        direction="refs",
        ids={},
        biblio={
            "title": "Chapter",
            "year": 2026,
            "authors": ["Ada"],
            "venue": "Series X",
            "type": "book-chapter",
            "series_title": "Series X",
        },
        why="",
        status="new",
        provenance={},
        gate="",
    )
    filled = _fill_empty(
        row,
        {
            "book_title": "Book Y",
            "series_title": "Series X",
            "venue": "Book Y",
            "pages": "71-99",
            "type": "book-chapter",
        },
        backend="crossref",
    )
    assert filled >= 1
    assert row.biblio["venue"] == "Book Y"
    assert row.biblio["book_title"] == "Book Y"
    assert row.biblio["pages"] == "71-99"


def test_create_new_journal_keeps_publication_title():
    created: list[dict] = []

    class Backend:
        supports_write = True

        def ensure_collection_path(self, path: str) -> str:
            return "COL1"

        def create_parent(self, payload: dict) -> str:
            created.append(payload)
            return "ITEM1"

        def create_or_update_note(self, *a, **k) -> None:
            return None

    from paperful.snowball.candidate import Candidate

    row = Candidate(
        run_id="r1",
        seed={"type": "doi", "value": "10.1000/x"},
        hop=0,
        direction="refs",
        ids={"doi": "10.1000/x", "openalex": "W1"},
        biblio={
            "title": "A sufficiently long journal article title here",
            "year": 2020,
            "authors": ["Ada Lovelace"],
            "venue": "Marine Policy",
            "type": "journal-article",
        },
        why="seed",
        status="new",
        provenance={"backend": "openalex"},
        gate="open",
    )
    create_new(Backend(), [row], "Inbox", note_provenance=False)
    assert created[0]["itemType"] == "journalArticle"
    assert created[0]["publicationTitle"] == "Marine Policy"
    assert "bookTitle" not in created[0]


def test_create_new_book_section_sets_book_title(monkeypatch):
    created: list[dict] = []

    class Backend:
        supports_write = True

        def ensure_collection_path(self, path: str) -> str:
            return "COL1"

        def create_parent(self, payload: dict) -> str:
            created.append(payload)
            return "ITEM1"

        def create_or_update_note(self, *a, **k) -> None:
            return None

    from paperful.snowball.candidate import Candidate

    row = Candidate(
        run_id="r1",
        seed={"type": "doi", "value": "10.1007/978-3-032-16171-0_4"},
        hop=0,
        direction="refs",
        ids={"doi": "10.1007/978-3-032-16171-0_4", "openalex": "W1"},
        biblio={
            "title": "Protecting Marine Life: Legal Gaps",
            "year": 2026,
            "authors": ["Denys-Sacha Robin"],
            "venue": "Animals in EU Economic Law",
            "type": "book-chapter",
            "book_title": "Animals in EU Economic Law",
            "series_title": "The Palgrave Macmillan Animal Ethics Series",
            "pages": "71-99",
        },
        why="seed",
        status="new",
        provenance={"backend": "openalex"},
        gate="open",
    )
    items, counts = create_new(Backend(), [row], "Inbox", note_provenance=False)
    assert counts["created"] == 1
    assert len(items) == 1
    assert items[0].item_type == "bookSection"
    payload = created[0]
    assert payload["itemType"] == "bookSection"
    assert payload["bookTitle"] == "Animals in EU Economic Law"
    assert payload["seriesTitle"] == "The Palgrave Macmillan Animal Ethics Series"
    assert payload["pages"] == "71-99"
    assert payload.get("publicationTitle") in ("", None)


def test_propose_patch_book_section_fields(cfg, monkeypatch):
    from paperful import metadata as meta
    from paperful.metadata import propose_patch
    from paperful.resolve import WorkMeta

    item = make_item(
        item_type="bookSection",
        doi="10.1007/978-3-032-16171-0_4",
        doi_verified="ok",
        library_doi="10.1007/978-3-032-16171-0_4",
        publication_title=None,
        book_title=None,
        series_title=None,
        pages=None,
    )
    work = WorkMeta(
        doi="10.1007/978-3-032-16171-0_4",
        title=item.title,
        year=2026,
        venue="Animals in EU Economic Law",
        source="crossref",
        work_type="book-chapter",
        book_title="Animals in EU Economic Law",
        series_title="The Palgrave Macmillan Animal Ethics Series",
        pages="71-99",
    )
    monkeypatch.setattr(meta, "work_by_doi", lambda *a, **k: work)
    patch = propose_patch(mock_client(lambda req: _json({})), cfg, item, [], prepared=True)
    assert patch is not None
    assert patch.after["bookTitle"] == "Animals in EU Economic Law"
    assert patch.after["seriesTitle"] == "The Palgrave Macmillan Animal Ethics Series"
    assert patch.after["pages"] == "71-99"
    assert "publicationTitle" not in patch.after
