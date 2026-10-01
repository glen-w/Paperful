"""A write to the manager leaves the mirror true; a failed read never empties it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pyzotero import errors as ze

from paperful.attach import AttachResult
from paperful.config import Config
from paperful.library import (
    LibraryError,
    LibraryReadError,
    MirroredBackend,
    ZoteroBackend,
    mirrored,
)
from paperful.mirror import forget_index, items_in_mirror, load_record, pdf_for_key
from paperful.snapshot import run_snapshot
from paperful.store import Manifest, Record, save_pdf
from paperful.zot import Collection, Item, is_pdf_attachment, item_from_json

COLS = {"COL1": Collection(key="COL1", name="BBNJ", parent=None, path="BBNJ")}


@pytest.fixture(autouse=True)
def _fresh_index():
    forget_index()
    yield
    forget_index()


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")


class FakeLibrary:
    """An in-memory manager with the calls a write-through needs."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.kids: dict[str, list[dict]] = {}
        self.trashed: list[str] = []
        self.reads = 0
        self.fail_reads = False
        self._n = 0

    def add(self, key: str, **data) -> None:
        body = {
            "itemType": "journalArticle",
            "title": "First title",
            "creators": [{"creatorType": "author", "lastName": "Smith"}],
            "date": "2020",
            "DOI": "10.1000/one",
            "collections": ["COL1"],
            "tags": [],
            "relations": {},
        }
        body.update(data)
        self.items[key] = {"key": key, "version": 1, "meta": {}, "data": body}
        self.kids.setdefault(key, [])

    # reads
    def collections(self):
        return COLS

    def raw_item(self, key):
        self.reads += 1
        if self.fail_reads:
            raise LibraryReadError("Zotero read failed")
        return self.items.get(key)

    def children(self, key):
        self.reads += 1
        if self.fail_reads:
            raise LibraryReadError("Zotero read failed")
        return list(self.kids.get(key, []))

    def item_from_raw(self, raw, children) -> Item:
        has_pdf = any(is_pdf_attachment(c.get("data") or {}) for c in children)
        return item_from_json(raw, COLS, None, has_pdf=has_pdf)

    # writes
    def apply_patch(self, key, fields):
        names = {"doi": "DOI"}
        for name, value in fields.items():
            self.items[key]["data"][names.get(name, name)] = value

    def attach(self, key, pdf_path, title=None, note=None):
        self._n += 1
        self.kids[key].append(
            {
                "key": f"ATT{self._n:05d}",
                "data": {
                    "itemType": "attachment",
                    "linkMode": "imported_file",
                    "contentType": "application/pdf",
                    "filename": Path(pdf_path).name,
                    "md5": "m" * 32,
                },
            }
        )
        return AttachResult(True, attachment_key=f"ATT{self._n:05d}", reason="success")

    def create_or_update_note(self, key, html, tag):
        self.kids[key].append(
            {
                "key": "NOTE0001",
                "data": {"itemType": "note", "note": html, "tags": [{"tag": tag}]},
            }
        )
        return "NOTE0001"

    def replace_prefixed_tag(self, key, prefix, tag):
        self.items[key]["data"]["tags"] = [{"tag": tag}]

    def relate_items(self, left, right):
        for a, b in ((left, right), (right, left)):
            self.items[a]["data"]["relations"] = {"dc:relation": f"http://zotero.org/users/0/items/{b}"}

    def create_parent(self, data):
        self._n += 1
        key = f"NEW{self._n:05d}"
        self.add(key, **data)
        return key

    def trash_item(self, key):
        self.trashed.append(key)

    def merge_into(self, keep, drop):
        self.kids[keep].extend(self.kids.pop(drop, []))
        self.items[keep]["data"]["abstractNote"] = "From the duplicate."
        self.trashed.append(drop)
        return {"moved": [], "fields": ["abstractNote"], "trashed_children": []}

    # a read the wrapper must pass through untouched
    def supports_write(self):
        return True


def _setup(cfg, key="ITEM0001", **data) -> tuple[FakeLibrary, MirroredBackend]:
    lib = FakeLibrary()
    lib.add(key, **data)
    backend = mirrored(cfg, lib)
    assert backend.refresh(key) is True
    return lib, backend


def test_mirrored_wraps_once_and_passes_reads_through(cfg):
    lib = FakeLibrary()
    backend = mirrored(cfg, lib)
    assert mirrored(cfg, backend) is backend
    assert backend.supports_write() is True
    assert backend.collections() is COLS
    with pytest.raises(AttributeError):
        backend.no_such_call


def test_apply_patch_updates_the_record_and_renames_the_folder(cfg):
    lib, backend = _setup(cfg)
    old = cfg.out_dir / "BBNJ" / "Smith - 2020 - First title -- ITEM0001"
    (old / "paper.pdf").write_bytes(b"%PDF-1.4")
    backend.apply_patch("ITEM0001", {"title": "Second title", "doi": "10.1000/two"})
    new = cfg.out_dir / "BBNJ" / "Smith - 2020 - Second title -- ITEM0001"
    assert not old.exists()
    assert (new / "paper.pdf").is_file()
    rec = json.loads((new / "record.json").read_text())
    assert rec["title"] == "Second title"
    assert rec["doi"] == "10.1000/two" and rec["library_doi"] == "10.1000/two"


def test_attach_adds_the_attachment_row(cfg):
    lib, backend = _setup(cfg)
    (item,) = items_in_mirror(cfg.out_dir)
    assert item.has_pdf is False
    pdf = cfg.out_dir / "BBNJ" / "Smith - 2020 - First title -- ITEM0001" / "p.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert backend.attach("ITEM0001", pdf).ok
    rec = load_record(cfg.out_dir, "ITEM0001")
    assert [row["linkMode"] for row in rec["attachments"]] == ["imported_file"]
    assert rec["attachments"][0]["md5"] == "m" * 32


def test_a_failed_attach_does_not_read_the_library(cfg):
    lib, backend = _setup(cfg)
    lib.attach = lambda *a, **k: AttachResult(False, reason="quota")
    before = lib.reads
    assert not backend.attach("ITEM0001", Path("x.pdf")).ok
    assert lib.reads == before


def test_note_tag_and_relation_writes_reach_the_record(cfg):
    lib, backend = _setup(cfg)
    lib.add("ITEM0002", title="Other paper", DOI="10.1000/other")
    backend.refresh("ITEM0002")
    backend.create_or_update_note("ITEM0001", "<p>summary</p>", "paperful-summary")
    backend.replace_prefixed_tag("ITEM0001", "paperful:", "paperful:oa")
    backend.relate_items("ITEM0001", "ITEM0002")
    folder = cfg.out_dir / "BBNJ" / "Smith - 2020 - First title -- ITEM0001"
    assert (folder / "notes" / "paperful-summary.html").read_text() == "<p>summary</p>"
    rec = load_record(cfg.out_dir, "ITEM0001")
    assert rec["tags"] == [{"tag": "paperful:oa"}]
    assert "ITEM0002" in rec["relations"]["dc:relation"]
    assert "ITEM0001" in load_record(cfg.out_dir, "ITEM0002")["relations"]["dc:relation"]


def test_create_parent_makes_a_folder(cfg):
    lib = FakeLibrary()
    backend = mirrored(cfg, lib)
    key = backend.create_parent({"title": "Brand new", "collections": ["COL1"]})
    rec = load_record(cfg.out_dir, key)
    assert rec["title"] == "Brand new"
    assert rec["collection_paths"] == ["BBNJ"]


def test_trash_marks_the_record_and_keeps_the_files(cfg):
    lib, backend = _setup(cfg)
    folder = cfg.out_dir / "BBNJ" / "Smith - 2020 - First title -- ITEM0001"
    (folder / "p.pdf").write_bytes(b"%PDF-1.4")
    backend.trash_item("ITEM0001")
    assert lib.trashed == ["ITEM0001"]
    assert (folder / "p.pdf").is_file()
    assert load_record(cfg.out_dir, "ITEM0001")["library"]["state"] == "trashed"
    assert items_in_mirror(cfg.out_dir) == []


def test_merge_marks_the_duplicate_and_refreshes_the_keeper(cfg):
    lib, backend = _setup(cfg, key="KEEP0001")
    lib.add("DROP0001", title="First title duplicate")
    backend.refresh("DROP0001")
    backend.merge_into("KEEP0001", "DROP0001")
    dropped = load_record(cfg.out_dir, "DROP0001")["library"]
    assert dropped["state"] == "trashed" and dropped["merged_into"] == "KEEP0001"
    assert load_record(cfg.out_dir, "KEEP0001")["abstract"] == "From the duplicate."
    assert [i.key for i in items_in_mirror(cfg.out_dir)] == ["KEEP0001"]


def test_a_failed_refresh_keeps_the_write_and_the_old_record(cfg):
    lib, backend = _setup(cfg)
    path = cfg.out_dir / "BBNJ" / "Smith - 2020 - First title -- ITEM0001" / "record.json"
    before = path.read_bytes()
    lib.fail_reads = True
    backend.apply_patch("ITEM0001", {"title": "Second title"})
    assert lib.items["ITEM0001"]["data"]["title"] == "Second title"
    assert path.read_bytes() == before
    assert backend.unrefreshed == ["ITEM0001"]
    lib.fail_reads = False
    assert backend.refresh("ITEM0001") is True
    assert backend.unrefreshed == []


def test_refresh_ignores_child_keys(cfg):
    lib, backend = _setup(cfg)
    lib.items["ATT00001"] = {"key": "ATT00001", "data": {"itemType": "attachment", "parentItem": "ITEM0001"}}
    assert backend.refresh("ATT00001") is False
    assert backend.unrefreshed == []


def test_snapshot_skips_an_unreadable_item_and_keeps_its_record(cfg):
    lib, backend = _setup(cfg)
    lib.kids["ITEM0001"].append(
        {"key": "NOTE0001", "data": {"itemType": "note", "note": "<p>n</p>", "tags": []}}
    )
    backend.refresh("ITEM0001")
    path = cfg.out_dir / "BBNJ" / "Smith - 2020 - First title -- ITEM0001" / "record.json"
    before = path.read_bytes()
    item = lib.item_from_raw(lib.items["ITEM0001"], [])
    lib.fail_reads = True
    stats = run_snapshot(cfg, lib, [item], pdfs="none", dry_run=False, manifest=None)
    assert stats.unread == 1 and stats.records == 0
    assert path.read_bytes() == before


def test_fetch_for_one_collection_survives_a_refresh_into_two(cfg):
    lib = FakeLibrary()
    cols = dict(COLS, COL2=Collection(key="COL2", name="Zed", parent=None, path="Zed"))
    lib.collections = lambda: cols
    lib.item_from_raw = lambda raw, kids: item_from_json(raw, cols, None)
    lib.add("ITEM0001", collections=["COL1", "COL2"])
    backend = mirrored(cfg, lib)
    scoped = item_from_json(lib.items["ITEM0001"], cols, {"COL2"})
    primary, _ = save_pdf(cfg.out_dir, scoped, b"%PDF-1.4 bytes", "d" * 32)
    from paperful.store import write_fetch_records

    write_fetch_records([primary], scoped, md5="d" * 32, source="unpaywall", fetched_url="u", pdf_doi=None)
    assert backend.refresh("ITEM0001")
    for collection in ("BBNJ", "Zed"):
        folder = cfg.out_dir / collection / "Smith - 2020 - First title -- ITEM0001"
        assert (folder / primary.name).is_file()
        assert json.loads((folder / "record.json").read_text())["fetch"]["source"] == "unpaywall"


def test_attach_finds_the_pdf_after_a_retitle(cfg):
    lib, backend = _setup(cfg)
    old = cfg.out_dir / "BBNJ" / "Smith - 2020 - First title -- ITEM0001"
    (old / "p.pdf").write_bytes(b"%PDF-1.4")
    manifest = Manifest(cfg.manifest_path)
    manifest.write(Record(itemKey="ITEM0001", status="ok", path=str(old / "p.pdf")))
    backend.apply_patch("ITEM0001", {"title": "Second title"})
    assert not (old / "p.pdf").exists()
    found = pdf_for_key(cfg.out_dir, "ITEM0001")
    assert found is not None and found.name == "p.pdf"


# ---- the Zotero adapter fails closed -------------------------------------------


class _Zot:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.created: list = []
        self.local_api_key = "k"

    def item(self, key):
        if self.error:
            raise self.error
        return {"key": key, "data": {"itemType": "journalArticle", "title": "T"}}

    def children(self, key):
        if self.error:
            raise self.error
        return []

    def collection_items_top(self, key):
        if self.error:
            raise self.error
        return []

    def everything(self, rows):
        return rows

    def create_items(self, payload):
        self.created.append(payload)
        return {"success": {"0": "NEWNOTE1"}}


class _ZL:
    def __init__(self, zot):
        self.zot = zot

    def collections(self):
        return {}


def _zotero(cfg, error=None) -> ZoteroBackend:
    backend = ZoteroBackend(cfg, _ZL(_Zot(error)))
    backend._ensure_write = lambda: None
    return backend


def test_a_missing_key_is_none_not_an_error(cfg):
    backend = _zotero(cfg, ze.ResourceNotFoundError("404"))
    assert backend.raw_item("GONE0001") is None
    assert backend.get_item("GONE0001") is None
    assert backend.children("GONE0001") == []


def test_a_transport_failure_raises(cfg):
    backend = _zotero(cfg, ConnectionError("refused"))
    for call in (
        lambda: backend.raw_item("ITEM0001"),
        lambda: backend.get_item("ITEM0001"),
        lambda: backend.children("ITEM0001"),
        lambda: backend.find_child_note_keys("ITEM0001", "t"),
        lambda: backend.read_child_note("ITEM0001", "t"),
        lambda: backend.find_collection_note_keys("COL1", "t"),
        lambda: backend.export_pdf(Item("ITEM0001", "journalArticle", "T", None, None, None, None, None), cfg.out_dir / "x.pdf"),
    ):
        with pytest.raises(LibraryReadError):
            call()
    assert issubclass(LibraryReadError, LibraryError)


def test_an_unreadable_parent_never_gets_a_second_note(cfg):
    """``could not list notes`` used to read as ``no note yet`` and post a duplicate."""
    backend = _zotero(cfg, ConnectionError("refused"))
    with pytest.raises(LibraryReadError):
        backend.create_or_update_note("ITEM0001", "<p>x</p>", "paperful-summary")
    with pytest.raises(LibraryReadError):
        backend.create_or_update_collection_note("COL1", "<p>x</p>", ["paperful-report"])
    assert backend.zl.zot.created == []
