"""Library adapter selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperful.library import LibraryError, ZoteroBackend, get_backend
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
