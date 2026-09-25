import httpx

from paperful.resolve import (
    extract_arxiv_id,
    extract_doi,
    extract_pmid,
    normalize_doi,
    title_similarity,
)


def test_normalize_doi_strips_prefixes_and_case():
    assert (
        normalize_doi("https://doi.org/10.1016/J.MARPOL.2017.05.011")
        == "10.1016/j.marpol.2017.05.011"
    )
    assert (
        normalize_doi("doi:10.1080/00908320.2025.2563269")
        == "10.1080/00908320.2025.2563269"
    )
    assert normalize_doi("10.1163/15718085-20261025.") == "10.1163/15718085-20261025"


def test_normalize_doi_strips_publisher_suffixes():
    assert (
        normalize_doi("https://onlinelibrary.wiley.com/doi/10.1111/reel.12345/full")
        == "10.1111/reel.12345"
    )


def test_normalize_doi_rejects_non_doi():
    assert normalize_doi("") is None
    assert normalize_doi("not a doi") is None
    assert normalize_doi(None) is None


def test_extract_doi_from_extra_field():
    extra = (
        "Publisher: Elsevier\nDOI: 10.1016/j.marpol.2023.105571\nCitation Key: foo2023"
    )
    assert extract_doi(extra) == "10.1016/j.marpol.2023.105571"


def test_extract_pmid_from_extra():
    assert extract_pmid("PMID: 12345678\nDOI: 10.1/x") == "12345678"
    assert extract_pmid("PubMed ID: 99") == "99"
    assert extract_pmid("no pmid here") is None


def test_extract_doi_from_url():
    assert (
        extract_doi(
            "https://www.frontiersin.org/articles/10.3389/fmars.2024.1234567/full"
        )
        == "10.3389/fmars.2024.1234567"
    )
    assert extract_doi("https://example.org/no-doi-here") is None


def test_extract_arxiv_id():
    assert extract_arxiv_id("https://arxiv.org/abs/2301.01234v2") == "2301.01234"
    assert extract_arxiv_id("arXiv: 1706.03762") == "1706.03762"
    assert extract_arxiv_id("https://arxiv.org/abs/hep-th/9901001") == "hep-th/9901001"
    assert extract_arxiv_id("https://doi.org/10.1016/j.marpol.2017.05.011") is None
    assert extract_arxiv_id(None) is None


def test_title_similarity_ignores_case_punctuation_and_accents():
    a = "Vulnerability to impacts of climate change on marine fisheries and food security"
    b = "VULNERABILITY TO IMPACTS OF CLIMATE-CHANGE ON MARINE FISHERIES & FOOD SECURITY"
    assert title_similarity(a, b) > 0.9
    assert title_similarity("Élan vital", "Elan vital") == 1.0
    assert title_similarity("Completely different", a) < 0.5


def test_short_title_splits_on_sentence_or_colon():
    from paperful.resolve import short_title

    assert short_title(
        "A rights revolution for nature. Introduction of legal rights for nature could protect"
    ) == ("A rights revolution for nature")
    assert (
        short_title("Vulnerability to impacts of climate change: a review")
        == "Vulnerability to impacts of climate change"
    )
    assert short_title("Short one. Rest") is None  # head too short to be a title
    assert (
        short_title("Dr. Smith and the long title with no subtitle") is None
    )  # 'Dr.' not a sentence end (uppercase before dot)


def test_crossref_preprint_relations():
    from paperful.resolve import version_from_crossref

    preprint = version_from_crossref(
        {
            "relation": {
                "is-preprint-of": [{"id-type": "doi", "id": "10.1038/s41586-020-2649-2"}]
            }
        },
        "10.1101/2020.01.01.123456",
    )
    assert preprint is not None
    assert preprint.preprint_doi == "10.1101/2020.01.01.123456"
    assert preprint.published_doi == "10.1038/s41586-020-2649-2"
    assert preprint.source == "crossref"

    published = version_from_crossref(
        {
            "type": "journal-article",
            "DOI": "10.1038/s41586-020-2649-2",
            "title": ["Attention is all you need"],
            "container-title": ["Nature"],
            "issued": {"date-parts": [[2020, 6, 1]]},
            "relation": {
                "has-preprint": [{"id-type": "doi", "id": "10.48550/arxiv.1706.03762"}]
            },
        },
        "10.1038/s41586-020-2649-2",
    )
    assert published is not None
    assert published.preprint_doi == "10.48550/arxiv.1706.03762"
    assert published.arxiv_id == "1706.03762"
    assert published.item_type == "journalArticle"
    assert published.published is not None
    assert published.published.venue == "Nature"


def test_arxiv_and_biorxiv_published_doi():
    from paperful.resolve import version_from_arxiv_xml, version_from_biorxiv

    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/1706.03762v5</id>
        <arxiv:doi>10.1038/s41586-020-2649-2</arxiv:doi>
      </entry>
    </feed>
    """
    link = version_from_arxiv_xml(xml, "10.48550/arxiv.1706.03762")
    assert link is not None
    assert link.published_doi == "10.1038/s41586-020-2649-2"
    assert link.arxiv_id == "1706.03762"
    assert link.source == "arxiv"

    journal_only = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/1706.03762v5</id>
        <arxiv:journal_ref>Nature 583, 10.1038/s41586-020-2649-2 (2020)</arxiv:journal_ref>
      </entry>
    </feed>
    """
    via_journal = version_from_arxiv_xml(journal_only, "10.48550/arxiv.1706.03762")
    assert via_journal is not None
    assert via_journal.published_doi == "10.1038/s41586-020-2649-2"

    bio = version_from_biorxiv(
        {
            "collection": [
                {"doi": "10.1101/2020.01.01.123456", "version": "1", "published": "NA"},
                {
                    "doi": "10.1101/2020.01.01.123456",
                    "version": "2",
                    "published": "10.1038/s41586-020-2649-2",
                },
            ]
        },
        "10.1101/2020.01.01.123456",
    )
    assert bio is not None
    assert bio.published_doi == "10.1038/s41586-020-2649-2"
    assert bio.source == "biorxiv"
    assert (
        version_from_biorxiv(
            {"collection": [{"published": "NA"}]}, "10.1101/2020.01.01.123456"
        )
        is None
    )


def test_openalex_related_works_do_not_link():
    from paperful.resolve import version_from_crossref, version_from_openalex, version_link

    payload = {
        "related_works": ["https://openalex.org/W123"],
        "locations": [{"pdf_url": "https://example.org/a.pdf"}],
    }
    assert version_from_openalex(payload) is None
    assert (
        version_from_crossref(
            {"DOI": "10.1000/vor", "related_works": payload["related_works"]},
            "10.1000/vor",
        )
        is None
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.crossref.org" in str(request.url):
            return httpx.Response(200, json={"message": {"DOI": "10.1000/vor"}})
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert version_link(client, "10.1000/vor", "t@example.org") is None


def test_normalize_doi_keeps_parentheses_inside_old_elsevier_dois():
    assert (
        normalize_doi("10.1016/0031-9384(69)90073-0") == "10.1016/0031-9384(69)90073-0"
    )
    assert (
        normalize_doi("https://doi.org/10.1016/S0140-6736(97)11096-0.")
        == "10.1016/s0140-6736(97)11096-0"
    )
    # a closing paren that merely wraps the DOI in prose is dropped
    assert extract_doi("see (doi:10.1000/abc123) for details") == "10.1000/abc123"
    assert (
        extract_doi("(https://doi.org/10.1016/0031-9384(69)90073-0)")
        == "10.1016/0031-9384(69)90073-0"
    )
