from scihub_dl.resolve import extract_arxiv_id, extract_doi, normalize_doi, title_similarity


def test_normalize_doi_strips_prefixes_and_case():
    assert normalize_doi("https://doi.org/10.1016/J.MARPOL.2017.05.011") == "10.1016/j.marpol.2017.05.011"
    assert normalize_doi("doi:10.1080/00908320.2025.2563269") == "10.1080/00908320.2025.2563269"
    assert normalize_doi("10.1163/15718085-20261025.") == "10.1163/15718085-20261025"


def test_normalize_doi_strips_publisher_suffixes():
    assert normalize_doi("https://onlinelibrary.wiley.com/doi/10.1111/reel.12345/full") == "10.1111/reel.12345"


def test_normalize_doi_rejects_non_doi():
    assert normalize_doi("") is None
    assert normalize_doi("not a doi") is None
    assert normalize_doi(None) is None


def test_extract_doi_from_extra_field():
    extra = "Publisher: Elsevier\nDOI: 10.1016/j.marpol.2023.105571\nCitation Key: foo2023"
    assert extract_doi(extra) == "10.1016/j.marpol.2023.105571"


def test_extract_doi_from_url():
    assert extract_doi("https://www.frontiersin.org/articles/10.3389/fmars.2024.1234567/full") == "10.3389/fmars.2024.1234567"
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
    from scihub_dl.resolve import short_title

    assert short_title("A rights revolution for nature. Introduction of legal rights for nature could protect") == (
        "A rights revolution for nature"
    )
    assert short_title("Vulnerability to impacts of climate change: a review") == "Vulnerability to impacts of climate change"
    assert short_title("Short one. Rest") is None  # head too short to be a title
    assert short_title("Dr. Smith and the long title with no subtitle") is None  # 'Dr.' not a sentence end (uppercase before dot)


def test_normalize_doi_keeps_parentheses_inside_old_elsevier_dois():
    assert normalize_doi("10.1016/0031-9384(69)90073-0") == "10.1016/0031-9384(69)90073-0"
    assert normalize_doi("https://doi.org/10.1016/S0140-6736(97)11096-0.") == "10.1016/s0140-6736(97)11096-0"
    # a closing paren that merely wraps the DOI in prose is dropped
    assert extract_doi("see (doi:10.1000/abc123) for details") == "10.1000/abc123"
    assert extract_doi("(https://doi.org/10.1016/0031-9384(69)90073-0)") == "10.1016/0031-9384(69)90073-0"
