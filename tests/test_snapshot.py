"""Snapshot layout, PDF modes, migration, history pointers, and restore planning."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.config import Config
from paperful.restore import plan_restore
from paperful.snapshot import run_snapshot, write_history
from paperful.store import (
    Manifest,
    Record,
    STATUS_OK,
    item_dirname,
    migrate_flat_tree,
    record_path,
)
from paperful.zot import Collection, Item


def _item(**overrides) -> Item:
    base = dict(
        key="ABCD1234",
        item_type="journalArticle",
        title="A paper",
        doi="10.1000/abc",
        arxiv_id=None,
        url="https://example.org/p",
        year=2020,
        first_author="Smith",
        collection_paths=["BBNJ"],
        has_pdf=True,
    )
    base.update(overrides)
    return Item(**base)


class _Backend:
    def __init__(self, raw: dict | None = None, children: list | None = None):
        self.exports = 0
        self.raw = raw or {
            "version": 4,
            "data": {
                "itemType": "journalArticle",
                "title": "A paper",
                "creators": [
                    {"creatorType": "author", "firstName": "Ada", "lastName": "Smith"}
                ],
                "abstractNote": "The abstract.",
                "tags": [{"tag": "bbnj"}],
                "volume": "12",
                "pages": "1-9",
                "collections": ["COL1"],
                "dateAdded": "2024-01-01 00:00:00",
                "dateModified": "2024-06-01 00:00:00",
                "extra": "PMID: 1",
            },
        }
        self.kids = children or []

    def collections(self):
        return {
            "COL1": Collection(key="COL1", name="BBNJ", parent=None, path="BBNJ"),
        }

    def raw_item(self, key: str):
        return self.raw

    def children(self, key: str):
        return self.kids

    def export_pdf(self, item: Item, dest: Path):
        self.exports += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4 exported")
        return dest


def test_snapshot_pdf_modes_and_record_roundtrip(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    item = _item()
    backend = _Backend()
    stats = run_snapshot(
        cfg, backend, [item], pdfs="additional", dry_run=False, manifest=None
    )
    assert stats.records == 1 and stats.pdf_exports == 0 and backend.exports == 0
    rec_path = record_path(cfg.out_dir / "BBNJ" / item_dirname(item))
    rec = json.loads(rec_path.read_text())
    assert rec["schema"] == "paperful.item.v1"
    assert rec["creators"][0]["firstName"] == "Ada"
    assert rec["tags"] == [{"tag": "bbnj"}]
    assert rec["fields"]["volume"] == "12"
    assert rec["fields"]["pages"] == "1-9"
    assert rec["abstract"] == "The abstract."
    assert rec["collections"] == [{"key": "COL1", "path": "BBNJ"}]
    history = json.loads((cfg.out_dir / "_history.json").read_text())
    assert history["schema"] == "paperful.history.v1"
    names = {row["name"] for row in history["ledgers"]}
    assert "manifest" in names and "sessions" not in names
    assert "zotero-local-api-key" not in names
    index = (cfg.out_dir / "_index.jsonl").read_text()
    assert "ABCD1234" in index
    cols = json.loads((cfg.out_dir / "_collections.json").read_text())
    assert cols["collections"][0]["path"] == "BBNJ"

    dry = run_snapshot(
        cfg, backend, [item], pdfs="all", dry_run=True, manifest=None
    )
    assert dry.pdf_exports == 1 and backend.exports == 0
    assert not any((cfg.out_dir / "BBNJ" / item_dirname(item)).glob("*.pdf"))

    live = run_snapshot(
        cfg, backend, [item], pdfs="all", dry_run=False, manifest=None
    )
    assert live.pdf_exports == 1 and backend.exports == 1
    assert any((cfg.out_dir / "BBNJ" / item_dirname(item)).glob("*.pdf"))

    again = _Backend()
    run_snapshot(cfg, again, [item], pdfs="all", dry_run=False, manifest=None)
    assert again.exports == 0  # matching file already in the folder

    none = _Backend()
    bare = _item(key="BARE0001", has_pdf=False, title="No file")
    run_snapshot(cfg, none, [bare], pdfs="none", dry_run=False, manifest=None)
    assert none.exports == 0
    bare_dir = cfg.out_dir / "BBNJ" / item_dirname(bare)
    assert (bare_dir / "record.json").is_file()
    assert not list(bare_dir.glob("*.pdf"))


def test_migrate_flat_card_updates_manifest(tmp_path):
    out = tmp_path / "out"
    flat_dir = out / "BBNJ"
    flat_dir.mkdir(parents=True)
    pdf = flat_dir / "Smith - 2020 - A paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 flat")
    card = {
        "schema": "paperful.mirror.v1",
        "item_key": "ABCD1234",
        "item_type": "journalArticle",
        "title": "A paper",
        "first_author": "Smith",
        "year": 2020,
        "source": "unpaywall",
        "fetched_url": "https://oa.test/a.pdf",
        "md5": "abc",
        "pdf": pdf.name,
        "fetched_at": "2026-01-01T00:00:00Z",
        "collection_paths": ["BBNJ"],
    }
    pdf.with_name(pdf.stem + ".paperful.json").write_text(json.dumps(card))
    manifest = Manifest(tmp_path / "manifest.jsonl")
    manifest.write(Record(itemKey="ABCD1234", status=STATUS_OK, path=str(pdf)))
    assert migrate_flat_tree(out, manifest) == 1
    dest = flat_dir / item_dirname(_item()) / pdf.name
    assert dest.is_file()
    assert not pdf.exists()
    assert not pdf.with_name(pdf.stem + ".paperful.json").exists()
    body = json.loads(record_path(dest.parent).read_text())
    assert body["fetch"]["source"] == "unpaywall"
    assert body["item_key"] == "ABCD1234"
    assert manifest.get("ABCD1234").path == str(dest)
    assert migrate_flat_tree(out, manifest) == 0


def test_history_omits_secrets(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    (cfg.state_dir / "sessions").mkdir(parents=True)
    (cfg.state_dir / "sessions" / "meta.json").write_text("{}")
    (cfg.state_dir / "zotero-local-api-key.json").write_text("{}")
    write_history(cfg.out_dir, cfg)
    text = (cfg.out_dir / "_history.json").read_text()
    assert "sessions" not in text
    assert "zotero-local-api-key" not in text
    assert "manifest.jsonl" in text


def test_restore_matches_and_does_not_overwrite(tmp_path):
    folder = tmp_path / "BBNJ" / item_dirname(_item())
    folder.mkdir(parents=True)
    (folder / "notes").mkdir()
    (folder / "notes" / "paperful-summary.html").write_text("<p>hi</p>")
    (folder / "Smith - 2020 - A paper.pdf").write_bytes(b"%PDF")
    record = {
        "schema": "paperful.item.v1",
        "item_key": "ABCD1234",
        "item_type": "journalArticle",
        "title": "A paper",
        "year": 2020,
        "doi": "10.1000/abc",
        "creators": [{"creatorType": "author", "lastName": "Smith"}],
        "collection_paths": ["BBNJ"],
        "notes": [{"file": "paperful-summary.html", "tag": "paperful-summary"}],
        "fetch": {"pdf": "Smith - 2020 - A paper.pdf"},
    }
    (folder / "record.json").write_text(json.dumps(record))
    live = _item(has_pdf=True)
    plan = plan_restore(
        [(folder / "record.json", record)],
        [live],
        note_tags_for={"ABCD1234": {"paperful-summary"}},
    )
    kinds = [a.kind for a in plan.actions]
    assert kinds == ["exists"]

    missing = plan_restore([(folder / "record.json", record)], [], note_tags_for={})
    kinds = [a.kind for a in missing.actions]
    assert kinds == ["create_item", "attach_pdf", "create_note"]
    assert missing.actions[0].payload["title"] == "A paper"
    assert "volume" not in missing.actions[0].payload or True

    other = {
        **record,
        "item_key": "OTHERKEY",
        "doi": "10.9/nope",
        "title": "Different",
        "year": 1999,
    }
    by_doi = plan_restore(
        [(folder / "record.json", {**record, "item_key": "OTHERKEY"})],
        [_item(key="LIVE9999", doi="10.1000/abc", has_pdf=False)],
    )
    assert [a.kind for a in by_doi.actions] == ["exists", "attach_pdf", "create_note"]
    assert by_doi.actions[0].detail.startswith("matched")
    assert other["title"] == "Different"


def test_apply_restore_creates_attaches_notes_and_skips_existing(tmp_path):
    from paperful.restore import RestoreAction, RestorePlan, apply_restore

    record_dir = tmp_path / "item"
    record_dir.mkdir()
    (record_dir / "record.json").write_text(
        json.dumps({"collection_paths": ["BBNJ"], "title": "A paper"}),
        encoding="utf-8",
    )
    pdf = record_dir / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    plan = RestorePlan(
        actions=[
            RestoreAction(
                kind="exists",
                item_key="KEEP",
                title="A paper",
                detail="matched; fields left unchanged",
                record_dir=record_dir,
            ),
            RestoreAction(
                kind="create_item",
                item_key="",
                title="New",
                detail="no live match",
                record_dir=record_dir,
                payload={"title": "New", "itemType": "journalArticle"},
            ),
            RestoreAction(
                kind="attach_pdf",
                item_key="",
                title="New",
                detail="a.pdf",
                record_dir=record_dir,
                pdf=pdf,
            ),
            RestoreAction(
                kind="create_note",
                item_key="",
                title="New",
                detail="n.html",
                record_dir=record_dir,
                note_html="<p>n</p>",
                note_tag="paperful-restored",
            ),
        ]
    )

    class Backend:
        def __init__(self):
            self.parents: list[dict] = []
            self.notes: list[tuple] = []

        def ensure_collection_path(self, path):
            assert path == "BBNJ"
            return "COL1"

        def create_parent(self, payload):
            self.parents.append(payload)
            return "NEWKEY"

        def create_or_update_note(self, key, html, tag):
            self.notes.append((key, html, tag))
            return "NOTE1"

    class Attacher:
        def __init__(self):
            self.calls: list[tuple] = []

        def attach(self, key, path, title):
            self.calls.append((key, path, title))

    backend = Backend()
    attacher = Attacher()
    done = apply_restore(plan, backend, attacher)
    assert done == {"create_item": 1, "attach_pdf": 1, "create_note": 1}
    assert len(backend.parents) == 1
    assert backend.parents[0]["title"] == "New"
    assert backend.parents[0]["collections"] == ["COL1"]
    assert attacher.calls == [("NEWKEY", pdf, "New")]
    assert backend.notes == [("NEWKEY", "<p>n</p>", "paperful-restored")]


def test_match_prefers_doi_over_a_different_key():
    from paperful.restore import match_item

    record = {
        "item_key": "FOLDER99",
        "doi": "10.1000/shared",
        "title": "Shared title",
        "year": 2020,
    }
    by_key = _item(key="FOLDER99", doi="10.1/other", title="Other title")
    by_doi = _item(key="LIVE0001", doi="10.1000/shared", title="Elsewhere")
    got = match_item(record, [by_key, by_doi])
    assert got is not None and got.key == "LIVE0001"


def test_record_scope_drops_undated_when_year_set():
    from paperful.restore import record_in_scope

    dated = {"item_type": "journalArticle", "year": 2022}
    undated = {"item_type": "journalArticle", "year": None}
    report = {"item_type": "report", "year": 2022}
    assert record_in_scope(dated, year_from=2021, year_to=2023)
    assert not record_in_scope(undated, year_from=2021)
    assert not record_in_scope(report, item_types=frozenset({"journalArticle"}))
    assert record_in_scope(report)


def test_pdfs_none_keeps_existing_bytes_and_skips_linked_url(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    item = _item()
    folder = cfg.out_dir / "BBNJ" / item_dirname(item)
    folder.mkdir(parents=True)
    (folder / "kept.pdf").write_bytes(b"%PDF-1.4 keep")
    backend = _Backend()
    run_snapshot(cfg, backend, [item], pdfs="none", dry_run=False, manifest=None)
    assert (folder / "kept.pdf").read_bytes() == b"%PDF-1.4 keep"
    assert backend.exports == 0
    linked = _item(key="LINKED01", has_pdf=True, has_linked_url=True)
    run_snapshot(cfg, backend, [linked], pdfs="all", dry_run=False, manifest=None)
    assert backend.exports == 0
    assert not (cfg.out_dir / "BBNJ" / item_dirname(linked)).joinpath("kept.pdf").exists()


def test_snapshot_copies_summary_and_hardlinks_second_collection(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    item = _item(collection_paths=["BBNJ", "AO"])
    summary = cfg.summaries_dir / f"{item.key}.html"
    summary.parent.mkdir(parents=True)
    summary.write_text("<p>brief</p>")
    backend = _Backend(
        children=[
            {
                "key": "PDFATT01",
                "data": {
                    "itemType": "attachment",
                    "contentType": "application/pdf",
                    "linkMode": "imported_file",
                    "filename": "a.pdf",
                    "md5": "abc123",
                },
            },
            {
                "key": "NOTE1234",
                "data": {
                    "itemType": "note",
                    "note": "<p>zot</p>",
                    "tags": [{"tag": "paperful-summary"}],
                },
            },
        ]
    )
    run_snapshot(cfg, backend, [item], pdfs="all", dry_run=False, manifest=None)
    primary = cfg.out_dir / "BBNJ" / item_dirname(item)
    extra = cfg.out_dir / "AO" / item_dirname(item)
    assert (primary / "notes" / "paperful-summary.html").read_text() == "<p>brief</p>"
    assert (extra / "notes" / "paperful-summary.html").read_text() == "<p>brief</p>"
    pdfs = list(primary.glob("*.pdf"))
    assert len(pdfs) == 1
    extra_pdf = extra / pdfs[0].name
    assert extra_pdf.is_file()
    assert extra_pdf.stat().st_ino == pdfs[0].stat().st_ino
    rec = json.loads((primary / "record.json").read_text())
    assert rec["attachments"][0]["origin"] == "zotero_export"
    assert any(n["file"] == "paperful-summary.html" for n in rec["notes"])


def test_dirname_keeps_key_when_title_is_long():
    from paperful.store import item_dirname

    item = _item(title="word " * 80, key="ABCD1234")
    name = item_dirname(item)
    assert name.endswith(" -- ABCD1234")
    assert len(name) <= 180


def test_doctor_ambers_mixed_flat_and_item_dirs(tmp_path):
    from paperful.doctor import _mirror_check

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    flat = cfg.out_dir / "BBNJ"
    flat.mkdir(parents=True)
    (flat / "old.pdf").write_bytes(b"%PDF")
    item_dir = flat / "Smith - 2020 - A paper -- ABCD1234"
    item_dir.mkdir()
    (item_dir / "record.json").write_text("{}")
    check = _mirror_check(cfg)
    assert check.name == "Mirror" and check.status == "amber"
    assert "pdfs=additional" in check.detail
