"""EndNote SQLite reader and staged XML+PDF import bundle."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from paperful.endnote import EndNoteBackend, library_paths
from paperful.library import LibraryError
from paperful.xfer import apply_import
from tests.conftest import PDF_BYTES


def make_endnote_library(root: Path) -> Path:
    enl = root / "Lib.enl"
    enl.write_bytes(b"enl")
    data = root / "Lib.Data"
    (data / "sdb").mkdir(parents=True)
    pdf_dir = data / "PDF"
    pdf_dir.mkdir()
    (pdf_dir / "paper.pdf").write_bytes(PDF_BYTES)
    conn = sqlite3.connect(str(data / "sdb" / "sdb.eni"))
    conn.execute(
        """
        CREATE TABLE refs (
            id INTEGER PRIMARY KEY,
            title TEXT,
            year TEXT,
            author TEXT,
            secondary_title TEXT,
            abstract TEXT,
            keywords TEXT,
            notes TEXT,
            research_notes TEXT,
            trash_state INTEGER,
            electronic_resource_number TEXT,
            url TEXT,
            reference_type INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE groups (
            group_id INTEGER,
            group_name TEXT,
            parent_id INTEGER,
            group_type INTEGER
        )
        """
    )
    conn.execute("CREATE TABLE group_refs (refs_id INTEGER, group_id INTEGER)")
    conn.execute("CREATE TABLE file_res (refs_id INTEGER, file_path TEXT)")
    conn.execute(
        """
        INSERT INTO refs VALUES (
            1, 'The Sea', '2020', 'Smith, Jane', 'Marine Policy',
            'Abs', 'BBNJ', 'a note', '', 0, '10.1000/xyz', 'https://ex.org', 0
        )
        """
    )
    conn.execute("INSERT INTO groups VALUES (10, 'BBNJ', 0, 1)")
    conn.execute("INSERT INTO group_refs VALUES (1, 10)")
    conn.execute("INSERT INTO file_res VALUES (1, 'paper.pdf')")
    conn.commit()
    conn.close()
    return enl


def _backend(cfg, enl: Path) -> EndNoteBackend:
    cfg.endnote_library = enl
    return EndNoteBackend(cfg)


def test_library_paths_from_enl_and_data(tmp_path):
    enl = make_endnote_library(tmp_path)
    got_enl, data, eni = library_paths(enl)
    assert got_enl == enl
    assert data.name == "Lib.Data"
    assert eni.name == "sdb.eni"
    again = library_paths(data)
    assert again[2] == eni


def test_endnote_reads_refs_groups_and_pdfs(cfg, tmp_path):
    backend = _backend(cfg, make_endnote_library(tmp_path))
    info = backend.ping()
    assert info["refs"] == 1 and info["write_mode"] == "bundle"
    col = backend.resolve_collection("BBNJ")
    items = backend.items_in_scope(backend.subtree_keys(col))
    assert len(items) == 1
    it = items[0]
    assert it.key == "1"
    assert it.item_type == "journalArticle"
    assert it.doi == "10.1000/xyz"
    assert it.first_author == "Smith"
    assert it.has_pdf
    dest = tmp_path / "exported.pdf"
    assert backend.export_pdf(it, dest) == dest
    assert dest.read_bytes() == PDF_BYTES
    notes = [ch for ch in backend.children("1") if (ch.get("data") or {}).get("itemType") == "note"]
    assert notes


def test_endnote_flush_writes_xml_bundle(cfg, tmp_path):
    backend = _backend(cfg, make_endnote_library(tmp_path))
    extra = tmp_path / "new.pdf"
    extra.write_bytes(PDF_BYTES)
    backend.apply_patch("1", {"title": "The High Seas"})
    backend.attach("1", extra)
    backend.create_or_update_note("1", "<p>sum</p>", "paperful-summary")
    dest = backend.flush_writes()
    assert dest is not None
    xml = (dest / "paperful.xml").read_text(encoding="utf-8")
    assert "The High Seas" in xml
    assert "internal-pdf://" in xml
    assert (dest / "PDF" / extra.name).is_file()
    assert "File → Import" in (dest / "README.txt").read_text(encoding="utf-8")
    assert backend.flush_writes() is None


def test_endnote_import_stages_new_item(cfg, tmp_path):
    backend = _backend(cfg, make_endnote_library(tmp_path))
    pdf = tmp_path / "imp.pdf"
    pdf.write_bytes(PDF_BYTES)
    apply_import(
        [
            {
                "item_type": "journalArticle",
                "title": "Imported EndNote",
                "creators": [
                    {"creatorType": "author", "lastName": "Ng", "firstName": "Li"}
                ],
                "year": 2018,
                "doi": "10.3/z",
                "notes": [{"html": "<p>n</p>", "tag": "paperful-imported"}],
                "pdfs": [str(pdf)],
                "collection_paths": ["BBNJ/EIA"],
            }
        ],
        backend,
        dry_run=False,
    )
    dest = backend.flush_writes()
    xml = (dest / "paperful.xml").read_text(encoding="utf-8")
    assert "Imported EndNote" in xml
    assert "BBNJ/EIA" in xml
    assert (dest / "PDF" / "imp.pdf").is_file()


def test_endnote_refuses_trash(cfg, tmp_path):
    backend = _backend(cfg, make_endnote_library(tmp_path))
    with pytest.raises(LibraryError, match="trash"):
        backend.trash_item("1")


def test_endnote_refuses_merge(cfg, tmp_path):
    backend = _backend(cfg, make_endnote_library(tmp_path))
    with pytest.raises(LibraryError, match="merge"):
        backend.merge_into("1", "2")


def test_endnote_registers_collations(cfg, tmp_path):
    backend = _backend(cfg, make_endnote_library(tmp_path))
    conn = backend._db()
    n = conn.execute(
        "SELECT COUNT(*) FROM refs WHERE title COLLATE ENCI_Base = title"
    ).fetchone()[0]
    assert n == 1


def test_endnote_reads_groups_from_spec_and_members(cfg, tmp_path):
    import struct

    enl = tmp_path / "Lib.enl"
    enl.write_bytes(b"enl")
    data = tmp_path / "Lib.Data"
    (data / "sdb").mkdir(parents=True)
    conn = sqlite3.connect(str(data / "sdb" / "sdb.eni"))
    conn.execute(
        """
        CREATE TABLE refs (
            id INTEGER PRIMARY KEY,
            title TEXT,
            trash_state INTEGER,
            reference_type INTEGER,
            electronic_resource_number TEXT
        )
        """
    )
    conn.execute(
        "CREATE TABLE groups (group_id INTEGER PRIMARY KEY, spec BLOB, members BLOB)"
    )
    spec = (
        b'<group version="1"><ids><id>aaaa</id><name>BBNJ</name></ids></group>'
    )
    members = struct.pack(">II", 2, 1) + struct.pack(">I", 1)
    conn.execute(
        "INSERT INTO refs VALUES (1, 'The Sea', 0, 0, '10.1000/xyz')"
    )
    conn.execute("INSERT INTO groups VALUES (10, ?, ?)", (spec, members))
    conn.commit()
    conn.close()
    backend = _backend(cfg, enl)
    col = backend.resolve_collection("BBNJ")
    items = backend.items_in_scope(backend.subtree_keys(col))
    assert len(items) == 1
    assert items[0].item_type == "journalArticle"
    assert items[0].doi == "10.1000/xyz"
    assert items[0].collection_paths == ["BBNJ"]


def test_endnote_skips_online_search_groups(cfg, tmp_path):
    enl = tmp_path / "Lib.enl"
    enl.write_bytes(b"enl")
    data = tmp_path / "Lib.Data"
    (data / "sdb").mkdir(parents=True)
    conn = sqlite3.connect(str(data / "sdb" / "sdb.eni"))
    conn.execute(
        "CREATE TABLE refs (id INTEGER PRIMARY KEY, title TEXT, trash_state INTEGER)"
    )
    conn.execute(
        "CREATE TABLE groups (group_id INTEGER PRIMARY KEY, spec BLOB, members BLOB)"
    )
    online = b"<group><ids><name>PubMed</name></ids><rule>TYPE;6</rule></group>"
    keep = b"<group><ids><name>Keep</name></ids></group>"
    conn.execute("INSERT INTO refs VALUES (1, 'The Sea', 0)")
    conn.execute("INSERT INTO groups VALUES (1, ?, ?)", (online, b""))
    conn.execute("INSERT INTO groups VALUES (2, ?, ?)", (keep, b""))
    conn.commit()
    conn.close()
    backend = _backend(cfg, enl)
    names = {c.name for c in backend.collections().values()}
    assert "Keep" in names
    assert "PubMed" not in names


def test_endnote_copy_on_lock_includes_journal(cfg, tmp_path, monkeypatch):
    import shutil

    from paperful.endnote import connect_readonly

    make_endnote_library(tmp_path)
    eni = tmp_path / "Lib.Data" / "sdb" / "sdb.eni"
    (eni.parent / "sdb.eni-journal").write_bytes(b"jnl")
    copied: list[str] = []
    real_copy = shutil.copy2

    def spy(src, dst, *args, **kwargs):
        copied.append(str(src).rsplit("/", 1)[-1])
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr("paperful.endnote.shutil.copy2", spy)
    real_connect = sqlite3.connect

    def locked(database, *args, **kwargs):
        if kwargs.get("uri") or str(database).startswith("file:"):
            raise sqlite3.OperationalError("database is locked")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr("paperful.endnote.sqlite3.connect", locked)
    conn = connect_readonly(eni)
    assert conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0] == 1
    assert "sdb.eni" in copied
    assert "sdb.eni-journal" in copied


def test_endnote_changes_full_noop_and_gone(cfg, tmp_path):
    import os
    import time

    from paperful.catalogue import has_change_feed
    from paperful.sync import run_sync

    enl = make_endnote_library(tmp_path)
    backend = _backend(cfg, enl)
    assert has_change_feed(backend)

    full = backend.changes(None)
    assert full.full and "1" in full.top_keys
    assert full.version == int(backend.eni.stat().st_mtime)
    assert not full.track_child_keys
    assert any(r.get("key") == "1" for r in full.rows)
    assert (full.rows[0].get("data") or {}).get("collections") == ["10"]

    noop = backend.changes(full.version)
    assert not noop.full and noop.rows == [] and noop.version == full.version

    stats = run_sync(cfg, backend, pdfs="none")
    assert stats.written >= 1
    assert (cfg.out_dir / "_sync.json").is_file()

    conn = sqlite3.connect(str(backend.eni))
    conn.execute("UPDATE refs SET trash_state = 1 WHERE id = 1")
    conn.commit()
    conn.close()
    time.sleep(1.05)
    os.utime(backend.eni, None)
    after = backend.changes(full.version)
    assert after.full
    assert "1" not in after.top_keys
    assert any(t.get("key") == "1" for t in after.trashed)


def test_endnote_xml_journal_ref_type_17_not_db_zero(cfg, tmp_path):
    backend = _backend(cfg, make_endnote_library(tmp_path))
    backend.apply_patch("1", {"title": "Journal export"})
    dest = backend.flush_writes()
    xml = (dest / "paperful.xml").read_text(encoding="utf-8")
    assert 'name="Journal Article"' in xml
    assert "<ref-type" in xml and ">17<" in xml.replace(" ", "")
    assert "<groups" not in xml.lower()


def test_endnote_db_reference_type_17_maps_to_bill_not_journal(cfg, tmp_path):
    enl = tmp_path / "Lib.enl"
    enl.write_bytes(b"enl")
    data = tmp_path / "Lib.Data"
    (data / "sdb").mkdir(parents=True)
    conn = sqlite3.connect(str(data / "sdb" / "sdb.eni"))
    conn.execute(
        """
        CREATE TABLE refs (
            id INTEGER PRIMARY KEY,
            title TEXT,
            trash_state INTEGER,
            reference_type INTEGER,
            electronic_resource_number TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO refs VALUES (2, 'A Bill', 0, 17, '')"
    )
    conn.commit()
    conn.close()
    backend = _backend(cfg, enl)
    it = backend.get_item("2")
    assert it is not None
    assert it.item_type == "bill"


def test_endnote_readme_matches_clarivate_import_steps(cfg, tmp_path):
    backend = _backend(cfg, make_endnote_library(tmp_path))
    backend.apply_patch("1", {"title": "Readme check"})
    dest = backend.flush_writes()
    readme = (dest / "README.txt").read_text(encoding="utf-8")
    assert "EndNote Generated XML" in readme
    assert "Duplicates" in readme
    assert "File → Import" in readme
    assert (dest / "paperful.xml").parent == dest
    assert (dest / "PDF").is_dir()
    assert "sdb" not in str(dest / "PDF")


def test_endnote_bundle_xml_label_only_for_collection_path(cfg, tmp_path):
    backend = _backend(cfg, make_endnote_library(tmp_path))
    backend.apply_patch("1", {"title": "Labeled"})
    rec = backend._pending_by_key.get("1") or backend._pending[0]
    rec["collection_paths"] = ["BBNJ/EIA"]
    dest = backend.flush_writes()
    xml = (dest / "paperful.xml").read_text(encoding="utf-8")
    assert "BBNJ/EIA" in xml
    assert "<label>" in xml or "BBNJ/EIA" in xml


def test_endnote_internal_pdf_round_trip_in_bundle(cfg, tmp_path):
    from paperful.interop.endnote_xml import parse_endnote_xml

    backend = _backend(cfg, make_endnote_library(tmp_path))
    extra = tmp_path / "round.pdf"
    extra.write_bytes(PDF_BYTES)
    backend.attach("1", extra)
    dest = backend.flush_writes()
    xml_path = dest / "paperful.xml"
    records = parse_endnote_xml(xml_path.read_text(encoding="utf-8"), xml_path=xml_path)
    assert records[0]["pdfs"]
    assert (dest / "PDF" / extra.name).is_file()


def test_endnote_refuses_add_to_collection(cfg, tmp_path):
    backend = _backend(cfg, make_endnote_library(tmp_path))
    with pytest.raises(LibraryError, match="group"):
        backend.add_to_collection("1", "10")


def test_endnote_copy_on_lock_includes_wal_and_shm(cfg, tmp_path, monkeypatch):
    import shutil

    from paperful.endnote import connect_readonly

    make_endnote_library(tmp_path)
    eni = tmp_path / "Lib.Data" / "sdb" / "sdb.eni"
    for suffix in ("-wal", "-shm", "-journal"):
        eni.with_name(eni.name + suffix).write_bytes(b"x")
    copied: list[str] = []
    real_copy = shutil.copy2

    def spy(src, dst, *args, **kwargs):
        copied.append(Path(src).name)
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr("paperful.endnote.shutil.copy2", spy)
    real_connect = sqlite3.connect

    def locked(database, *args, **kwargs):
        if kwargs.get("uri") or str(database).startswith("file:"):
            raise sqlite3.OperationalError("database is locked")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr("paperful.endnote.sqlite3.connect", locked)
    conn = connect_readonly(eni)
    assert conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0] == 1
    assert "sdb.eni" in copied
    assert "sdb.eni-wal" in copied
    assert "sdb.eni-shm" in copied
    assert "sdb.eni-journal" in copied
