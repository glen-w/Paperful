"""The mirror catalogue: one entry per item across all of its folders."""

from __future__ import annotations

import os

from paperful.store import items_from_mirror, mirror_entries, write_json


def _mirror_dir(out, collection, name, *, record=None, pdf=None):
    folder = out / collection / name if collection else out / name
    folder.mkdir(parents=True)
    if record is not None:
        write_json(folder / "record.json", record)
    if pdf is not None:
        (folder / "paper.pdf").write_bytes(pdf)
    return folder


def _full_record(key="ABCD1234", **over):
    record = {
        "item_key": key,
        "item_type": "journalArticle",
        "version": 7,
        "title": "Deep sea governance",
        "creators": [
            {"creatorType": "author", "lastName": "Silva", "firstName": "A"},
            {"creatorType": "author", "name": "FAO"},
        ],
        "year": 2021,
        "abstract": "An abstract.",
        "collection_paths": ["ocean/BBNJ", "law"],
    }
    record.update(over)
    return record


def test_items_from_mirror_fills_creator_surnames(tmp_path):
    name = "Silva - 2021 - Deep sea governance -- ABCD1234"
    _mirror_dir(tmp_path, "ocean/BBNJ", name, record=_full_record(), pdf=b"%PDF-1.4 a")
    (item,) = items_from_mirror(tmp_path)
    assert item.creator_surnames == ["Silva", "FAO"] and item.creator_count == 2
    assert item.first_author == "Silva" and item.has_pdf and item.year == 2021


def test_mirror_entries_groups_folders_and_takes_the_fullest_record(tmp_path):
    name = "Silva - 2021 - Deep sea governance -- ABCD1234"
    shell = {"item_key": "ABCD1234", "version": None, "title": "Deep sea governance"}
    # Sorted first, holds only a fetch shell; the PDF sits in the second folder.
    _mirror_dir(tmp_path, "law", name, record=shell)
    _mirror_dir(tmp_path, "ocean/BBNJ", name, record=_full_record(), pdf=b"%PDF-1.4 a")
    (entry,) = mirror_entries(tmp_path)
    assert entry.key == "ABCD1234"
    assert entry.dirs == [f"law/{name}", f"ocean/BBNJ/{name}"]
    assert entry.collections == ["law", "ocean/BBNJ"]
    assert entry.record["version"] == 7
    assert [p.parent.parent.name for p in entry.pdfs] == ["BBNJ"]
    item = entry.item()
    assert item.creator_surnames == ["Silva", "FAO"] and item.has_pdf
    assert item.abstract == "An abstract."
    # items_from_mirror stops at the first folder and misses the PDF.
    assert items_from_mirror(tmp_path)[0].has_pdf is False


def test_mirror_entries_counts_a_hardlinked_pdf_once(tmp_path):
    name = "Silva - 2021 - Deep sea governance -- ABCD1234"
    first = _mirror_dir(tmp_path, "law", name, record=_full_record(), pdf=b"%PDF-1.4 a")
    second = _mirror_dir(tmp_path, "ocean", name, record=_full_record())
    os.link(first / "paper.pdf", second / "paper.pdf")
    (entry,) = mirror_entries(tmp_path)
    assert len(entry.pdfs) == 1
    # A re-download in one folder is a different file and is listed too.
    (second / "paper.pdf").unlink()
    (second / "paper.pdf").write_bytes(b"%PDF-1.4 b")
    assert len(mirror_entries(tmp_path)[0].pdfs) == 2


def test_mirror_entries_keeps_a_pdf_folder_without_record(tmp_path):
    _mirror_dir(tmp_path, "inbox", "Unknown - n.d. - Scan -- ZZZZ9999", pdf=b"%PDF-1.4 a")
    (entry,) = mirror_entries(tmp_path)
    assert entry.key == "ZZZZ9999" and entry.record == {} and len(entry.pdfs) == 1
    item = entry.item()
    assert item.title == "" and item.collection_paths == ["inbox"]


def test_mirror_entries_scope_by_prefix_and_keys(tmp_path):
    a = "Silva - 2021 - Deep sea governance -- ABCD1234"
    b = "Chen - 2019 - Krill -- EFGH5678"
    _mirror_dir(tmp_path, "ocean/BBNJ", a, record=_full_record())
    _mirror_dir(tmp_path, "law", a, record=_full_record(), pdf=b"%PDF-1.4 a")
    _mirror_dir(tmp_path, "oceanography", b, record=_full_record("EFGH5678"))
    assert [e.key for e in mirror_entries(tmp_path)] == ["ABCD1234", "EFGH5678"]
    scoped = mirror_entries(tmp_path, ["ocean"])
    # "ocean" does not match the sibling "oceanography"; the PDF under law/ still comes.
    assert [e.key for e in scoped] == ["ABCD1234"] and len(scoped[0].pdfs) == 1
    assert [e.key for e in mirror_entries(tmp_path, keys=["EFGH5678"])] == ["EFGH5678"]
    assert mirror_entries(tmp_path / "missing") == []


def test_mirror_entries_ignores_non_item_folders(tmp_path):
    (tmp_path / "ocean" / "notes").mkdir(parents=True)
    (tmp_path / "ocean" / "loose.pdf").write_bytes(b"%PDF-1.4 a")
    assert mirror_entries(tmp_path) == []
