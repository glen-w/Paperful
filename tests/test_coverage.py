"""Collection coverage: briefing / file mentions vs -C."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.coverage import (
    COVERAGE_PACK_KEYS,
    SCHEMA,
    classify_mentions,
    dois_from_coverage_pack,
    extract_mentions,
    write_pack,
)
from paperful.identity import LibraryFingerprint
from paperful.ingest_dois import dois_from_refs_pack
from tests.conftest import make_item

MARKDOWN = """
# Briefing

- 2019 — Alpha paper — `10.1000/alpha`
- 2020 — Beta paper — `10.1000/beta`

Also see https://doi.org/10.1000/gamma

10.1000/delta
"""


def test_extract_mentions_from_markdown():
    mentions = extract_mentions(MARKDOWN)
    dois = [m.doi for m in mentions]
    assert "10.1000/alpha" in dois
    assert "10.1000/beta" in dois
    assert "10.1000/gamma" in dois
    assert "10.1000/delta" in dois
    alpha = next(m for m in mentions if m.doi == "10.1000/alpha")
    assert "Alpha" in alpha.title
    assert alpha.year == 2019


def test_extract_mentions_from_html():
    html = "<p>See <a href='https://doi.org/10.1000/html'>x</a></p>"
    mentions = extract_mentions(html)
    assert any(m.doi == "10.1000/html" for m in mentions)


def test_classify_in_collection_missing_ambiguous():
    in_col = make_item(
        key="INCOL",
        doi="10.1000/alpha",
        title="Alpha paper about marine governance",
        year=2019,
        collection_paths=["BBNJ"],
    )
    outside = make_item(
        key="OUT",
        doi="10.1000/beta",
        title="Beta paper about marine governance",
        year=2020,
        collection_paths=["Other"],
    )
    all_items = [in_col, outside]
    col_fp = LibraryFingerprint.from_items(
        all_items, scope="collection", collection="BBNJ"
    )
    lib_fp = LibraryFingerprint.from_items(all_items, scope="library")
    mentions = extract_mentions(MARKDOWN)
    rows = classify_mentions(mentions, col_fp, lib_fp)
    by_doi = {r.doi: r for r in rows}
    assert by_doi["10.1000/alpha"].status == "in_collection"
    assert by_doi["10.1000/alpha"].item_key == "INCOL"
    assert by_doi["10.1000/beta"].status == "ambiguous"
    assert by_doi["10.1000/beta"].finding == "in_library_outside_collection"
    assert by_doi["10.1000/gamma"].status == "missing"
    assert by_doi["10.1000/gamma"].suggested_action == "ingest-dois"


def test_write_pack_and_dois(tmp_path: Path):
    mentions = extract_mentions("10.1000/missing\n")
    empty = LibraryFingerprint.from_items([])
    rows = classify_mentions(mentions, empty, empty)
    folder = write_pack(
        tmp_path, "BBNJ", rows, {"kind": "file", "ref": "list.txt"}
    )
    pack = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    assert pack["schema"] == SCHEMA
    assert COVERAGE_PACK_KEYS <= pack.keys()
    assert (folder / "dois.txt").read_text(encoding="utf-8").strip() == "10.1000/missing"
    assert dois_from_coverage_pack(folder / "pack.json") == ["10.1000/missing"]
    assert dois_from_refs_pack(folder / "pack.json") == ["10.1000/missing"]
