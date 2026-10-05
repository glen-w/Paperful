"""The mirror reader: the same ``Item`` a live listing gives, and PDFs found on disk."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from paperful.config import Config
from paperful.lint import resolve_pdf_path
from paperful.mirror import (
    MirrorIndex,
    forget_index,
    item_from_record,
    items_in_mirror,
    iter_item_dirs,
    load_record,
    pdf_for,
    record_pdf,
    update_record,
)
from paperful.snapshot import attachment_rows, record_from_raw
from paperful.store import Manifest, Record, item_dirname, record_path, write_json
from paperful.zot import Collection, Item, item_from_json

COLS = {
    "COL1": Collection(key="COL1", name="BBNJ", parent=None, path="BBNJ"),
    "COL2": Collection(key="COL2", name="EIA", parent="COL1", path="BBNJ/EIA"),
}

RAW_ITEMS = [
    {
        "key": "ARTICLE1",
        "version": 7,
        "meta": {"parsedDate": "2021-03-04"},
        "data": {
            "itemType": "journalArticle",
            "title": "Area-based management beyond national jurisdiction",
            "creators": [
                {"creatorType": "editor", "firstName": "E", "lastName": "Editor"},
                {"creatorType": "author", "firstName": "A", "lastName": "Smith"},
                {"creatorType": "author", "name": "UNESCO"},
            ],
            "abstractNote": "An abstract.",
            "date": "4 March 2021",
            "DOI": "10.1000/ABC.1",
            "url": "https://example.org/a",
            "extra": "PMID: 12345",
            "publicationTitle": "Marine Policy",
            "pages": "1-9",
            "volume": "12",
            "tags": [{"tag": "bbnj"}],
            "collections": ["COL1", "COL2"],
            "dateAdded": "2024-01-01T00:00:00Z",
            "dateModified": "2024-06-01T00:00:00Z",
        },
    },
    {
        "key": "CHAPTER1",
        "version": 3,
        "meta": {},
        "data": {
            "itemType": "bookSection",
            "title": "A chapter",
            "creators": [{"creatorType": "author", "lastName": "Jones"}],
            "date": "2019",
            "bookTitle": "The Book",
            "seriesTitle": "The Series",
            "extra": "DOI: 10.2000/chap",
            "collections": [],
            "dateAdded": "2023-05-05T00:00:00Z",
        },
    },
    {
        "key": "PREPRNT1",
        "version": 1,
        "meta": {},
        "data": {
            "itemType": "preprint",
            "title": "",
            "creators": [],
            "url": "https://arxiv.org/abs/2101.00001",
            "collections": ["COL2"],
        },
    },
]

PDF_CHILD = {
    "key": "ATTACH01",
    "data": {
        "itemType": "attachment",
        "linkMode": "imported_file",
        "contentType": "application/pdf",
        "filename": "x.pdf",
        "md5": "abc",
    },
}
LINK_CHILD = {
    "key": "ATTACH02",
    "data": {
        "itemType": "attachment",
        "linkMode": "linked_url",
        "contentType": "application/pdf",
        "title": "Full Text",
    },
}


@pytest.fixture(autouse=True)
def _fresh_index():
    forget_index()
    yield
    forget_index()


def _snapshot(out: Path, raw: dict, children: list[dict]) -> tuple[Item, Path]:
    """Write a record the way ``snapshot`` does and return the live Item."""
    has_pdf = any(c is PDF_CHILD for c in children)
    linked = any(c is LINK_CHILD for c in children)
    live = item_from_json(
        raw,
        COLS,
        None,
        has_pdf=has_pdf,
        has_linked_url=linked,
        pdf_tier="native" if has_pdf else "",
    )
    rec = record_from_raw(raw, live, COLS)
    rec["attachments"] = attachment_rows(children)
    folder = out / live.collection_paths[0] / item_dirname(live)
    write_json(record_path(folder), rec)
    return live, folder


@pytest.mark.parametrize("raw", RAW_ITEMS, ids=[r["key"] for r in RAW_ITEMS])
@pytest.mark.parametrize(
    "children", [[], [PDF_CHILD], [LINK_CHILD], [PDF_CHILD, LINK_CHILD]]
)
def test_item_from_record_matches_the_live_listing(tmp_path, raw, children):
    out = tmp_path / "out"
    live, folder = _snapshot(out, raw, children)
    rec = json.loads(record_path(folder).read_text())
    mirrored = item_from_record(rec, folder, out)
    assert mirrored is not None
    assert asdict(mirrored) == asdict(live)


def test_selected_collections_limit_paths_like_a_scoped_listing(tmp_path):
    out = tmp_path / "out"
    raw = RAW_ITEMS[0]
    _live, folder = _snapshot(out, raw, [])
    rec = json.loads(record_path(folder).read_text())
    scoped = item_from_json(raw, COLS, {"COL2"})
    mirrored = item_from_record(rec, folder, out, selected={"COL2"})
    assert mirrored.collection_paths == scoped.collection_paths == ["BBNJ/EIA"]
    outside = item_from_record(rec, folder, out, selected={"OTHER"})
    assert outside.collection_paths == item_from_json(raw, COLS, {"OTHER"}).collection_paths


def test_folder_pdf_counts_when_the_record_has_no_attachment_rows(tmp_path):
    out = tmp_path / "out"
    _live, folder = _snapshot(out, RAW_ITEMS[1], [])
    (folder / "Jones - 2019 - A chapter.pdf").write_bytes(b"%PDF-1.4")
    (item,) = items_in_mirror(out)
    assert item.has_pdf is True
    assert item.pdf_path == str(folder / "Jones - 2019 - A chapter.pdf")


def test_iter_item_dirs_does_not_descend_into_item_folders(tmp_path):
    out = tmp_path / "out"
    folder = out / "A" / "Smith - 2020 - Paper -- KEY00001"
    nested = folder / "notes" / "Odd - 2020 - Nested -- KEY00002"
    nested.mkdir(parents=True)
    assert list(iter_item_dirs(out)) == [folder]
    assert list(iter_item_dirs(tmp_path / "missing")) == []


def test_index_finds_every_folder_for_a_key_and_updates_them_all(tmp_path):
    out = tmp_path / "out"
    for collection in ("A", "B"):
        folder = out / collection / "Smith - 2020 - Paper -- KEY00001"
        write_json(record_path(folder), {"item_key": "KEY00001", "title": "Old"})
    index = MirrorIndex.scan(out)
    assert len(index.dirs("KEY00001")) == 2
    assert index.keys() == ["KEY00001"]
    assert load_record(out, "KEY00001")["title"] == "Old"
    assert update_record(out, "KEY00001", lambda rec: rec.update(title="New")) == 2
    for collection in ("A", "B"):
        rec = json.loads(
            record_path(out / collection / "Smith - 2020 - Paper -- KEY00001").read_text()
        )
        assert rec["title"] == "New"
    assert load_record(out, "MISSING1") is None
    assert update_record(out, "MISSING1", lambda rec: None) == 0


def test_record_pdf_prefers_the_fetched_file(tmp_path):
    folder = tmp_path / "Smith - 2020 - Paper -- KEY00001"
    folder.mkdir()
    (folder / "a-export.pdf").write_bytes(b"%PDF-1.4 a")
    (folder / "z-fetched.pdf").write_bytes(b"%PDF-1.4 z")
    assert record_pdf(folder, {"fetch": {"pdf": "z-fetched.pdf"}}).name == "z-fetched.pdf"
    assert record_pdf(folder, {"fetch": {"pdf": "gone.pdf"}}).name == "a-export.pdf"
    assert record_pdf(folder, None).name == "a-export.pdf"


def _api_item(**overrides) -> Item:
    base = dict(
        key="KEY00001",
        item_type="journalArticle",
        title="Paper",
        doi=None,
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Smith",
        collection_paths=["A"],
        has_pdf=True,
    )
    base.update(overrides)
    return Item(**base)


def test_pdf_for_finds_a_mirror_pdf_the_manifest_never_recorded(tmp_path):
    """A PDF that ``snapshot --pdfs all`` exported must not be exported again."""
    out = tmp_path / "out"
    item = _api_item()
    folder = out / "A" / item_dirname(item)
    write_json(record_path(folder), {"item_key": item.key})
    pdf = folder / "Smith - 2020 - Paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert pdf_for(out, item, None) == pdf
    cfg = Config(out_dir=out, state_dir=tmp_path / "state")
    assert resolve_pdf_path(cfg, item, Manifest(tmp_path / "state" / "manifest.jsonl")) == pdf


def test_pdf_for_survives_a_retitled_item(tmp_path):
    out = tmp_path / "out"
    old = _api_item(title="Old title")
    folder = out / "A" / item_dirname(old)
    write_json(record_path(folder), {"item_key": old.key})
    pdf = folder / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert pdf_for(out, _api_item(title="New title"), None) == pdf


def test_pdf_for_order_and_misses(tmp_path):
    out = tmp_path / "out"
    item = _api_item()
    assert pdf_for(out, item, None) is None
    manifest = Manifest(tmp_path / "state" / "manifest.jsonl")
    fetched = out / "elsewhere.pdf"
    fetched.parent.mkdir(parents=True)
    fetched.write_bytes(b"%PDF-1.4")
    manifest.write(Record(itemKey=item.key, status="ok", path=str(fetched)))
    assert pdf_for(out, item, manifest) == fetched
    direct = tmp_path / "direct.pdf"
    direct.write_bytes(b"%PDF-1.4")
    item.pdf_path = str(direct)
    assert pdf_for(out, item, manifest) == direct


def test_folding_a_folder_into_itself_deletes_nothing(tmp_path):
    from paperful.mirror import fold_folder

    folder = tmp_path / "Smith - 2020 - Paper -- KEY00001"
    folder.mkdir()
    (folder / "paper.pdf").write_bytes(b"%PDF-1.4")
    (folder / "record.json").write_text("{}")
    fold_folder(folder, folder)
    assert (folder / "paper.pdf").is_file() and (folder / "record.json").is_file()


def test_a_title_that_only_changes_case_keeps_its_pdf(tmp_path):
    """On macOS the old and new folder names are one folder. It must not be folded into itself."""
    from paperful.mirror import place_item_dirs

    out = tmp_path / "out"
    loud = _api_item(title="ANALYSIS OF EMOTIONAL STABILITY")
    (folder,) = place_item_dirs(out, loud, exact=True)
    (folder / "paper.pdf").write_bytes(b"%PDF-1.4")
    forget_index()
    quiet = _api_item(title="Analysis of Emotional Stability")
    (renamed,) = place_item_dirs(out, quiet, exact=True)
    assert (renamed / "paper.pdf").read_bytes() == b"%PDF-1.4"
    names = [p.name for p in (out / "A").iterdir()]
    assert names == [renamed.name]
    # And again, with the index already loaded.
    (again,) = place_item_dirs(out, quiet, exact=True)
    assert (again / "paper.pdf").is_file()
