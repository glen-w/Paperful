"""Ingest from a mirror in tmp_path, with a fake embedder and a real index."""

from __future__ import annotations

from pathlib import Path

import pytest

import paperful.rag.ingest as ingest_mod
from paperful.ocr import OcrBatch, OcrRow
from paperful.rag.index import Index, index_dir, ledger_path
from paperful.rag.ingest import ingest_entries, select_entries
from paperful.rag.ledger import STATUS_FAILED, STATUS_OK, STATUS_STUB, Ledger
from tests.ragfakes import BODY, DIM, FakeEmbedder, TextFileParser
from tests.ragfakes import add_item as _add

pytest.importorskip("lancedb")


@pytest.fixture
def rag_cfg(cfg):
    cfg.rag_enabled = True
    cfg.out_dir.mkdir(parents=True)
    return cfg


@pytest.fixture
def tools():
    return {"embedder": FakeEmbedder(), "parser": TextFileParser()}


def _ingest(cfg, tools, **kw):
    kw.setdefault("ocr_available", lambda: False)
    return ingest_entries(cfg, select_entries(cfg), **tools, **kw)


def _statuses(batch):
    return {row.key: row.status for row in batch.rows}


# ---- first run ---------------------------------------------------------------


def test_ingest_indexes_pdfs_abstracts_and_skips_empty_items(rag_cfg, tools):
    _add(rag_cfg, "AAAA1111", pdf=BODY + "\f" + BODY)
    _add(rag_cfg, "BBBB2222", title="Whales", abstract="Whales eat krill.")
    _add(rag_cfg, "CCCC3333", title="Nothing here")
    batch = _ingest(rag_cfg, tools)
    assert _statuses(batch) == {
        "AAAA1111": "pdf",
        "BBBB2222": "abstract",
        "CCCC3333": "nothing",
    }
    ledger = Ledger(ledger_path(rag_cfg))
    pdf_row, stub_row = ledger.get("AAAA1111"), ledger.get("BBBB2222")
    assert pdf_row.status == STATUS_OK and pdf_row.source == "pdf" and pdf_row.chunks >= 1
    assert pdf_row.pdf == "ocean/Chen - 2019 - Krill in winter -- AAAA1111/paper.pdf"
    assert pdf_row.authors == ["Chen"] and pdf_row.year == 2019 and pdf_row.pdf_sha256
    assert stub_row.status == STATUS_STUB and stub_row.chunks == 1
    assert ledger.get("CCCC3333") is None
    index = Index.open(rag_cfg)
    assert index.count() == pdf_row.chunks + 1 and index.dim == DIM
    assert batch.summary()["chunks"] == index.count()
    # The paper title goes in front of what is embedded, not into the stored text.
    assert tools["embedder"].documents[0].startswith("Krill in winter\n\n")
    hits = index.search(tools["embedder"].embed_query("x"), "", k=10, hybrid=False)
    by_key = {h["item_key"]: h for h in hits}
    assert not by_key["AAAA1111"]["text"].startswith("Krill in winter\n\n")
    assert by_key["AAAA1111"]["page_start"] == 1
    assert by_key["BBBB2222"]["page_start"] is None
    assert by_key["BBBB2222"]["source"] == "abstract"


def test_second_run_does_no_work(rag_cfg, tools):
    _add(rag_cfg, "AAAA1111", pdf=BODY)
    _add(rag_cfg, "BBBB2222", abstract="Whales eat krill.")
    _ingest(rag_cfg, tools)
    embedded, parsed = len(tools["embedder"].documents), len(tools["parser"].parsed)
    batch = _ingest(rag_cfg, tools)
    assert set(_statuses(batch).values()) == {"unchanged"}
    assert len(tools["embedder"].documents) == embedded
    assert len(tools["parser"].parsed) == parsed


def test_dry_run_reports_the_plan_and_writes_nothing(rag_cfg, tools):
    _add(rag_cfg, "AAAA1111", pdf=BODY)
    _add(rag_cfg, "BBBB2222", abstract="Whales eat krill.")
    batch = _ingest(rag_cfg, tools, dry_run=True)
    assert batch.dry_run and _statuses(batch) == {"AAAA1111": "pdf", "BBBB2222": "abstract"}
    assert not rag_cfg.rag_dir.exists()
    assert tools["embedder"].documents == [] and tools["parser"].parsed == []


def test_abstracts_can_be_turned_off(rag_cfg, tools):
    rag_cfg.rag_abstracts = False
    _add(rag_cfg, "BBBB2222", abstract="Whales eat krill.")
    assert _statuses(_ingest(rag_cfg, tools)) == {"BBBB2222": "nothing"}


# ---- change tracking ---------------------------------------------------------


def test_stub_is_upgraded_when_the_pdf_arrives(rag_cfg, tools):
    folder = _add(rag_cfg, "AAAA1111", abstract="Short abstract about krill.")
    _ingest(rag_cfg, tools)
    (folder / "paper.pdf").write_text(BODY)
    batch = _ingest(rag_cfg, tools)
    assert batch.rows[0].status == "pdf" and batch.rows[0].reason == "PDF added"
    row = Ledger(ledger_path(rag_cfg)).get("AAAA1111")
    assert row.status == STATUS_OK and row.source == "pdf"
    hits = Index.open(rag_cfg).search([1.0] + [0.0] * (DIM - 1), "", k=10, hybrid=False)
    assert {h["source"] for h in hits} == {"pdf"}


def test_changed_pdf_replaces_its_passages(rag_cfg, tools):
    folder = _add(rag_cfg, "AAAA1111", pdf=BODY)
    _ingest(rag_cfg, tools)
    (folder / "paper.pdf").write_text("Seabed mining licences and royalties. " * 10)
    batch = _ingest(rag_cfg, tools)
    assert batch.rows[0].reason == "PDF changed"
    hits = Index.open(rag_cfg).search([1.0] + [0.0] * (DIM - 1), "", k=10, hybrid=False)
    assert hits and all("Seabed" in h["text"] for h in hits)


def test_metadata_change_refreshes_the_ledger_without_embedding(rag_cfg, tools):
    _add(rag_cfg, "AAAA1111", pdf=BODY)
    _ingest(rag_cfg, tools)
    embedded = len(tools["embedder"].documents)
    _add(rag_cfg, "AAAA1111", collection="law", pdf=None)
    batch = _ingest(rag_cfg, tools)
    assert _statuses(batch) == {"AAAA1111": "meta"}
    assert len(tools["embedder"].documents) == embedded
    assert len(Ledger(ledger_path(rag_cfg)).get("AAAA1111").dirs) == 2


def test_force_reindexes_everything(rag_cfg, tools):
    _add(rag_cfg, "AAAA1111", pdf=BODY)
    _ingest(rag_cfg, tools)
    count = Index.open(rag_cfg).count()
    batch = _ingest(rag_cfg, tools, force=True)
    assert batch.rows[0].status == "pdf" and Index.open(rag_cfg).count() == count
    # The text cache means a forced run does not parse again.
    assert tools["parser"].parsed == ["paper.pdf"]


def test_chunk_settings_change_reindexes(rag_cfg, tools):
    _add(rag_cfg, "AAAA1111", pdf=BODY * 4)
    _ingest(rag_cfg, tools)
    before = Index.open(rag_cfg).count()
    rag_cfg.rag_chunk_chars, rag_cfg.rag_chunk_overlap = 400, 50
    batch = _ingest(rag_cfg, tools)
    assert batch.rows[0].reason == "settings changed"
    assert Index.open(rag_cfg).count() > before


def test_prune_drops_items_that_left_the_mirror(rag_cfg, tools):
    import shutil

    folder = _add(rag_cfg, "AAAA1111", pdf=BODY)
    _add(rag_cfg, "BBBB2222", abstract="Whales eat krill.")
    _ingest(rag_cfg, tools)
    shutil.rmtree(folder)
    assert _statuses(_ingest(rag_cfg, tools)) == {"BBBB2222": "unchanged"}
    assert Ledger(ledger_path(rag_cfg)).get("AAAA1111") is not None
    batch = _ingest(rag_cfg, tools, prune=True)
    assert _statuses(batch)["AAAA1111"] == "removed"
    assert Ledger(ledger_path(rag_cfg)).keys() == {"BBBB2222"}
    assert Index.open(rag_cfg).count() == 1


def test_unreadable_pdf_is_recorded_and_not_retried(rag_cfg, tools):
    _add(rag_cfg, "AAAA1111", pdf="BROKEN")
    batch = _ingest(rag_cfg, tools)
    assert batch.rows[0].status == "failed" and "unreadable" in batch.rows[0].reason
    row = Ledger(ledger_path(rag_cfg)).get("AAAA1111")
    assert row.status == STATUS_FAILED and row.pdf_sha256 and row.error
    again = _ingest(rag_cfg, tools)
    assert again.rows[0].status == "unchanged" and "failed earlier" in again.rows[0].reason
    assert tools["parser"].parsed == ["paper.pdf"]
    retried = _ingest(rag_cfg, tools, retry_failed=True)
    assert retried.rows[0].status == "failed" and len(tools["parser"].parsed) == 2


def test_select_entries_filters_by_collection_key_year_and_type(rag_cfg):
    _add(rag_cfg, "AAAA1111", collection="ocean/BBNJ", abstract="a")
    _add(rag_cfg, "BBBB2222", collection="law", abstract="b")
    assert [e.key for e in select_entries(rag_cfg, collections=["ocean"])] == ["AAAA1111"]
    assert [e.key for e in select_entries(rag_cfg, item_keys=["BBBB2222"])] == ["BBBB2222"]
    assert select_entries(rag_cfg, year_from=2020) == []
    assert len(select_entries(rag_cfg, year_to=2019)) == 2
    assert select_entries(rag_cfg, item_types=frozenset({"book"})) == []
    assert len(select_entries(rag_cfg, item_types=frozenset({"journalArticle"}))) == 2


# ---- OCR ---------------------------------------------------------------------


def _fake_ocr(monkeypatch, *, succeed=True):
    """Stand-in for OCRmyPDF: rewrites each scan with a text layer."""
    calls = []

    def ocr_items(cfg, items, manifest, backend, *, apply, track=None, classify=None, **kw):
        calls.append({"keys": [i.key for i in items], "backend": backend, "apply": apply})
        batch = OcrBatch()
        for item in items:
            path = Path(item.pdf_path)
            why = classify(path)
            assert why in ("no text", "partial text")
            if succeed:
                path.write_text(BODY + "\f" + BODY)
                batch.rows.append(OcrRow(item.key, item.title, str(path), "ocr", why))
            else:
                batch.rows.append(
                    OcrRow(item.key, item.title, str(path), "failed", "ocrmypdf timed out")
                )
        return batch

    monkeypatch.setattr(ingest_mod, "ocr_items", ocr_items)
    return calls


def test_only_scans_are_sent_to_ocr(rag_cfg, tools, monkeypatch):
    _add(rag_cfg, "AAAA1111", pdf=BODY)  # born digital
    _add(rag_cfg, "BBBB2222", title="Old survey", pdf="\f\f")  # three blank pages
    _add(rag_cfg, "CCCC3333", title="Typed cover", pdf=BODY + "\f\f\f")  # 1 of 4 has text
    calls = _fake_ocr(monkeypatch)
    batch = _ingest(rag_cfg, tools, ocr_available=lambda: True)
    assert calls == [{"keys": ["BBBB2222", "CCCC3333"], "backend": None, "apply": True}]
    assert _statuses(batch) == {"AAAA1111": "pdf", "BBBB2222": "ocr", "CCCC3333": "ocr"}
    row = Ledger(ledger_path(rag_cfg)).get("BBBB2222")
    assert row.source == "ocr" and not row.ocr_pending and not row.error
    # The ledger describes the rewritten file, so the next run sees nothing to do.
    assert set(_statuses(_ingest(rag_cfg, tools, ocr_available=lambda: True)).values()) == {
        "unchanged"
    }
    assert len(calls) == 1


def test_scan_without_ocr_waits_and_is_picked_up_later(rag_cfg, tools, monkeypatch):
    _add(rag_cfg, "BBBB2222", title="Old survey", abstract="A survey.", pdf="\f\f")
    calls = _fake_ocr(monkeypatch)
    batch = _ingest(rag_cfg, tools)  # ocrmypdf not installed
    assert _statuses(batch) == {"BBBB2222": "abstract"} and calls == []
    row = Ledger(ledger_path(rag_cfg)).get("BBBB2222")
    assert row.status == STATUS_STUB and row.ocr_pending and row.pdf_sha256
    assert _statuses(_ingest(rag_cfg, tools)) == {"BBBB2222": "unchanged"}
    batch = _ingest(rag_cfg, tools, ocr_available=lambda: True)
    assert batch.rows[0].status == "ocr"
    assert Ledger(ledger_path(rag_cfg)).get("BBBB2222").ocr_pending is False


def test_scan_with_no_abstract_still_waits_for_ocr(rag_cfg, tools, monkeypatch):
    _add(rag_cfg, "BBBB2222", title="Old survey", pdf="\f\f")
    _fake_ocr(monkeypatch)
    assert _statuses(_ingest(rag_cfg, tools)) == {"BBBB2222": "failed"}
    row = Ledger(ledger_path(rag_cfg)).get("BBBB2222")
    assert row.ocr_pending and not row.error
    assert _ingest(rag_cfg, tools, ocr_available=lambda: True).rows[0].status == "ocr"


def test_ocr_can_be_turned_off_by_flag_or_config(rag_cfg, tools, monkeypatch):
    _add(rag_cfg, "BBBB2222", abstract="A survey.", pdf="\f\f")
    calls = _fake_ocr(monkeypatch)
    _ingest(rag_cfg, tools, ocr=False, ocr_available=lambda: True)
    rag_cfg.rag_ocr = "off"
    _ingest(rag_cfg, tools, force=True, ocr_available=lambda: True)
    assert calls == []


def test_partial_text_is_indexed_when_ocr_is_unavailable(rag_cfg, tools):
    _add(rag_cfg, "CCCC3333", pdf=BODY + "\f\f\f")
    batch = _ingest(rag_cfg, tools)
    assert batch.rows[0].status == "pdf"
    row = Ledger(ledger_path(rag_cfg)).get("CCCC3333")
    assert row.status == STATUS_OK and row.ocr_pending


def test_failed_ocr_is_parked_until_retry(rag_cfg, tools, monkeypatch):
    _add(rag_cfg, "BBBB2222", abstract="A survey.", pdf="\f\f")
    calls = _fake_ocr(monkeypatch, succeed=False)
    batch = _ingest(rag_cfg, tools, ocr_available=lambda: True)
    assert batch.rows[0].status == "abstract" and "timed out" in batch.rows[0].reason
    row = Ledger(ledger_path(rag_cfg)).get("BBBB2222")
    assert row.status == STATUS_STUB and "OCR failed" in row.error
    _ingest(rag_cfg, tools, ocr_available=lambda: True)
    assert len(calls) == 1
    _ingest(rag_cfg, tools, ocr_available=lambda: True, retry_failed=True)
    assert len(calls) == 2


# ---- isolation ---------------------------------------------------------------


def test_ingest_never_opens_the_reference_manager(rag_cfg, tools, monkeypatch):
    import paperful.zot as zot

    def boom(*args, **kwargs):
        raise AssertionError("rag ingest must not contact the reference manager")

    monkeypatch.setattr(zot.ZoteroLocal, "__init__", boom)
    monkeypatch.setattr("paperful.library.get_backend", boom)
    _add(rag_cfg, "AAAA1111", pdf=BODY)
    assert _ingest(rag_cfg, tools).rows[0].status == "pdf"


def test_embedding_failure_stops_the_run_and_keeps_what_was_done(rag_cfg, tools):
    from paperful.llm.embed import EmbedError

    _add(rag_cfg, "AAAA1111", pdf=BODY)
    _add(rag_cfg, "BBBB2222", title="Whales", pdf=BODY.replace("Krill", "Whales"))
    embedder = tools["embedder"]
    real = embedder.embed_documents

    def flaky(texts):
        if any("Whales" in t for t in texts):
            raise EmbedError("Ollama unreachable")
        return real(texts)

    embedder.embed_documents = flaky
    with pytest.raises(EmbedError):
        _ingest(rag_cfg, tools)
    assert Ledger(ledger_path(rag_cfg)).keys() == {"AAAA1111"}
    embedder.embed_documents = real
    assert _statuses(_ingest(rag_cfg, tools)) == {"AAAA1111": "unchanged", "BBBB2222": "pdf"}
    assert index_dir(rag_cfg).name == "ollama__nomic-embed-text"
