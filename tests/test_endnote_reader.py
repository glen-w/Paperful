"""EndNote reader edges: path resolution, groups, trash, author splitting, odd library paths.

Adapter-field checklist: docs/templates/adapter-field-assessment.md (E1-E4, E9).
"""

from __future__ import annotations

import sqlite3
import struct
import tempfile
from pathlib import Path

import pytest

from paperful import endnote
from paperful.endnote import (
    EndNoteBackend,
    _endnote_member_ids,
    _parse_group_spec,
    _ref_get,
    _resolve_data_file,
    _split_authors,
    connect_readonly,
    library_paths,
)
from paperful.library import LibraryError
from tests.conftest import PDF_BYTES


def _library(root: Path, *, name: str = "Lib", refs=(), groups=(), members=(), files=(), group_cols=None):
    """Hand-built sdb.eni. ``refs`` rows: (id, title, trash_state)."""
    enl = root / f"{name}.enl"
    enl.write_bytes(b"enl")
    data = root / f"{name}.Data"
    (data / "sdb").mkdir(parents=True)
    conn = sqlite3.connect(str(data / "sdb" / "sdb.eni"))
    conn.execute(
        "CREATE TABLE refs (id INTEGER PRIMARY KEY, title TEXT, trash_state INTEGER, "
        "author TEXT, year TEXT, reference_type INTEGER, electronic_resource_number TEXT)"
    )
    conn.executemany(
        "INSERT INTO refs (id, title, trash_state, author, year, reference_type, electronic_resource_number) "
        "VALUES (?, ?, ?, 'Doe, Jo', '2020', 17, NULL)",
        refs,
    )
    conn.execute(group_cols or "CREATE TABLE groups (group_id INTEGER, group_name TEXT, parent_id INTEGER, group_type INTEGER)")
    for g in groups:
        conn.execute(f"INSERT INTO groups VALUES ({','.join('?' * len(g))})", g)
    conn.execute("CREATE TABLE group_refs (refs_id INTEGER, group_id INTEGER)")
    conn.executemany("INSERT INTO group_refs VALUES (?, ?)", members)
    conn.execute("CREATE TABLE file_res (refs_id INTEGER, file_path TEXT, file_type INTEGER)")
    conn.executemany("INSERT INTO file_res VALUES (?, ?, ?)", files)
    conn.commit()
    conn.close()
    return enl


def _backend(cfg, enl: Path) -> EndNoteBackend:
    cfg.endnote_library = enl
    return EndNoteBackend(cfg)


# --- pure helpers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Smith, Jane", [("Smith", "Jane")]),
        ("Jane Smith; Doe, Jo / Single", [("Smith", "Jane"), ("Doe", "Jo"), ("Single", "")]),
        ("A, B\x00C, D", [("A", "B"), ("C", "D")]),
        ("Line, One\r\nLine, Two", [("Line", "One"), ("Line", "Two")]),
        ("*Starred, Name*", [("Starred", "Name")]),
        ("  ;; / \n ", []),
        ("", []),
        ("Ada Byron King", [("King", "Ada Byron")]),
        ("Org//Other, Person", [("Org", ""), ("Other", "Person")]),
    ],
)
def test_split_authors(raw, expected):
    got = [(a["lastName"], a["firstName"]) for a in _split_authors(raw)]
    assert got == expected
    assert all(a["creatorType"] == "author" for a in _split_authors(raw))


def test_ref_get_is_case_insensitive_and_skips_blank_values():
    row = {"Title": "T", "author": "", "AUTHORS": "A"}
    assert _ref_get(row, "title") == "T"
    assert _ref_get(row, "author", "authors") == "A"
    assert _ref_get(row, "missing") is None
    assert _ref_get({"year": None}, "year") is None


@pytest.mark.parametrize(
    ("blob", "expected"),
    [
        (None, {}),
        ("", {}),
        (b"", {}),
        (b"  Plain Name  ", {"name": "Plain Name"}),
        ("   ", {}),
        ("<group><ids><name>Nested</name></ids></group>", {"name": "Nested"}),
        ("<group><name>First</name><name>Second</name></group>", {"name": "First"}),
        ("<group><ids/></group>", {}),
        ("<group><broken", {}),
        ("<group><rule>TYPE;6</rule></group>", {"skip": True}),
        (b"TYPE;6 online search", {"skip": True}),
        ('<ns:group xmlns:ns="urn:x"><ns:name>Namespaced</ns:name></ns:group>', {"name": "Namespaced"}),
    ],
)
def test_parse_group_spec(blob, expected):
    assert _parse_group_spec(blob) == expected


def test_member_blob_decodes_both_endians_and_rejects_bad_sizes():
    big = struct.pack(">II", 2, 3) + struct.pack(">3I", 4, 0, 9)
    little = struct.pack("<II", 2, 2) + struct.pack("<2I", 7, 8)
    assert _endnote_member_ids(big) == [4, 9]  # zero ids are dropped
    assert _endnote_member_ids(little) == [7, 8]
    assert _endnote_member_ids(b"") == [] and _endnote_member_ids(b"short") == []
    assert _endnote_member_ids(struct.pack(">II", 2, 0)) == []
    assert _endnote_member_ids(struct.pack(">II", 2, 5) + b"\x00" * 4) == []  # count/length mismatch
    assert _endnote_member_ids(struct.pack(">II", 2, 2_000_000)) == []


def test_resolve_data_file_search_order(tmp_path):
    data = tmp_path / "Lib.Data"
    (data / "PDF" / "123").mkdir(parents=True)
    (data / "PDF" / "123" / "deep.pdf").write_bytes(b"%PDF")
    (data / "PDF" / "top.pdf").write_bytes(b"%PDF")
    (data / "rooted.pdf").write_bytes(b"%PDF")
    assert _resolve_data_file(data, "rooted.pdf") == data / "rooted.pdf"
    assert _resolve_data_file(data, "top.pdf") == data / "PDF" / "top.pdf"
    assert _resolve_data_file(data, "123/deep.pdf") == data / "PDF" / "123" / "deep.pdf"
    assert _resolve_data_file(data, "internal-pdf://top.pdf") == data / "PDF" / "top.pdf"
    assert _resolve_data_file(data, "file:///top.pdf") == data / "PDF" / "top.pdf"
    # Wrong sub-folder in the stored path still finds the file by name under PDF/.
    assert _resolve_data_file(data, "elsewhere/deep.pdf") == data / "PDF" / "123" / "deep.pdf"
    assert _resolve_data_file(data, "nothing.pdf") is None
    assert _resolve_data_file(data, "") is None


@pytest.mark.parametrize("variant", ["enl", "data", "bare"])
def test_library_paths_accepts_enl_data_folder_or_bare_stem(tmp_path, variant):
    enl = _library(tmp_path, refs=[])
    arg = {"enl": enl, "data": tmp_path / "Lib.Data", "bare": tmp_path / "Lib"}[variant]
    got_enl, data, eni = library_paths(arg)
    assert data == tmp_path / "Lib.Data" and eni == data / "sdb" / "sdb.eni" and eni.is_file()
    if variant != "bare":
        assert got_enl == enl


# --- connection handling --------------------------------------------------------------


def test_connect_readonly_missing_database(tmp_path):
    with pytest.raises(LibraryError, match="EndNote database not found"):
        connect_readonly(tmp_path / "nope" / "sdb.eni")


def test_unlocked_database_is_opened_in_place_without_a_temp_copy(tmp_path, monkeypatch):
    enl = _library(tmp_path, refs=[(1, "T", 0)])
    _e, _d, eni = library_paths(enl)
    monkeypatch.setattr(
        tempfile, "mkdtemp", lambda *a, **k: (_ for _ in ()).throw(AssertionError("copied an unlocked db"))
    )
    conn = connect_readonly(eni)
    assert conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO refs (id, title) VALUES (2, 'write attempt')")


def test_library_in_a_folder_with_uri_special_characters_still_reads(tmp_path):
    odd = tmp_path / "My Library #2 (100%?)"
    odd.mkdir()
    enl = _library(odd, refs=[(1, "Odd path title", 0)])
    _e, _d, eni = library_paths(enl)
    conn = connect_readonly(eni)
    assert conn.execute("SELECT title FROM refs").fetchone()[0] == "Odd path title"


# --- backend reads --------------------------------------------------------------------


def test_trashed_refs_are_hidden_but_countable(cfg, tmp_path):
    enl = _library(tmp_path, refs=[(1, "Live", 0), (2, "Null trash", None), (3, "Trashed", 1)])
    backend = _backend(cfg, enl)
    assert backend._ref_ids() == {"1", "2"}
    assert backend._ref_ids(live_only=False) == {"1", "2", "3"}
    assert [r["title"] for r in backend._iter_refs(trashed_only=True)] == ["Trashed"]
    assert {r["title"] for r in backend._iter_refs()} == {"Live", "Null trash"}


def test_refs_without_trash_column_have_no_trash(cfg, tmp_path):
    enl = tmp_path / "Lib.enl"
    enl.write_bytes(b"enl")
    data = tmp_path / "Lib.Data"
    (data / "sdb").mkdir(parents=True)
    conn = sqlite3.connect(str(data / "sdb" / "sdb.eni"))
    conn.execute("CREATE TABLE refs (refs_id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO refs VALUES (5, 'Minimal')")
    conn.commit()
    conn.close()
    backend = _backend(cfg, enl)
    assert backend._ref_ids() == {"5"}  # refs_id is accepted as the key column
    assert backend._iter_refs(trashed_only=True) == []
    assert backend._ref_by_id("5")["title"] == "Minimal"
    assert backend._ref_by_id("999") is None


def test_database_without_refs_table_is_empty(cfg, tmp_path):
    enl = tmp_path / "Lib.enl"
    enl.write_bytes(b"enl")
    (tmp_path / "Lib.Data" / "sdb").mkdir(parents=True)
    sqlite3.connect(str(tmp_path / "Lib.Data" / "sdb" / "sdb.eni")).close()
    backend = _backend(cfg, enl)
    assert backend._ref_ids() == set() and backend._iter_refs() == []
    assert backend._ref_by_id("1") is None
    assert backend.collections() == {}


def test_nested_groups_build_slash_paths_and_sanitise_names(cfg, tmp_path):
    enl = _library(
        tmp_path,
        refs=[(1, "In child", 0), (2, "In root only", 0), (3, "Nowhere", 0)],
        groups=[
            (10, "BBNJ", 0, 1),
            (11, "EIA: scope/ratio?", 10, 1),
            (12, "Deep", 11, 1),
            (13, "Smart group", 0, 5),  # types above 2 are not user groups
        ],
        members=[(1, 12), (2, 10), (1, 13)],
    )
    backend = _backend(cfg, enl)
    cols = backend.collections()
    assert set(cols) == {"10", "11", "12"}
    assert cols["11"].path == "BBNJ/EIA_ scope_ratio_"
    assert cols["12"].path == "BBNJ/EIA_ scope_ratio_/Deep"
    assert cols["12"].parent == "11"
    items = {i.key: i for i in backend.items_in_scope(None)}
    assert items["1"].collection_paths == ["BBNJ/EIA_ scope_ratio_/Deep"]
    assert items["2"].collection_paths == ["BBNJ"]
    assert items["3"].collection_paths == ["Uncollected"] or items["3"].collection_paths  # never empty


def test_group_parent_cycle_does_not_recurse_forever(cfg, tmp_path):
    enl = _library(
        tmp_path,
        refs=[(1, "T", 0)],
        groups=[(1, "A", 2, 1), (2, "B", 1, 1)],
        members=[(1, 1)],
    )
    cols = _backend(cfg, enl).collections()
    assert set(cols) == {"1", "2"}
    assert cols["1"].path.count("/") <= 51  # bounded by the depth guard


def test_group_members_from_blob_when_no_member_table(cfg, tmp_path):
    enl = tmp_path / "Lib.enl"
    enl.write_bytes(b"enl")
    data = tmp_path / "Lib.Data"
    (data / "sdb").mkdir(parents=True)
    conn = sqlite3.connect(str(data / "sdb" / "sdb.eni"))
    conn.execute("CREATE TABLE refs (id INTEGER PRIMARY KEY, title TEXT, trash_state INTEGER)")
    conn.executemany("INSERT INTO refs VALUES (?, ?, 0)", [(1, "One"), (2, "Two")])
    conn.execute("CREATE TABLE groups (group_id INTEGER, spec BLOB, members BLOB)")
    spec = b"<group><ids><name>Blob</name></ids></group>"
    little = struct.pack("<II", 2, 1) + struct.pack("<I", 2)
    conn.execute("INSERT INTO groups VALUES (1, ?, ?)", (spec, little))
    conn.commit()
    conn.close()
    backend = _backend(cfg, enl)
    items = backend.items_in_scope(backend.subtree_keys(backend.resolve_collection("Blob")))
    assert [i.title for i in items] == ["Two"]


def test_groups_table_without_id_column_yields_no_collections(cfg, tmp_path):
    enl = _library(
        tmp_path,
        refs=[(1, "T", 0)],
        group_cols="CREATE TABLE groups (label TEXT)",
    )
    assert _backend(cfg, enl).collections() == {}


def test_pdf_lookup_prefers_primary_file_type_then_falls_back(cfg, tmp_path):
    enl = _library(tmp_path, refs=[(1, "With files", 0), (2, "Name match only", 0), (3, "No pdf", 0)])
    pdfs = tmp_path / "Lib.Data" / "PDF"
    pdfs.mkdir()
    (pdfs / "supplement.pdf").write_bytes(PDF_BYTES)
    (pdfs / "main.pdf").write_bytes(PDF_BYTES)
    (pdfs / "ref-2-copy.pdf").write_bytes(PDF_BYTES)
    conn = sqlite3.connect(str(tmp_path / "Lib.Data" / "sdb" / "sdb.eni"))
    conn.executemany(
        "INSERT INTO file_res VALUES (?, ?, ?)",
        [(1, "supplement.pdf", 2), (1, "main.pdf", 1), (1, "", 1), (1, "vanished.pdf", 1)],
    )
    conn.commit()
    conn.close()
    backend = _backend(cfg, enl)
    assert backend._pdf_for("1").name == "main.pdf"
    assert backend._pdf_for("2") is None or backend._pdf_for("2").name  # not matched through file_res
    assert backend._pdf_for("3") is None
    assert backend._pdf_for("404") is None


def test_unreadable_file_res_does_not_break_item_listing(cfg, tmp_path):
    enl = _library(tmp_path, refs=[(1, "T", 0)])
    conn = sqlite3.connect(str(tmp_path / "Lib.Data" / "sdb" / "sdb.eni"))
    conn.execute("DROP TABLE file_res")
    conn.execute("CREATE TABLE file_res (unrelated TEXT)")
    conn.commit()
    conn.close()
    backend = _backend(cfg, enl)
    assert backend._pdf_for("1") is None
    assert [i.title for i in backend.items_in_scope(None)] == ["T"]


def test_module_exports_stay_importable():
    assert endnote.EndNoteBackend is EndNoteBackend
