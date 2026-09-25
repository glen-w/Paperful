"""Preprint and published paper share one citeable work."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.attach import AttachResult
from paperful.resolve import VersionLink, WorkMeta
from paperful.snowball.candidate import Candidate
from paperful.snowball.command import _mark_exists
from paperful.snowball.ingest import create_new
from paperful.versions import apply_versions, classify_versions, merge_preprint_extra
from paperful.zot import Item

PDF = b"%PDF-1.4\n" + b"x" * 2000


def _item(**overrides) -> Item:
    base = dict(
        key="PRE1",
        item_type="preprint",
        title="Attention is all you need",
        doi="10.1101/2020.01.01.123456",
        arxiv_id="1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        year=2017,
        first_author="Vaswani",
        extra="",
        date="2017",
        publication_title=None,
        has_pdf=True,
        date_added="2017-06-01T00:00:00Z",
    )
    base.update(overrides)
    return Item(**base)


def _link() -> VersionLink:
    return VersionLink(
        preprint_doi="10.1101/2020.01.01.123456",
        published_doi="10.1038/s41586-020-2649-2",
        source="crossref",
        arxiv_id="1706.03762",
        item_type="journalArticle",
        published=WorkMeta(
            doi="10.1038/s41586-020-2649-2",
            title="Attention is all you need",
            year=2020,
            date="2020-06-01",
            venue="Nature",
            source="crossref",
        ),
    )


class _Lib:
    def __init__(self, items: list[Item], pdfs: dict[str, bytes] | None = None):
        self.items = {item.key: item for item in items}
        self.pdfs = pdfs or {}
        self.attached: list[tuple[str, str | None]] = []
        self.trashed: list[str] = []
        self.related: list[tuple[str, str]] = []

    def apply_patch(self, key: str, fields: dict) -> None:
        item = self.items[key]
        if "doi" in fields:
            item.doi = fields["doi"]
        if "title" in fields:
            item.title = fields["title"]
        if "date" in fields:
            item.date = fields["date"]
        if "publicationTitle" in fields:
            item.publication_title = fields["publicationTitle"]
        if "itemType" in fields:
            item.item_type = fields["itemType"]
        if "extra" in fields:
            item.extra = fields["extra"]

    def get_item(self, key: str) -> Item | None:
        return self.items.get(key)

    def attach(self, key: str, path: Path, title: str | None = None, note: str | None = None):
        del note
        assert path.is_file()
        self.attached.append((key, title))
        self.items[key].has_pdf = True
        return AttachResult(True, reason="success", code="success")

    def export_pdf(self, item: Item, dest: Path) -> Path | None:
        blob = self.pdfs.get(item.key)
        if not blob:
            return None
        dest.write_bytes(blob)
        return dest

    def relate_items(self, left: str, right: str) -> None:
        self.related.append((left, right))

    def trash_item(self, key: str) -> None:
        self.trashed.append(key)


def test_upgrade_keeps_preprint_and_published_pdf(tmp_path: Path):
    preprint = _item()
    sibling = _item(
        key="PUB1",
        item_type="journalArticle",
        doi="10.1038/s41586-020-2649-2",
        arxiv_id=None,
        has_pdf=True,
        date_added="2020-06-02T00:00:00Z",
        year=2020,
    )
    lib = _Lib([preprint, sibling], pdfs={"PUB1": PDF, "PRE1": PDF})
    rows = classify_versions([preprint, sibling], lambda _doi: _link())
    assert len(rows) == 1
    assert rows[0].needs_review is False
    assert rows[0].item_key == "PRE1"
    assert rows[0].sibling_key == "PUB1"

    applied, errors = apply_versions(
        lib,
        rows,
        fetch_published=lambda _doi: None,
        audit_path=tmp_path / "versions-applied.jsonl",
        scope="Col",
        pack=tmp_path / "pack.json",
    )
    assert applied == 1
    assert errors == []
    assert preprint.doi == "10.1038/s41586-020-2649-2"
    assert preprint.item_type == "journalArticle"
    assert preprint.date == "2020-06-01"
    assert preprint.publication_title == "Nature"
    assert "arXiv: 1706.03762" in preprint.extra
    assert "Preprint DOI: 10.1101/2020.01.01.123456" in preprint.extra
    assert ("PRE1", "Published PDF") in lib.attached
    assert ("PRE1", "Preprint PDF") not in lib.attached
    assert lib.related == [("PRE1", "PUB1")]
    assert lib.trashed == ["PUB1"]


def test_older_published_item_keeps_preprint_pdf(tmp_path: Path):
    published = _item(
        key="PUB1",
        item_type="journalArticle",
        doi="10.1038/s41586-020-2649-2",
        arxiv_id=None,
        has_pdf=True,
        date_added="2016-01-01T00:00:00Z",
        year=2020,
    )
    preprint = _item(date_added="2020-06-02T00:00:00Z")
    lib = _Lib([published, preprint], pdfs={"PRE1": PDF, "PUB1": PDF})
    rows = classify_versions([published, preprint], lambda _doi: _link())
    assert rows[0].item_key == "PUB1"
    apply_versions(
        lib,
        rows,
        fetch_published=lambda _doi: None,
        audit_path=tmp_path / "versions-applied.jsonl",
        scope="Col",
        pack=tmp_path / "pack.json",
    )
    assert ("PUB1", "Preprint PDF") in lib.attached
    assert ("PUB1", "Published PDF") not in lib.attached
    assert "Preprint DOI: 10.1101/2020.01.01.123456" in published.extra
    assert lib.trashed == ["PRE1"]


def test_sibling_stays_when_published_pdf_is_missing(tmp_path: Path):
    preprint = _item(has_pdf=True)
    sibling = _item(
        key="PUB1",
        item_type="journalArticle",
        doi="10.1038/s41586-020-2649-2",
        arxiv_id=None,
        has_pdf=False,
        date_added="2020-06-02T00:00:00Z",
    )
    lib = _Lib([preprint, sibling])
    rows = classify_versions([preprint, sibling], lambda _doi: _link())
    _applied, errors = apply_versions(
        lib,
        rows,
        fetch_published=lambda _doi: None,
        audit_path=tmp_path / "versions-applied.jsonl",
        scope="Col",
        pack=tmp_path / "pack.json",
    )
    assert lib.trashed == []
    assert any("sibling left in place" in err for err in errors)
    assert preprint.doi == "10.1038/s41586-020-2649-2"


def test_title_near_match_is_review_only(tmp_path: Path):
    left = _item()
    right = _item(
        key="PUB1",
        item_type="journalArticle",
        doi="10.1038/s41586-020-2649-2",
        arxiv_id=None,
        year=2018,
        date_added="2018-01-01T00:00:00Z",
    )
    rows = classify_versions([left, right], lambda _doi: None)
    assert len(rows) == 1
    assert rows[0].needs_review is True
    lib = _Lib([left, right])
    apply_versions(
        lib,
        rows,
        fetch_published=lambda _doi: None,
        audit_path=tmp_path / "versions-applied.jsonl",
        scope="Col",
        pack=tmp_path / "pack.json",
    )
    assert left.doi == "10.1101/2020.01.01.123456"
    assert lib.trashed == []


def test_snowball_marks_version_and_does_not_create(tmp_path: Path):
    del tmp_path
    row = Candidate(
        "r",
        {"type": "doi", "value": "x"},
        1,
        "refs",
        {"doi": "10.1038/s41586-020-2649-2"},
        {"title": "Attention is all you need", "year": 2020},
        "cited",
        "new",
        {},
        "auto",
    )

    def lookup(doi, title, year=None):
        del title, year
        if doi and doi.startswith("10.1101/"):
            return ("PRE1", "doi")
        return None

    _mark_exists([row], lookup, version_of=lambda _doi: _link())
    assert row.status == "version"
    assert row.exists_match["item_key"] == "PRE1"

    class Backend:
        def ensure_collection_path(self, path: str) -> str:
            return path

        def create_parent(self, data: dict) -> str:
            raise AssertionError(data)

    _items, counts = create_new(Backend(), [row], "Inbox")
    assert counts["created"] == 0
    assert counts["skipped_exists"] == 1


def test_version_pack_schema(tmp_path: Path):
    from paperful.versions import SCHEMA, write_pack

    preprint = _item()
    rows = classify_versions([preprint], lambda _doi: _link())
    json_path, md_path = write_pack(tmp_path, "BBNJ", rows, n_items=1, stamp="20260925T120000Z")
    pack = json.loads(json_path.read_text())
    assert pack["schema"] == SCHEMA == "paperful.version_pack.v1"
    row = pack["proposals"][0]
    assert row["item_key"] == "PRE1"
    assert row["published_doi"] == "10.1038/s41586-020-2649-2"
    assert row["preprint_doi"] == "10.1101/2020.01.01.123456"
    assert row["primary_pdf"] == "published"
    assert row["after"]["doi"] == row["published_doi"]
    assert "Preprint DOI:" in row["after"]["extra"]
    assert md_path.is_file()
    assert "10.1038/s41586-020-2649-2" in md_path.read_text()


def test_merge_preprint_extra_is_idempotent():
    once = merge_preprint_extra("", arxiv_id="1706.03762", preprint_doi="10.1101/2020.01.01.123456")
    twice = merge_preprint_extra(
        once, arxiv_id="1706.03762", preprint_doi="10.1101/2020.01.01.123456"
    )
    assert once == twice
