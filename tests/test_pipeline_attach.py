"""Parent-key remap helpers used when attach hits a stale manifest key."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from paperful.attach import AttachResult
from paperful.pipeline_attach import attach_after_remap, live_parent_key
from paperful.store import STATUS_ATTACHED, Manifest, Record
from tests.conftest import make_item


class _ListingAttacher:
    def __init__(self, items, *, via_zl=False):
        self.calls: list[tuple[str, Path]] = []
        if via_zl:
            self.zl = SimpleNamespace(items_in_scope=lambda _keys: list(items))
        else:
            self.items_in_scope = lambda _keys: list(items)

    def attach(self, key, path, note=None):
        self.calls.append((key, path))
        return AttachResult(True, attachment_key="ATT", reason="success", code="success")


def test_live_parent_key_returns_none_without_a_catalogue():
    pipe = SimpleNamespace(
        attacher=SimpleNamespace(),
        _parent_by_doi=None,
        _parent_by_title=None,
    )
    rec = Record(itemKey="OLD", status="ok", doi="10.1/x", title="T")
    assert live_parent_key(pipe, rec) is None


def test_live_parent_key_matches_doi_then_title(tmp_path):
    items = [
        make_item(key="BYDOI", doi="10.1000/abc", title="Other title", has_pdf=False),
        make_item(
            key="BYTITLE",
            doi=None,
            title="Exact Remap Title",
            has_pdf=True,
        ),
    ]
    attacher = _ListingAttacher(items)
    pipe = SimpleNamespace(
        attacher=attacher,
        _parent_by_doi=None,
        _parent_by_title=None,
        _pdf_parents=None,
    )
    assert (
        live_parent_key(
            pipe,
            Record(itemKey="OLD", status="ok", doi="10.1000/abc", title="ignored"),
        )
        == "BYDOI"
    )
    assert pipe._pdf_parents == {"BYTITLE"}

    pipe2 = SimpleNamespace(
        attacher=_ListingAttacher(items, via_zl=True),
        _parent_by_doi=None,
        _parent_by_title=None,
        _pdf_parents=None,
    )
    assert (
        live_parent_key(
            pipe2,
            Record(itemKey="OLD", status="ok", doi=None, title="Exact Remap Title"),
        )
        == "BYTITLE"
    )


def test_attach_after_remap_marks_already_present_pdf(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    manifest = Manifest(tmp_path / "manifest.jsonl")
    items = [make_item(key="NEW", doi="10.1/x", title="T", has_pdf=True)]
    attacher = _ListingAttacher(items)
    pipe = SimpleNamespace(
        attacher=attacher,
        manifest=manifest,
        _parent_by_doi=None,
        _parent_by_title=None,
        _pdf_parents=None,
    )
    rec = Record(
        itemKey="OLD",
        status="ok",
        doi="10.1/x",
        title="T",
        path=str(pdf),
        source="unpaywall",
        md5="abc",
    )
    res = attach_after_remap(pipe, rec, pdf, prior_reason="parent_missing")
    assert res.ok and res.code == "unchanged"
    assert rec.itemKey == "NEW"
    assert attacher.calls == []
    assert manifest.get("OLD").status == STATUS_ATTACHED
    assert "already present" in manifest.get("OLD").reason


def test_attach_after_remap_retries_when_parent_lacks_pdf(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    manifest = Manifest(tmp_path / "manifest.jsonl")
    items = [make_item(key="NEW", doi="10.1/y", title="T", has_pdf=False)]
    attacher = _ListingAttacher(items)
    pipe = SimpleNamespace(
        attacher=attacher,
        manifest=manifest,
        _parent_by_doi=None,
        _parent_by_title=None,
        _pdf_parents=None,
    )
    rec = Record(
        itemKey="OLD",
        status="ok",
        doi="10.1/y",
        title="T",
        path=str(pdf),
        source="unpaywall",
    )
    res = attach_after_remap(pipe, rec, pdf, prior_reason="parent_missing")
    assert res.ok
    assert attacher.calls == [("NEW", pdf)]
    assert rec.itemKey == "NEW"
    assert "remapped OLD→NEW" in res.reason
    assert manifest.get("OLD").status == STATUS_ATTACHED


def test_live_parent_key_returns_none_when_identifiers_miss():
    items = [make_item(key="OTHER", doi="10.9/z", title="Different", has_pdf=False)]
    pipe = SimpleNamespace(
        attacher=_ListingAttacher(items),
        _parent_by_doi=None,
        _parent_by_title=None,
        _pdf_parents=None,
    )
    assert (
        live_parent_key(
            pipe,
            Record(itemKey="OLD", status="ok", doi="10.1/missing", title="No match"),
        )
        is None
    )


def test_attach_after_remap_keeps_prior_reason_without_a_new_key(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    pipe = SimpleNamespace(
        attacher=_ListingAttacher([]),
        manifest=Manifest(tmp_path / "manifest.jsonl"),
        _parent_by_doi=None,
        _parent_by_title=None,
        _pdf_parents=None,
    )
    rec = Record(itemKey="OLD", status="ok", doi="10.1/gone", title="Gone")
    res = attach_after_remap(pipe, rec, pdf, prior_reason="parent_missing")
    assert not res.ok and res.code == "parent_missing"
    assert res.reason == "parent_missing"
    assert rec.itemKey == "OLD"


def test_attach_after_remap_initialises_pdf_parents_when_maps_are_seeded(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    manifest = Manifest(tmp_path / "manifest.jsonl")
    attacher = _ListingAttacher([])
    pipe = SimpleNamespace(
        attacher=attacher,
        manifest=manifest,
        _parent_by_doi={"10.1000/seeded": "NEW"},
        _parent_by_title={},
        _pdf_parents=None,
    )
    rec = Record(
        itemKey="OLD",
        status="ok",
        doi="10.1000/seeded",
        title="T",
        path=str(pdf),
        source="unpaywall",
    )
    res = attach_after_remap(pipe, rec, pdf, prior_reason="parent_missing")
    assert res.ok
    assert pipe._pdf_parents == {"NEW"}
    assert attacher.calls == [("NEW", pdf)]
    assert manifest.get("OLD").status == STATUS_ATTACHED
