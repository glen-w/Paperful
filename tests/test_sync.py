"""The refresh: what changed and nothing else, and never a guess when a read fails."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from paperful.config import Config
from paperful.library import ChangeSet, LibraryError, LibraryReadError
from paperful.mirror import forget_index, items_in_mirror, load_record
from paperful.snapshot import read_index
from paperful.sync import run_sync, sync_state
from paperful.zot import Collection, Item

PDF = b"%PDF-1.4 the bytes"
PDF_MD5 = hashlib.md5(PDF).hexdigest()


@pytest.fixture(autouse=True)
def _fresh_index():
    forget_index()
    yield
    forget_index()


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        out_dir=tmp_path / "out", state_dir=tmp_path / "state", mirror_pdfs="lazy"
    )


class FakeZotero:
    """A library with versions, a trash, and a count of every call made to it."""

    def __init__(self):
        self.version = 10
        self.rows: dict[str, dict] = {}
        self.trash: set[str] = set()
        self.files: dict[str, bytes] = {}
        self.calls: Counter = Counter()
        self.library_id = "LIB-ONE"
        self.fail: set[str] = set()
        self.cols = {
            "COLA": Collection("COLA", "Alpha", None, "Alpha", "Alpha"),
            "COLB": Collection("COLB", "Beta", None, "Beta", "Beta"),
        }

    # ---- test-side edits (each one bumps the library version) -------------
    def put(self, key: str, **data) -> None:
        self.version += 1
        body = (self.rows.get(key) or {}).get("data") or {
            "itemType": "journalArticle",
            "title": "First title",
            "creators": [{"creatorType": "author", "lastName": "Smith"}],
            "date": "2020",
            "collections": ["COLA"],
        }
        body = {**body, **data}
        self.rows[key] = {"key": key, "version": self.version, "data": body}

    def attach(self, parent: str, key: str, *, bytes_: bytes | None = PDF) -> None:
        self.put(
            key,
            itemType="attachment",
            parentItem=parent,
            linkMode="imported_file",
            contentType="application/pdf",
            filename="paper.pdf",
            md5=hashlib.md5(bytes_).hexdigest() if bytes_ else "0" * 32,
            title="Full Text PDF",
        )
        if bytes_ is not None:
            self.files[key] = bytes_

    def note(self, parent: str, key: str, html: str = "<p>n</p>") -> None:
        self.put(key, itemType="note", parentItem=parent, note=html, tags=[])

    def annotate(self, attachment: str, key: str, text: str = "hl") -> None:
        self.put(key, itemType="annotation", parentItem=attachment, annotationText=text)

    def to_trash(self, key: str) -> None:
        self.version += 1
        self.trash.add(key)

    def restore(self, key: str) -> None:
        self.version += 1
        self.trash.discard(key)
        self.rows[key]["version"] = self.version

    def delete(self, key: str) -> None:
        self.version += 1
        self.rows.pop(key, None)
        self.trash.discard(key)

    # ---- what the adapter exposes -------------------------------------------
    def _live(self) -> dict[str, dict]:
        gone = set(self.trash)
        for _ in range(3):  # a trashed parent takes its children with it
            gone |= {
                k for k, r in self.rows.items() if r["data"].get("parentItem") in gone
            }
        return {k: r for k, r in self.rows.items() if k not in gone}

    def _out(self, row: dict) -> dict:
        row = copy.deepcopy(row)
        live = self._live()
        row["meta"] = {
            "numChildren": sum(
                1 for r in live.values() if r["data"].get("parentItem") == row["key"]
            )
        }
        return row

    def changes(self, since):
        self.calls["changes"] += 1
        if "changes" in self.fail:
            raise LibraryReadError("Zotero read failed (library changes)")
        live = self._live()
        rows = [
            self._out(r)
            for r in live.values()
            if since is None or r["version"] > since
        ]
        return ChangeSet(
            version=self.version,
            full=since is None,
            rows=rows,
            top_keys={k for k, r in live.items() if not r["data"].get("parentItem")},
            all_keys=set(live),
            trashed=[self._out(self.rows[k]) for k in self.trash],
            collections=dict(self.cols),
            library_id=self.library_id,
        )

    def raw_item(self, key):
        self.calls["raw_item"] += 1
        if key in self.fail:
            raise LibraryReadError(f"Zotero read failed (item {key})")
        row = self._live().get(key)
        return self._out(row) if row else None

    def children(self, key):
        self.calls["children"] += 1
        if key in self.fail:
            raise LibraryReadError(f"Zotero read failed (children of {key})")
        return [
            self._out(r)
            for r in self._live().values()
            if r["data"].get("parentItem") == key
        ]

    def export_pdf(self, item: Item, dest: Path):
        self.calls["export_pdf"] += 1
        if "export" in self.fail:
            raise LibraryReadError("Zotero read failed (export)")
        for row in self.children(item.key):
            data = self.files.get(row["key"])
            if data is not None:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                return dest
        return None

    def reads(self) -> int:
        return self.calls["raw_item"] + self.calls["children"]


def _folder(cfg, key: str, collection: str = "Alpha", title: str = "First title") -> Path:
    return cfg.out_dir / collection / f"Smith - 2020 - {title} -- {key}"


def _library(cfg, n: int = 2) -> FakeZotero:
    zot = FakeZotero()
    for i in range(1, n + 1):
        zot.put(f"ITEM000{i}", title=f"Paper {i}")
    return zot


# ---- first refresh -------------------------------------------------------------


def test_first_refresh_writes_everything_without_a_request_per_item(cfg):
    zot = _library(cfg, n=3)
    zot.attach("ITEM0001", "ATT00001")
    zot.note("ITEM0001", "NOTE0001")
    stats = run_sync(cfg, zot)
    assert stats.full and stats.written == 3 and stats.unread == 0
    assert zot.calls["changes"] == 1 and zot.reads() == 0
    state = sync_state(cfg.out_dir)
    assert state["version"] == zot.version and state["library"] == "LIB-ONE"
    assert state["last_written"] == 3 and state["last_gone"] == 0
    from paperful.catalogue import MirrorCatalogue

    assert "3 written, 0 gone" in MirrorCatalogue(cfg.out_dir).age_line()
    items = {i.key: i for i in items_in_mirror(cfg.out_dir)}
    assert sorted(items) == ["ITEM0001", "ITEM0002", "ITEM0003"]
    assert items["ITEM0001"].has_pdf and not items["ITEM0002"].has_pdf
    index = read_index(cfg.out_dir)
    assert index["ITEM0001"]["children"] == ["ATT00001", "NOTE0001"]
    cols = json.loads((cfg.out_dir / "_collections.json").read_text())
    assert [c["path"] for c in cols["collections"]] == ["Alpha", "Beta"]


def test_a_refresh_with_nothing_changed_reads_and_writes_nothing(cfg):
    zot = _library(cfg)
    run_sync(cfg, zot)
    before = {p: p.read_bytes() for p in cfg.out_dir.rglob("record.json")}
    zot.calls.clear()
    stats = run_sync(cfg, zot)
    assert not stats.full and stats.written == 0 and not stats.changed
    assert zot.calls == Counter(changes=1)
    assert {p: p.read_bytes() for p in cfg.out_dir.rglob("record.json")} == before


def test_standalone_notes_land_under_out_notes(cfg):
    from paperful.catalogue import MirrorCatalogue

    zot = FakeZotero()
    zot.put(
        "NOTESTAND",
        itemType="note",
        note="<p>collection report</p>",
        tags=[{"tag": "paperful-report"}],
        collections=["COLA"],
        title="",
    )
    # Top-level note must not carry a parentItem.
    zot.rows["NOTESTAND"]["data"].pop("parentItem", None)
    run_sync(cfg, zot, pdfs="none")
    note_dir = cfg.out_dir / "_notes" / "NOTESTAND"
    assert (note_dir / "note.html").read_text() == "<p>collection report</p>"
    cat = MirrorCatalogue(cfg.out_dir)
    assert cat.find_collection_note_keys("COLA", "paperful-report") == ["NOTESTAND"]
    raw = cat.raw_item("NOTESTAND")
    assert raw is not None and raw["data"]["itemType"] == "note"


def test_non_pdf_attachment_bytes_copy_when_pdfs_all(cfg):
    zot = _library(cfg, n=1)
    zot.put(
        "SNAP0001",
        itemType="attachment",
        parentItem="ITEM0001",
        linkMode="imported_file",
        contentType="text/html",
        filename="snapshot.html",
        title="Snapshot",
    )
    zot.files["SNAP0001"] = b"<html>snap</html>"

    def export_attachment(key, dest):
        data = zot.files.get(key)
        if data is None:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    zot.export_attachment = export_attachment  # type: ignore[attr-defined]
    run_sync(cfg, zot, pdfs="all")
    folders = [
        p.parent
        for p in cfg.out_dir.rglob("record.json")
        if "ITEM0001" in p.parent.name
    ]
    assert folders
    assert (folders[0] / "snapshot.html").read_bytes() == b"<html>snap</html>"


def test_standalone_attachment_lands_under_out_attachments(cfg):
    zot = FakeZotero()
    zot.put(
        "FILESTAND",
        itemType="attachment",
        linkMode="imported_file",
        contentType="application/epub+zip",
        filename="book.epub",
        title="Standalone EPUB",
        collections=["COLA"],
    )
    zot.rows["FILESTAND"]["data"].pop("parentItem", None)
    zot.files["FILESTAND"] = b"PK\x03\x04epub"

    def export_attachment(key, dest):
        data = zot.files.get(key)
        if data is None:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    zot.export_attachment = export_attachment  # type: ignore[attr-defined]
    run_sync(cfg, zot, pdfs="none")
    folder = cfg.out_dir / "_attachments" / "FILESTAND"
    assert (folder / "record.json").is_file()
    assert (folder / "book.epub").read_bytes() == b"PK\x03\x04epub"


def test_parents_only_feed_empty_delta_does_not_rewrite_children(cfg):
    """Mendeley/EndNote set track_child_keys=False; empty delta must not touch parents."""
    from paperful.library import ChangeSet
    from paperful.zot import Collection

    zot = _library(cfg, n=1)
    zot.attach("ITEM0001", "ATT00001")
    run_sync(cfg, zot, pdfs="none")
    before = {
        p: p.read_bytes()
        for p in cfg.out_dir.rglob("record.json")
        if "_notes" not in str(p) and "_attachments" not in str(p)
    }

    def changes(since):
        return ChangeSet(
            version=zot.version,
            full=False,
            rows=[],
            top_keys={"ITEM0001"},
            all_keys={"ITEM0001"},  # parents-only on purpose
            trashed=[],
            collections={
                "COLA": Collection("COLA", "Alpha", None, "Alpha", "Alpha"),
            },
            library_id=zot.library_id,
            track_child_keys=False,
        )

    zot.changes = changes  # type: ignore[method-assign]
    stats = run_sync(cfg, zot, pdfs="none")
    assert stats.written == 0
    assert {
        p: p.read_bytes()
        for p in cfg.out_dir.rglob("record.json")
        if "_notes" not in str(p) and "_attachments" not in str(p)
    } == before


def test_dry_run_writes_nothing(cfg):
    zot = _library(cfg)
    stats = run_sync(cfg, zot, dry_run=True)
    assert stats.written == 2
    assert not cfg.out_dir.exists() or not any(cfg.out_dir.iterdir())
    assert sync_state(cfg.out_dir) is None


# ---- deltas ----------------------------------------------------------------------


def test_a_retitled_item_keeps_its_folder_contents(cfg):
    zot = _library(cfg, n=1)
    run_sync(cfg, zot)
    old = _folder(cfg, "ITEM0001", title="Paper 1")
    (old / "paper.pdf").write_bytes(PDF)
    zot.put("ITEM0001", title="Renamed")
    stats = run_sync(cfg, zot)
    assert stats.written == 1
    new = _folder(cfg, "ITEM0001", title="Renamed")
    assert not old.exists() and (new / "paper.pdf").read_bytes() == PDF
    assert load_record(cfg.out_dir, "ITEM0001")["title"] == "Renamed"


def test_a_new_item_with_its_children_in_the_delta_needs_no_second_read(cfg):
    zot = _library(cfg, n=1)
    run_sync(cfg, zot)
    zot.calls.clear()
    zot.put("ITEM0009", title="Brand new")
    zot.attach("ITEM0009", "ATT00009")
    stats = run_sync(cfg, zot)
    assert stats.written == 1 and zot.reads() == 0
    assert {i.key: i.has_pdf for i in items_in_mirror(cfg.out_dir)}["ITEM0009"] is True


def test_a_child_added_to_an_unchanged_parent_refreshes_that_parent(cfg):
    zot = _library(cfg)
    zot.note("ITEM0001", "NOTE0001", "<p>old</p>")
    run_sync(cfg, zot)
    zot.calls.clear()
    zot.attach("ITEM0001", "ATT00001")
    stats = run_sync(cfg, zot)
    assert stats.written == 1
    assert zot.calls["raw_item"] == 1 and zot.calls["children"] == 1
    rec = load_record(cfg.out_dir, "ITEM0001")
    assert [a["key"] for a in rec["attachments"]] == ["ATT00001"]
    assert len(rec["notes"]) == 1  # the unchanged sibling is still there


def test_a_child_removed_in_the_library_is_removed_from_the_record(cfg):
    zot = _library(cfg)
    zot.attach("ITEM0001", "ATT00001")
    run_sync(cfg, zot)
    assert {i.key: i.has_pdf for i in items_in_mirror(cfg.out_dir)}["ITEM0001"]
    zot.delete("ATT00001")
    stats = run_sync(cfg, zot)
    assert stats.written == 1
    assert load_record(cfg.out_dir, "ITEM0001")["attachments"] == []
    zot.attach("ITEM0001", "ATT00002")
    run_sync(cfg, zot)
    zot.to_trash("ATT00002")
    run_sync(cfg, zot)
    assert load_record(cfg.out_dir, "ITEM0001")["attachments"] == []


def test_collection_changes_move_add_and_fold_folders(cfg):
    zot = _library(cfg, n=1)
    run_sync(cfg, zot)
    alpha = _folder(cfg, "ITEM0001", "Alpha", "Paper 1")
    beta = _folder(cfg, "ITEM0001", "Beta", "Paper 1")
    (alpha / "paper.pdf").write_bytes(PDF)

    zot.put("ITEM0001", collections=["COLB"])  # moved
    run_sync(cfg, zot)
    assert not alpha.exists() and (beta / "paper.pdf").read_bytes() == PDF

    zot.put("ITEM0001", collections=["COLA", "COLB"])  # also in Alpha now
    run_sync(cfg, zot)
    assert (alpha / "paper.pdf").samefile(beta / "paper.pdf")
    assert load_record(cfg.out_dir, "ITEM0001")["collection_paths"] == ["Alpha", "Beta"]

    (beta / "only-here.txt").write_text("keep me")
    zot.put("ITEM0001", collections=["COLA"])  # left Beta
    run_sync(cfg, zot)
    assert not beta.exists()
    assert (alpha / "paper.pdf").read_bytes() == PDF
    assert (alpha / "only-here.txt").read_text() == "keep me"

    zot.put("ITEM0001", collections=[])  # in no collection
    run_sync(cfg, zot)
    assert (_folder(cfg, "ITEM0001", "_uncollected", "Paper 1") / "paper.pdf").is_file()


# ---- items that leave ---------------------------------------------------------------


def test_trashed_and_deleted_items_are_marked_and_kept(cfg):
    zot = _library(cfg, n=3)
    run_sync(cfg, zot)
    folder = _folder(cfg, "ITEM0001", title="Paper 1")
    (folder / "paper.pdf").write_bytes(PDF)
    zot.to_trash("ITEM0001")
    zot.delete("ITEM0002")
    stats = run_sync(cfg, zot)
    assert stats.gone == 2
    assert load_record(cfg.out_dir, "ITEM0001")["library"]["state"] == "trashed"
    assert load_record(cfg.out_dir, "ITEM0002")["library"]["state"] == "gone"
    assert (folder / "paper.pdf").is_file()
    assert [i.key for i in items_in_mirror(cfg.out_dir)] == ["ITEM0003"]
    again = run_sync(cfg, zot)
    assert again.gone == 0 and not again.changed

    zot.restore("ITEM0001")
    run_sync(cfg, zot)
    assert "library" not in load_record(cfg.out_dir, "ITEM0001")
    assert (folder / "paper.pdf").is_file()


def test_gone_policy_trash_moves_the_folder_and_brings_it_back(cfg):
    cfg.mirror_gone = "trash"
    zot = _library(cfg)
    run_sync(cfg, zot)
    folder = _folder(cfg, "ITEM0001", title="Paper 1")
    (folder / "paper.pdf").write_bytes(PDF)
    zot.to_trash("ITEM0001")
    run_sync(cfg, zot)
    parked = cfg.out_dir / "_trash" / "Alpha" / folder.name
    assert not folder.exists() and (parked / "paper.pdf").is_file()
    assert [i.key for i in items_in_mirror(cfg.out_dir)] == ["ITEM0002"]
    assert run_sync(cfg, zot).gone == 0
    zot.restore("ITEM0001")
    run_sync(cfg, zot)
    assert (folder / "paper.pdf").is_file() and not parked.exists()


def test_a_mirror_that_is_mostly_absent_from_the_library_is_refused(cfg):
    zot = FakeZotero()
    for i in range(120):
        zot.put(f"ITEM{i:04d}", title=f"Paper {i}")
    run_sync(cfg, zot)
    other = FakeZotero()
    other.library_id = "LIB-TWO"
    other.put("ELSE0001", title="Another library")
    before = {p: p.read_bytes() for p in cfg.out_dir.rglob("record.json")}
    with pytest.raises(LibraryError, match="different library"):
        run_sync(cfg, other)
    assert {p: p.read_bytes() for p in cfg.out_dir.rglob("record.json")} == before
    assert sync_state(cfg.out_dir)["library"] == "LIB-ONE"
    stats = run_sync(cfg, other, accept_gone=True)
    assert stats.full and stats.gone == 120


def test_another_library_on_the_same_port_forces_a_full_read(cfg):
    zot = _library(cfg)
    run_sync(cfg, zot)
    zot.library_id = "LIB-TWO"
    zot.calls.clear()
    stats = run_sync(cfg, zot)
    assert stats.full and zot.calls["changes"] == 2
    assert sync_state(cfg.out_dir)["library"] == "LIB-TWO"


# ---- a manager that cannot be read ---------------------------------------------------


def test_a_failed_listing_writes_nothing(cfg):
    zot = _library(cfg)
    run_sync(cfg, zot)
    state = (cfg.out_dir / "_sync.json").read_bytes()
    before = {p: p.read_bytes() for p in cfg.out_dir.rglob("record.json")}
    zot.put("ITEM0001", title="Changed")
    zot.fail.add("changes")
    with pytest.raises(LibraryError):
        run_sync(cfg, zot)
    assert (cfg.out_dir / "_sync.json").read_bytes() == state
    assert {p: p.read_bytes() for p in cfg.out_dir.rglob("record.json")} == before


def test_an_unreadable_item_holds_the_version_back_until_it_is_read(cfg):
    zot = _library(cfg)
    zot.note("ITEM0001", "NOTE0001")
    run_sync(cfg, zot)
    first = sync_state(cfg.out_dir)["version"]
    record = _folder(cfg, "ITEM0001", title="Paper 1") / "record.json"
    before = record.read_bytes()
    zot.attach("ITEM0001", "ATT00001")
    zot.put("ITEM0002", title="Also changed")
    zot.fail.add("ITEM0001")
    stats = run_sync(cfg, zot)
    assert stats.unread == 1 and stats.written == 1
    assert record.read_bytes() == before
    assert sync_state(cfg.out_dir)["version"] == first
    zot.fail.clear()
    stats = run_sync(cfg, zot)
    assert stats.unread == 0 and stats.written == 2
    assert sync_state(cfg.out_dir)["version"] == zot.version
    assert load_record(cfg.out_dir, "ITEM0001")["attachments"][0]["key"] == "ATT00001"


def test_a_manager_without_changes_is_told_to_snapshot(cfg):
    with pytest.raises(LibraryError, match="snapshot"):
        run_sync(cfg, object())


# ---- PDFs ---------------------------------------------------------------------------


def test_pdfs_all_copies_manager_pdfs_and_remembers_it_finished(cfg):
    zot = _library(cfg)
    zot.put("ITEM0001", collections=["COLA", "COLB"])
    zot.attach("ITEM0001", "ATT00001")
    stats = run_sync(cfg, zot, pdfs="all")
    assert stats.pdf_exports == 1 and zot.calls["export_pdf"] == 1
    alpha = _folder(cfg, "ITEM0001", "Alpha", "Paper 1")
    beta = _folder(cfg, "ITEM0001", "Beta", "Paper 1")
    (pdf,) = alpha.glob("*.pdf")
    assert pdf.read_bytes() == PDF and (beta / pdf.name).samefile(pdf)
    assert sync_state(cfg.out_dir)["pdfs_complete"] is True
    zot.calls.clear()
    assert run_sync(cfg, zot, pdfs="all").pdf_exports == 0
    assert zot.calls["export_pdf"] == 0


def test_pdfs_lazy_and_none_copy_nothing(cfg):
    for mode in ("lazy", "none"):
        zot = _library(cfg)
        zot.attach("ITEM0001", "ATT00001")
        stats = run_sync(cfg, zot, pdfs=mode, full=True)
        assert stats.pdf_exports == 0 and zot.calls["export_pdf"] == 0
        assert not sync_state(cfg.out_dir)["pdfs_complete"]


def test_switching_to_all_backfills_the_whole_mirror(cfg):
    zot = _library(cfg)
    zot.attach("ITEM0001", "ATT00001")
    run_sync(cfg, zot, pdfs="lazy")
    stats = run_sync(cfg, zot, pdfs="all")  # nothing changed in the library
    assert stats.written == 0 and stats.pdf_exports == 1


def test_a_cached_export_is_moved_in_instead_of_asked_for_again(cfg):
    zot = _library(cfg)
    zot.attach("ITEM0001", "ATT00001")
    cached = cfg.pdf_cache_dir / "ITEM0001.pdf"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(PDF)
    stats = run_sync(cfg, zot, pdfs="all")
    assert stats.pdf_exports == 1 and zot.calls["export_pdf"] == 0
    assert not cached.exists()
    assert any(_folder(cfg, "ITEM0001", title="Paper 1").glob("*.pdf"))


def test_a_stale_cached_export_is_not_trusted(cfg):
    zot = _library(cfg)
    zot.attach("ITEM0001", "ATT00001")
    cached = cfg.pdf_cache_dir / "ITEM0001.pdf"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"%PDF-1.4 an older file")
    run_sync(cfg, zot, pdfs="all")
    assert zot.calls["export_pdf"] == 1
    (pdf,) = _folder(cfg, "ITEM0001", title="Paper 1").glob("*.pdf")
    assert pdf.read_bytes() == PDF


def test_a_ghost_attachment_is_counted_not_retried_forever(cfg):
    zot = _library(cfg)
    zot.attach("ITEM0001", "ATT00001", bytes_=None)
    stats = run_sync(cfg, zot, pdfs="all")
    assert stats.pdf_missing == 1 and stats.pdf_exports == 0
    assert sync_state(cfg.out_dir)["pdfs_complete"] is True


def test_a_failed_export_leaves_the_backfill_open(cfg):
    zot = _library(cfg)
    zot.attach("ITEM0001", "ATT00001")
    zot.fail.add("export")
    stats = run_sync(cfg, zot, pdfs="all")
    assert stats.unread == 1
    assert not sync_state(cfg.out_dir)["pdfs_complete"]
    zot.fail.clear()
    assert run_sync(cfg, zot, pdfs="all").pdf_exports == 1
    assert sync_state(cfg.out_dir)["pdfs_complete"] is True


# ---- annotations ------------------------------------------------------------------------


def test_annotations_are_mirrored_and_follow_changes(cfg):
    zot = _library(cfg, n=1)
    zot.attach("ITEM0001", "ATT00001")
    zot.annotate("ATT00001", "ANNO0001", "first highlight")
    run_sync(cfg, zot)
    path = _folder(cfg, "ITEM0001", title="Paper 1") / "annotations.json"
    body = json.loads(path.read_text())
    assert [a["annotationText"] for a in body["annotations"]] == ["first highlight"]
    assert read_index(cfg.out_dir)["ITEM0001"]["annotations"] == ["ANNO0001"]

    zot.annotate("ATT00001", "ANNO0002", "second highlight")
    run_sync(cfg, zot)
    texts = [a["annotationText"] for a in json.loads(path.read_text())["annotations"]]
    assert sorted(texts) == ["first highlight", "second highlight"]

    zot.put("ITEM0001", title="Retitled")  # a change that reads no annotations
    run_sync(cfg, zot)
    moved = _folder(cfg, "ITEM0001", title="Retitled") / "annotations.json"
    assert len(json.loads(moved.read_text())["annotations"]) == 2
    assert len(read_index(cfg.out_dir)["ITEM0001"]["annotations"]) == 2

    zot.delete("ANNO0001")
    zot.delete("ANNO0002")
    run_sync(cfg, zot)
    assert not moved.exists()


def test_a_commands_first_refresh_does_not_start_the_whole_pdf_copy(cfg):
    zot = _library(cfg)
    zot.attach("ITEM0001", "ATT00001")
    stats = run_sync(cfg, zot, pdfs="all", backfill=False)  # first: a full read
    assert stats.full and stats.pdf_exports == 0 and zot.calls["export_pdf"] == 0
    assert not sync_state(cfg.out_dir)["pdfs_complete"]
    zot.attach("ITEM0002", "ATT00002")
    stats = run_sync(cfg, zot, pdfs="all", backfill=False)  # later: the changed item only
    assert stats.pdf_exports == 1
    assert not sync_state(cfg.out_dir)["pdfs_complete"]
    stats = run_sync(cfg, zot, pdfs="all")  # paperful sync finishes the job
    assert stats.pdf_exports == 1 and sync_state(cfg.out_dir)["pdfs_complete"] is True
