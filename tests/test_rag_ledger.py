"""The ingest ledger and the per-item plan."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from paperful.rag.ledger import (
    ACTION_META,
    ACTION_PDF,
    ACTION_REMOVE,
    ACTION_SKIP,
    ACTION_STUB,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_STUB,
    Ledger,
    LedgerRow,
    PdfStat,
    describe,
    pick_pdf,
    plan_item,
    text_sha,
)
from paperful.store import MirrorEntry

PARAMS = "light1/c1/2048/256"
NAME = "Silva - 2021 - Deep sea governance -- ABCD1234"


def _entry(*, abstract: str = "An abstract.", pdfs=(), **record) -> MirrorEntry:
    rec = {
        "item_key": "ABCD1234",
        "item_type": "journalArticle",
        "version": 3,
        "title": "Deep sea governance",
        "creators": [{"lastName": "Silva"}],
        "year": 2021,
        "abstract": abstract,
    }
    rec.update(record)
    return MirrorEntry(key="ABCD1234", dirs=[f"ocean/{NAME}"], record=rec, pdfs=list(pdfs))


PDF = PdfStat(path=Path("/mirror/a.pdf"), size=100, mtime_ns=5)


def _row(entry: MirrorEntry, **over) -> LedgerRow:
    row = LedgerRow(key=entry.key, params=PARAMS, **describe(entry))
    for name, value in over.items():
        setattr(row, name, value)
    return row


def _pdf_row(entry, **over) -> LedgerRow:
    base = dict(
        status=STATUS_OK, source="pdf", pdf_size=100, pdf_mtime_ns=5, pdf_sha256="aaa"
    )
    base.update(over)
    return _row(entry, **base)


def _stub_row(entry, **over) -> LedgerRow:
    base = dict(status=STATUS_STUB, source="abstract", abstract_sha=text_sha("An abstract."))
    base.update(over)
    return _row(entry, **base)


def _plan(entry, row, *, pdf=None, **kw):
    kw.setdefault("params", PARAMS)
    kw.setdefault("ocr_available", True)
    kw.setdefault("hasher", lambda path: "aaa")
    return plan_item(entry, row, pdf=pdf, **kw)


# ---- plan_item ---------------------------------------------------------------


def test_new_items():
    assert _plan(_entry(), None, pdf=PDF).action == ACTION_PDF
    assert _plan(_entry(), None).action == ACTION_STUB
    assert _plan(_entry(abstract=""), None).action == ACTION_SKIP
    assert _plan(_entry(), None, abstracts=False).action == ACTION_SKIP


def test_unchanged_pdf_is_skipped_without_hashing():
    entry = _entry()

    def hasher(path):
        raise AssertionError("stat matched; the file must not be read")

    plan = _plan(entry, _pdf_row(entry), pdf=PDF, hasher=hasher)
    assert (plan.action, plan.reason) == (ACTION_SKIP, "unchanged")


def test_touched_pdf_with_same_bytes_is_skipped():
    entry = _entry()
    touched = PdfStat(path=PDF.path, size=100, mtime_ns=99)
    assert _plan(entry, _pdf_row(entry), pdf=touched).action == ACTION_SKIP


def test_changed_pdf_is_reindexed():
    entry = _entry()
    bigger = PdfStat(path=PDF.path, size=250, mtime_ns=99)
    plan = _plan(entry, _pdf_row(entry), pdf=bigger)
    assert (plan.action, plan.reason) == (ACTION_PDF, "PDF changed")
    same_size = PdfStat(path=PDF.path, size=100, mtime_ns=99)
    plan = _plan(entry, _pdf_row(entry), pdf=same_size, hasher=lambda p: "bbb")
    assert plan.action == ACTION_PDF


def test_stub_is_upgraded_when_a_pdf_arrives():
    entry = _entry()
    plan = _plan(entry, _stub_row(entry), pdf=PDF)
    assert (plan.action, plan.reason) == (ACTION_PDF, "PDF added")


def test_settings_change_and_force_reindex():
    entry = _entry()
    assert _plan(entry, _pdf_row(entry), pdf=PDF, params="light1/c1/1000/100").reason == (
        "settings changed"
    )
    assert _plan(entry, _pdf_row(entry), pdf=PDF, force=True).action == ACTION_PDF
    assert _plan(entry, _stub_row(entry), force=True).action == ACTION_STUB


def test_scan_waits_for_ocr_then_is_picked_up():
    entry = _entry()
    waiting = _stub_row(
        entry, pdf_size=100, pdf_mtime_ns=5, pdf_sha256="aaa", ocr_pending=True
    )
    assert _plan(entry, waiting, pdf=PDF, ocr_available=False).action == ACTION_SKIP
    plan = _plan(entry, waiting, pdf=PDF, ocr_available=True)
    assert (plan.action, plan.reason) == (ACTION_PDF, "OCR now available")


def test_textless_pdf_after_ocr_is_not_retried_every_run():
    entry = _entry()
    done = _stub_row(entry, pdf_size=100, pdf_mtime_ns=5, pdf_sha256="aaa")
    assert _plan(entry, done, pdf=PDF).action == ACTION_SKIP


def test_failed_rows_wait_for_a_new_pdf_or_retry_flag():
    entry = _entry(abstract="")
    failed = _row(
        entry,
        status=STATUS_FAILED,
        pdf_size=100,
        pdf_mtime_ns=5,
        pdf_sha256="aaa",
        error="ocrmypdf timed out after 600s",
    )
    plan = _plan(entry, failed, pdf=PDF)
    assert plan.action == ACTION_SKIP and "timed out" in plan.reason
    assert _plan(entry, failed, pdf=PDF, retry_failed=True).reason == "retry"
    replaced = PdfStat(path=PDF.path, size=7, mtime_ns=6)
    assert _plan(entry, failed, pdf=replaced).action == ACTION_PDF


def test_pdf_removed_falls_back_to_abstract_or_removal():
    entry = _entry()
    assert _plan(entry, _pdf_row(entry)).action == ACTION_STUB
    bare = _entry(abstract="")
    plan = _plan(bare, _pdf_row(bare))
    assert plan.action == ACTION_REMOVE


def test_stub_follows_the_abstract():
    entry = _entry(abstract="A new abstract.")
    plan = _plan(entry, _stub_row(entry))
    assert (plan.action, plan.reason) == (ACTION_STUB, "abstract changed")
    gone = _entry(abstract="")
    assert _plan(gone, _stub_row(gone)).action == ACTION_REMOVE
    assert _plan(_entry(), _stub_row(_entry())).action == ACTION_SKIP
    assert _plan(_entry(), _stub_row(_entry()), abstracts=False).action == ACTION_REMOVE


def test_metadata_only_change_refreshes_the_row():
    old = _entry()
    row = _pdf_row(old)
    retitled = _entry(title="Deep-sea governance, revised")
    plan = _plan(retitled, row, pdf=PDF)
    assert (plan.action, plan.reason) == (ACTION_META, "metadata changed")
    moved = _entry()
    moved.dirs.append(f"law/{NAME}")
    assert _plan(moved, row, pdf=PDF).action == ACTION_META


# ---- pick_pdf ----------------------------------------------------------------


def test_pick_pdf_prefers_newest_then_largest(tmp_path):
    old = tmp_path / "old.pdf"
    new = tmp_path / "new.pdf"
    old.write_bytes(b"x" * 500)
    new.write_bytes(b"x" * 10)
    os.utime(old, ns=(1_000, 1_000))
    os.utime(new, ns=(2_000, 2_000))
    entry = _entry(pdfs=[old, new, tmp_path / "missing.pdf"])
    assert pick_pdf(entry).path == new
    os.utime(new, ns=(1_000, 1_000))
    assert pick_pdf(entry).path == old
    assert pick_pdf(_entry()) is None


# ---- Ledger ------------------------------------------------------------------


def test_ledger_latest_line_wins_and_survives_reload(tmp_path):
    path = tmp_path / "rag" / "ingest.jsonl"
    ledger = Ledger(path)
    assert ledger.rows() == [] and ledger.get("A") is None
    ledger.write(LedgerRow(key="A", status=STATUS_STUB, title="first"))
    ledger.write(LedgerRow(key="A", status=STATUS_OK, title="second", chunks=4))
    ledger.write(LedgerRow(key="B", authors=["Chen"], year=2019))
    again = Ledger(path)
    assert again.keys() == {"A", "B"}
    assert again.get("A").title == "second" and again.get("A").chunks == 4
    assert again.get("A").ts > 0
    assert again.get("B").authors == ["Chen"]


def test_ledger_remove_is_a_tombstone(tmp_path):
    path = tmp_path / "ingest.jsonl"
    ledger = Ledger(path)
    ledger.write(LedgerRow(key="A"))
    ledger.remove("A")
    ledger.remove("never-there")
    assert ledger.get("A") is None and Ledger(path).keys() == set()
    assert len(path.read_text().splitlines()) == 2
    ledger.write(LedgerRow(key="A", title="back"))
    assert Ledger(path).get("A").title == "back"


def test_ledger_tolerates_corrupt_and_unknown_lines(tmp_path):
    path = tmp_path / "ingest.jsonl"
    path.write_text(
        '{"key": "A", "title": "ok", "future_field": 1}\nnot json\n[1]\n{"title": "no key"}\n'
    )
    ledger = Ledger(path)
    assert ledger.keys() == {"A"} and ledger.get("A").title == "ok"


@pytest.mark.parametrize("text", ["", "abc"])
def test_text_sha_is_stable(text):
    assert text_sha(text) == text_sha(text) and len(text_sha(text)) == 64
