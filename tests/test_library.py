"""Library adapter selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperful.library import (
    LibraryError,
    ZoteroBackend,
    collection_note_payload,
    created_item_key,
    get_backend,
    note_payload,
)
from tests.conftest import make_item


def test_get_backend_zotero_default(cfg):
    backend = get_backend(cfg)
    assert isinstance(backend, ZoteroBackend)


def test_get_backend_mendeley_returns_backend(cfg):
    from paperful.mendeley import MendeleyBackend

    cfg.manager = "mendeley"
    backend = get_backend(cfg)
    assert isinstance(backend, MendeleyBackend)


def test_get_backend_endnote_needs_a_library(cfg):
    cfg.manager = "endnote"
    with pytest.raises(LibraryError, match="[Ee]ndnote"):
        get_backend(cfg)


def test_get_backend_endnote(cfg, tmp_path):
    from paperful.endnote import EndNoteBackend

    cfg.manager = "endnote"
    cfg.endnote_library = tmp_path / "Lib.enl"
    assert isinstance(get_backend(cfg), EndNoteBackend)


def test_get_backend_unknown(cfg):
    cfg.manager = "jabref"
    with pytest.raises(LibraryError, match="Unknown"):
        get_backend(cfg)


def test_zotero_apply_patch_maps_fields(cfg):
    class FakeZot:
        def __init__(self):
            self.updated = None
            self.local_api_key = "k"

        def item(self, key):
            return {
                "data": {
                    "DOI": "10.1/old",
                    "title": "T",
                    "date": "2010",
                    "publicationTitle": "Old",
                    "version": 1,
                }
            }

        def update_item(self, raw):
            self.updated = raw

    class ZL:
        def __init__(self):
            self.zot = FakeZot()

        def ping(self):
            return {"supports_write": True}

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    backend.apply_patch(
        "ITEM0001", {"doi": "10.9/new", "publicationTitle": "Marine Policy"}
    )
    data = backend.zl.zot.updated["data"]
    assert data["DOI"] == "10.9/new"
    assert data["publicationTitle"] == "Marine Policy"


def test_zotero_export_pdf_dumps_attachment(cfg, tmp_path):
    dest = tmp_path / "cache" / "ITEM0001.pdf"

    class FakeZot:
        def children(self, key):
            return [
                {
                    "key": "ATT1",
                    "data": {
                        "contentType": "application/pdf",
                        "linkMode": "imported_file",
                        "filename": "p.pdf",
                    },
                }
            ]

        def dump(self, key, filename, folder):
            Path(folder).mkdir(parents=True, exist_ok=True)
            (Path(folder) / filename).write_bytes(b"%PDF-1.4")

    class ZL:
        def __init__(self):
            self.zot = FakeZot()

    backend = ZoteroBackend(cfg, ZL())
    out = backend.export_pdf(make_item(has_pdf=True), dest)
    assert out == dest and dest.is_file()


def test_note_payload_is_a_plain_note_item():
    payload = note_payload("<p>hi</p>", "paperful-summary", "ITEM0001")
    assert payload["itemType"] == "note"
    assert payload["parentItem"] == "ITEM0001"
    assert payload["note"] == "<p>hi</p>"
    assert payload["tags"] == [{"tag": "paperful-summary"}]


def test_created_item_key_from_write_api_dict():
    assert created_item_key({"success": {"0": "NOTE1"}}) == "NOTE1"
    assert created_item_key({"successful": {"0": {"key": "NOTE2"}}}) == "NOTE2"
    assert created_item_key([{"key": "NOTE3"}]) == "NOTE3"
    assert created_item_key({}) == ""


def test_create_or_update_note_builds_payload_without_template(cfg):
    class FakeZot:
        def __init__(self):
            self.created = None
            self.local_api_key = "k"

        def item_template(self, item_type):
            raise AssertionError("local API has no item_template")

        def children(self, key):
            return []

        def create_items(self, payload):
            self.created = payload
            return {"success": {"0": "NOTE1"}, "successful": {"0": {"key": "NOTE1"}}}

    class ZL:
        def __init__(self):
            self.zot = FakeZot()

        def ping(self):
            return {"supports_write": True}

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    key = backend.create_or_update_note("ITEM0001", "<p>sum</p>", "paperful-summary")
    assert key == "NOTE1"
    assert backend.zl.zot.created[0]["itemType"] == "note"
    assert backend.zl.zot.created[0]["parentItem"] == "ITEM0001"
    assert backend.zl.zot.created[0]["note"] == "<p>sum</p>"


def test_create_or_update_note_updates_existing(cfg):
    class FakeZot:
        def __init__(self):
            self.updated = None
            self.local_api_key = "k"

        def item_template(self, item_type):
            raise AssertionError("should update, not create")

        def children(self, key):
            return [
                {
                    "key": "NOTE1",
                    "data": {
                        "itemType": "note",
                        "note": "<p>old</p>",
                        "tags": [{"tag": "paperful-summary"}],
                    },
                }
            ]

        def item(self, key):
            return {"data": {"note": "<p>old</p>", "version": 1}}

        def update_item(self, raw):
            self.updated = raw

        def create_items(self, payload):
            raise AssertionError("existing note should be updated")

    class ZL:
        def __init__(self):
            self.zot = FakeZot()

        def ping(self):
            return {"supports_write": True}

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    key = backend.create_or_update_note("ITEM0001", "<p>new</p>", "paperful-summary")
    assert key == "NOTE1"
    assert backend.zl.zot.updated["data"]["note"] == "<p>new</p>"


def test_collection_note_payload_has_no_parent():
    payload = collection_note_payload("<p>r</p>", ["paperful-report", "paperful-report:bbnj"], "COL1")
    assert payload["itemType"] == "note"
    assert "parentItem" not in payload
    assert payload["collections"] == ["COL1"]
    assert payload["tags"] == [{"tag": "paperful-report"}, {"tag": "paperful-report:bbnj"}]


def test_read_child_note_returns_html(cfg):
    class FakeZot:
        def children(self, key):
            return [
                {
                    "key": "NOTE1",
                    "data": {
                        "itemType": "note",
                        "tags": [{"tag": "paperful-summary"}],
                    },
                }
            ]

        def item(self, key):
            return {"data": {"note": "<p>from zotero</p>"}}

    class ZL:
        def __init__(self):
            self.zot = FakeZot()

    backend = ZoteroBackend(cfg, ZL())
    assert backend.read_child_note("ITEM0001", "paperful-summary") == "<p>from zotero</p>"
    assert backend.read_child_note("ITEM0001", "other") is None


def test_create_collection_note_then_update(cfg):
    class FakeZot:
        def __init__(self):
            self.created = None
            self.updated = None
            self.local_api_key = "k"
            self._notes = []

        def everything(self, items):
            return items

        def collection_items_top(self, key):
            return list(self._notes)

        def create_items(self, payload):
            self.created = payload
            self._notes.append(
                {
                    "key": "R1",
                    "data": {
                        "itemType": "note",
                        "note": payload[0]["note"],
                        "tags": payload[0]["tags"],
                        "collections": payload[0]["collections"],
                    },
                }
            )
            return {"success": {"0": "R1"}}

        def item(self, key):
            return {"key": key, "data": {"note": "<p>old</p>", "tags": [], "version": 1}}

        def update_item(self, raw):
            self.updated = raw

    class ZL:
        def __init__(self):
            self.zot = FakeZot()

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    tags = ["paperful-report", "paperful-report:bbnj"]
    assert backend.create_or_update_collection_note("COL1", "<p>v1</p>", tags) == "R1"
    assert backend.zl.zot.created[0]["collections"] == ["COL1"]
    assert "parentItem" not in backend.zl.zot.created[0]
    assert backend.create_or_update_collection_note("COL1", "<p>v2</p>", tags) == "R1"
    assert backend.zl.zot.updated["data"]["note"] == "<p>v2</p>"
    assert backend.zl.zot.created[0]["note"] == "<p>v1</p>"


def test_collection_note_search_skips_child_notes(cfg):
    class FakeZot:
        def everything(self, items):
            return items

        def collection_items_top(self, key):
            return [
                {
                    "key": "CHILD",
                    "data": {
                        "itemType": "note",
                        "parentItem": "ITEM1",
                        "tags": [{"tag": "paperful-report:bbnj"}],
                    },
                },
                {
                    "key": "TOP",
                    "data": {
                        "itemType": "note",
                        "tags": [{"tag": "paperful-report:bbnj"}],
                    },
                },
            ]

    class ZL:
        def __init__(self):
            self.zot = FakeZot()

    backend = ZoteroBackend(cfg, ZL())
    assert backend.find_collection_note_keys("COL1", "paperful-report:bbnj") == ["TOP"]
