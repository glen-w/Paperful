"""Mirror-first records for export (export_build.build_scope_records)."""

from __future__ import annotations

from pathlib import Path

from paperful.export_build import build_scope_records
from paperful.library import LibraryError
from paperful.store import item_dirname, record_path, write_json

from conftest import make_item


class _Backend:
    def __init__(self, *, children=None, export_pdf=None, boom_children=False, boom_pdf=False):
        self._children = children if children is not None else []
        self._export_pdf = export_pdf
        self.boom_children = boom_children
        self.boom_pdf = boom_pdf
        self.export_calls = 0

    def children(self, key: str):
        if self.boom_children:
            raise LibraryError("children down")
        return self._children

    def export_pdf(self, item, dest: Path):
        self.export_calls += 1
        if self.boom_pdf:
            raise LibraryError("pdf down")
        if self._export_pdf is not None:
            return self._export_pdf(item, dest)
        dest.write_bytes(b"%PDF-1.4 export")
        return dest


def _seed_record(cfg, item, **extra):
    path = record_path(cfg.out_dir / item.collection_paths[0] / item_dirname(item))
    write_json(
        path,
        {
            "item_type": "document",
            "title": "disk title",
            "creators": [{"creatorType": "author", "lastName": "Smith", "firstName": "Ada"}],
            "date": "2018",
            "publication_title": "Disk Journal",
            **extra,
        },
    )
    return path


def test_library_fields_overlay_disk_record_and_drop_uncollected(cfg):
    item = make_item(
        collection_paths=["Ocean", "_uncollected"],
        date="2019-04",
        publication_title="Marine Policy",
        pmid="999",
        abstract="A short abstract.",
    )
    _seed_record(cfg, item)
    records, copied = build_scope_records(cfg, _Backend(), [item])
    assert copied == 0
    rec = records[0]
    assert rec["title"] == item.title
    assert rec["doi"] == item.doi
    assert rec["item_type"] == "journalArticle"
    assert rec["date"] == "2019-04"
    assert rec["publication_title"] == "Marine Policy"
    assert rec["pmid"] == "999"
    assert rec["abstract"] == "A short abstract."
    assert rec["collection_paths"] == ["Ocean"]
    assert rec["creators"][0]["lastName"] == "Smith"
    assert rec["notes"] == []


def test_year_fills_date_when_item_and_record_have_none(cfg):
    item = make_item(date=None, year=2021, collection_paths=["Col"])
    path = record_path(cfg.out_dir / "Col" / item_dirname(item))
    write_json(path, {"title": "disk", "date": ""})
    records, _ = build_scope_records(cfg, _Backend(), [item])
    assert records[0]["date"] == "2021"


def test_pdf_copy_prefers_local_file_over_backend(cfg, tmp_path: Path):
    local = tmp_path / "local.pdf"
    local.write_bytes(b"%PDF-1.4 local")
    item = make_item(has_pdf=True, pdf_path=str(local))
    backend = _Backend()
    pdf_dir = tmp_path / "export"
    pdf_dir.mkdir()
    records, copied = build_scope_records(cfg, backend, [item], pdf_dir=pdf_dir)
    assert copied == 1
    assert backend.export_calls == 0
    exported = Path(records[0]["pdfs"][0])
    assert exported.is_file()
    assert exported.read_bytes() == b"%PDF-1.4 local"


def test_pdf_falls_back_to_backend_and_swallows_library_error(cfg, tmp_path: Path):
    item = make_item(has_pdf=True, pdf_path=None)
    pdf_dir = tmp_path / "export"
    pdf_dir.mkdir()
    records, copied = build_scope_records(cfg, _Backend(), [item], pdf_dir=pdf_dir)
    assert copied == 1
    assert Path(records[0]["pdfs"][0]).read_bytes().startswith(b"%PDF")

    records, copied = build_scope_records(
        cfg, _Backend(boom_pdf=True), [item], pdf_dir=pdf_dir
    )
    assert copied == 0
    assert records[0]["pdfs"] == []


def test_notes_are_optional_and_a_children_failure_is_empty(cfg):
    kids = [
        {
            "key": "NOTE1",
            "data": {
                "itemType": "note",
                "note": "<p>hello</p>",
                "tags": [{"tag": "paperful-summary"}],
            },
        },
        {"key": "ATT1", "data": {"itemType": "attachment", "note": "skip"}},
        {"key": "EMPTY", "data": {"itemType": "note", "note": ""}},
    ]
    item = make_item()
    records, _ = build_scope_records(cfg, _Backend(children=kids), [item])
    assert records[0]["notes"] == [
        {"file": "NOTE1.html", "html": "<p>hello</p>", "tag": "paperful-summary"}
    ]
    bare, _ = build_scope_records(cfg, _Backend(children=kids), [item], include_notes=False)
    assert bare[0]["notes"] == []
    failed, _ = build_scope_records(cfg, _Backend(boom_children=True), [item])
    assert failed[0]["notes"] == []
