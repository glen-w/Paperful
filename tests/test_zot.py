from paperful.zot import UNCOLLECTED, build_collection_tree, is_pdf_attachment, item_from_json, parse_year


def _col(key, name, parent=None):
    return {"data": {"key": key, "name": name, "parentCollection": parent or False}}


def test_build_collection_tree_paths():
    cols = build_collection_tree([_col("A", "BBNJ"), _col("B", "not undermine", "A"), _col("C", "deep/nested: x", "B")])
    assert cols["B"].path == "BBNJ/not undermine"
    assert cols["C"].path == "BBNJ/not undermine/deep_nested_ x"
    assert cols["A"].parent is None and cols["B"].parent == "A"


def test_is_pdf_attachment():
    assert is_pdf_attachment({"contentType": "application/pdf", "linkMode": "imported_file"})
    assert is_pdf_attachment({"contentType": "application/pdf", "linkMode": "linked_file"})
    assert not is_pdf_attachment({"contentType": "application/pdf", "linkMode": "linked_url"})
    assert not is_pdf_attachment({"contentType": "text/html", "linkMode": "imported_url"})


def test_item_from_json_extracts_identifiers_and_paths():
    cols = build_collection_tree([_col("A", "BBNJ"), _col("B", "AO")])
    raw = {
        "key": "ITEM1",
        "meta": {"parsedDate": "2024-03-01"},
        "data": {
            "itemType": "journalArticle",
            "title": "  Some title  ",
            "DOI": "https://doi.org/10.1000/ABC",
            "url": "https://arxiv.org/abs/2401.00001",
            "creators": [{"creatorType": "editor", "lastName": "Ed"}, {"creatorType": "author", "lastName": "Wright"}],
            "collections": ["A", "B", "ZZZ"],
        },
    }
    item = item_from_json(raw, cols, selected={"A"})
    assert item.doi == "10.1000/abc" and item.doi_source == "field"
    assert item.arxiv_id == "2401.00001"
    assert item.year == 2024
    assert item.first_author == "Wright"
    assert item.title == "Some title"
    assert item.collection_paths == ["BBNJ"]

    item_all = item_from_json(raw, cols, selected=None)
    assert item_all.collection_paths == ["AO", "BBNJ"]


def test_item_from_json_doi_fallbacks():
    cols = {}
    raw = {"key": "K", "meta": {}, "data": {"itemType": "report", "title": "T", "extra": "DOI: 10.5555/xyz", "collections": []}}
    item = item_from_json(raw, cols, None)
    assert item.doi == "10.5555/xyz" and item.doi_source == "extra"
    assert item.collection_paths == [UNCOLLECTED]
    raw["data"].pop("extra")
    raw["data"]["url"] = "https://doi.org/10.6666/uvw"
    assert item_from_json(raw, cols, None).doi_source == "url"
    raw["data"].pop("url")
    assert item_from_json(raw, cols, None).doi_source == "none"


def test_parse_year():
    assert parse_year("2019-05-01") == 2019
    assert parse_year("May 3, 1998") == 1998
    assert parse_year("n.d.") is None


def test_collection_raw_path_and_squash_matching():
    from paperful.zot import _squash

    cols = build_collection_tree([_col("A", "BBNJ"), _col("B", "EIA / SEA", "A")])
    assert cols["B"].path == "BBNJ/EIA _ SEA"
    assert cols["B"].raw_path == "BBNJ/EIA / SEA"
    assert _squash("BBNJ/EIA / SEA") == _squash(cols["B"].path) == _squash(cols["B"].raw_path) == "bbnj/eia/sea"
