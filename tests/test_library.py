"""Library adapter selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperful.library import (
    LibraryError,
    ZoteroBackend,
    created_item_key,
    get_backend,
    note_payload,
)
from tests.conftest import make_item


def test_get_backend_zotero_default(cfg):
    backend = get_backend(cfg)
    assert isinstance(backend, ZoteroBackend)


def test_get_backend_mendeley_not_implemented(cfg):
    cfg.manager = "mendeley"
    with pytest.raises(LibraryError, match="Mendeley"):
        get_backend(cfg)


def test_get_backend_unknown(cfg):
    cfg.manager = "endnote"
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
