"""PDF drop-folder watch and ingest."""

from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from paperful.handoff import HINT_OPENABLE, MissingPdf, parse_handoff
from paperful.inbox import (
    SeenLedger,
    build_doi_index,
    ensure_inbox_dirs,
    list_candidate_pdfs,
    match_pdf,
    move_unmatched,
    process_candidates,
    wait_stable,
)
from paperful.store import Manifest, STATUS_ATTACHED
from tests.conftest import make_item


def test_parse_handoff_accepts_watch():
    assert parse_handoff("watch") == "watch"
    assert parse_handoff("WATCH") == "watch"


def test_ensure_inbox_dirs(cfg, tmp_path: Path):
    cfg.inbox_dir = str(tmp_path / "drop")
    root = ensure_inbox_dirs(cfg)
    assert root.is_dir()
    assert (root / "unmatched").is_dir()


def test_ensure_inbox_dirs_requires_config(cfg):
    cfg.inbox_dir = ""
    with pytest.raises(ValueError, match="inbox"):
        ensure_inbox_dirs(cfg)


def test_wait_stable_immediate_when_settle_zero(tmp_path: Path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    assert wait_stable(pdf, 0.0) is True


def test_build_doi_index_skips_ambiguous_and_has_pdf():
    items = [
        make_item(key="A", doi="10.1000/x", has_pdf=False),
        make_item(key="B", doi="10.1000/x", has_pdf=False),
        make_item(key="C", doi="10.1000/y", has_pdf=True),
        make_item(key="D", doi="10.1000/z", has_pdf=False),
    ]
    index = build_doi_index(items)
    assert "10.1000/x" not in index
    assert "10.1000/y" not in index
    assert index["10.1000/z"].key == "D"


def test_match_pdf_doi_then_fifo(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    item = make_item(key="DOI1", doi="10.1000/match", has_pdf=False)
    fifo_item = make_item(key="FIFO1", doi="10.1000/fifo", has_pdf=False)
    index = {"10.1000/match": item}
    queue = deque(
        [
            MissingPdf(
                key="FIFO1",
                title="t",
                doi="10.1000/fifo",
                url="https://x/a.pdf",
                hint=HINT_OPENABLE,
                attempts=[],
            )
        ]
    )
    by_key = {"FIFO1": fifo_item}

    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: "10.1000/match")
    hit = match_pdf(pdf, doi_index=index, fifo_queue=queue, items_by_key=by_key)
    assert hit.item is item and hit.how == "doi"
    assert len(queue) == 1

    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: None)
    hit = match_pdf(pdf, doi_index={}, fifo_queue=queue, items_by_key=by_key)
    assert hit.item is fifo_item and hit.how == "fifo"
    assert len(queue) == 0


def test_list_candidate_skips_partial_names(tmp_path: Path):
    good = tmp_path / "ok.pdf"
    good.write_bytes(b"%PDF")
    (tmp_path / "bad.pdf.crdownload").write_bytes(b"x")
    (tmp_path / "unmatched").mkdir()
    (tmp_path / "unmatched" / "other.pdf").write_bytes(b"%PDF")
    assert list_candidate_pdfs(tmp_path) == [good]


def test_move_unmatched(tmp_path: Path):
    root = tmp_path / "inbox"
    root.mkdir()
    pdf = root / "orphan.pdf"
    pdf.write_bytes(b"%PDF")
    dest = move_unmatched(root, pdf)
    assert dest.parent.name == "unmatched"
    assert dest.is_file()
    assert not pdf.exists()


def test_seen_ledger_skips_repeat(cfg, tmp_path: Path, monkeypatch):
    root = tmp_path / "inbox"
    cfg.inbox_dir = str(root)
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir.mkdir()
    cfg.min_pdf_bytes = 1000
    ensure_inbox_dirs(cfg)
    pdf = root / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"x" * 2000)
    item = make_item(key="K1", doi="10.1000/a", has_pdf=False)

    class Backend:
        def supports_write(self):
            return True

        def attach(self, key, path, title=None, note=None):
            class R:
                ok = True
                reason = "ok"

            return R()

    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: "10.1000/a")
    stats = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [item],
        once=True,
        settle_seconds=0.0,
        on_status=lambda _m: None,
    )
    assert stats.attached == 1
    assert not pdf.exists()

    # Drop a new file with same bytes fingerprint after recreate — ledger should skip
    # once path exists again with identical content fingerprint from prior ingest.
    # Re-create under a new name so path differs; ledger keys on full fingerprint.
    pdf2 = root / "b.pdf"
    pdf2.write_bytes(b"%PDF-1.4 " + b"x" * 2000)
    item2 = make_item(key="K2", doi="10.1000/b", has_pdf=False)
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: "10.1000/b")
    stats2 = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [item2],
        once=True,
        settle_seconds=0.0,
    )
    assert stats2.attached == 1

    # Same file path+content fingerprint already recorded → skipped
    pdf3 = root / "b.pdf"
    pdf3.write_bytes(b"%PDF-1.4 " + b"x" * 2000)
    # Force same fingerprint as pdf2 by using SeenLedger directly
    ledger = SeenLedger(cfg.inbox_seen_path)
    from paperful.inbox import _fingerprint

    assert ledger.has(_fingerprint(pdf3))
    stats3 = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [make_item(key="K3", doi="10.1000/c", has_pdf=False)],
        once=True,
        settle_seconds=0.0,
    )
    assert stats3.skipped >= 1
    assert stats3.attached == 0


def test_process_unmatched_moves_file(cfg, tmp_path: Path, monkeypatch):
    root = tmp_path / "inbox"
    cfg.inbox_dir = str(root)
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir.mkdir()
    cfg.min_pdf_bytes = 100
    ensure_inbox_dirs(cfg)
    pdf = root / "nope.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"y" * 200)
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: "10.1000/missing")

    class Backend:
        def supports_write(self):
            return True

        def attach(self, *a, **k):
            raise AssertionError("should not attach")

    stats = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [make_item(key="Z", doi="10.1000/other", has_pdf=False)],
        once=True,
        settle_seconds=0.0,
    )
    assert stats.unmatched == 1
    assert (root / "unmatched" / "nope.pdf").is_file()


def test_process_attach_by_doi(cfg, tmp_path: Path, monkeypatch):
    root = tmp_path / "inbox"
    cfg.inbox_dir = str(root)
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir.mkdir()
    cfg.min_pdf_bytes = 1000
    ensure_inbox_dirs(cfg)
    pdf = root / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"z" * 2000)
    item = make_item(key="ATT1", doi="10.1000/ok", has_pdf=False, collection_paths=["Col"])
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: "10.1000/ok")
    attached: list[str] = []

    class Backend:
        def supports_write(self):
            return True

        def attach(self, key, path, title=None, note=None):
            attached.append(key)

            class R:
                ok = True
                reason = "ok"

            return R()

    manifest = Manifest(cfg.manifest_path)
    stats = process_candidates(
        cfg,
        Backend(),
        manifest,
        [item],
        once=True,
        settle_seconds=0.0,
    )
    assert stats.attached == 1
    assert attached == ["ATT1"]
    assert manifest.records["ATT1"].status == STATUS_ATTACHED
    assert manifest.records["ATT1"].source == "inbox"
    assert not pdf.exists()


def test_process_fifo_when_no_doi(cfg, tmp_path: Path, monkeypatch):
    root = tmp_path / "inbox"
    cfg.inbox_dir = str(root)
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir.mkdir()
    cfg.min_pdf_bytes = 1000
    ensure_inbox_dirs(cfg)
    pdf = root / "hand.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"f" * 2000)
    item = make_item(key="FIFO2", doi="10.1000/fifo2", has_pdf=False, collection_paths=["Col"])
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: None)
    attached: list[str] = []

    class Backend:
        def supports_write(self):
            return True

        def attach(self, key, path, title=None, note=None):
            attached.append(key)

            class R:
                ok = True
                reason = "ok"

            return R()

    from paperful.inbox import fifo_from_missing

    queue = fifo_from_missing(
        [
            MissingPdf(
                key="FIFO2",
                title="t",
                doi="10.1000/fifo2",
                url="https://x/a.pdf",
                hint=HINT_OPENABLE,
                attempts=[],
            )
        ]
    )
    stats = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [item],
        fifo_queue=queue,
        once=True,
        settle_seconds=0.0,
    )
    assert stats.attached == 1 and attached == ["FIFO2"]


def test_idle_stops_watch_loop(cfg, tmp_path: Path):
    root = tmp_path / "inbox"
    cfg.inbox_dir = str(root)
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir.mkdir()
    ensure_inbox_dirs(cfg)
    sleeps: list[float] = []

    class Backend:
        def supports_write(self):
            return True

        def attach(self, *a, **k):
            raise AssertionError("no files")

    import time as _time

    stats = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [make_item(key="I", doi="10.1000/i", has_pdf=False)],
        once=False,
        idle_seconds=0.05,
        poll_seconds=0.02,
        settle_seconds=0.0,
        sleep_fn=_time.sleep,
    )
    assert stats.quit_reason == "idle"
    assert stats.attached == 0


def test_title_fingerprint_attach(cfg, tmp_path: Path, monkeypatch):
    root = tmp_path / "inbox"
    cfg.inbox_dir = str(root)
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir.mkdir()
    cfg.min_pdf_bytes = 1000
    cfg.inbox_match = "doi+title"
    ensure_inbox_dirs(cfg)
    pdf = root / "Marine governance thresholds 2021.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"z" * 2000)
    item = make_item(
        key="T1",
        doi=None,
        title="Marine governance thresholds",
        year=2021,
        has_pdf=False,
        collection_paths=["Col"],
    )
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: None)
    monkeypatch.setattr(
        "paperful.inbox_match.text_from_pdf",
        lambda *_a, **_k: "Marine governance thresholds\n2021 ocean policy",
    )
    monkeypatch.setattr("paperful.pdfid._pypdf_title", lambda _p: "")
    attached: list[str] = []

    class Backend:
        def supports_write(self):
            return True

        def attach(self, key, path, title=None, note=None):
            attached.append(key)

            class R:
                ok = True
                reason = "ok"

            return R()

    stats = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [item],
        once=True,
        settle_seconds=0.0,
    )
    assert stats.attached == 1
    assert attached == ["T1"]
    assert stats.events[0].how == "title_fingerprint"


def test_hold_before_unmatched(cfg, tmp_path: Path, monkeypatch):
    root = tmp_path / "inbox"
    cfg.inbox_dir = str(root)
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir.mkdir()
    cfg.min_pdf_bytes = 100
    cfg.inbox_quarantine_after_s = 60.0
    ensure_inbox_dirs(cfg)
    pdf = root / "later.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"y" * 200)
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: None)

    class Backend:
        def supports_write(self):
            return True

        def attach(self, *a, **k):
            raise AssertionError("should not attach")

    stats = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [make_item(key="Z", doi="10.1000/other", has_pdf=False)],
        once=True,
        settle_seconds=0.0,
    )
    assert stats.held == 1
    assert pdf.is_file()
    assert not (root / "unmatched" / "later.pdf").exists()


def test_gated_proposal_apply_reject(cfg, tmp_path: Path, monkeypatch):
    from paperful.inbox import apply_proposal, reject_proposal
    from paperful.inbox_match import list_proposals
    from paperful.resolve import WorkMeta

    root = tmp_path / "inbox"
    cfg.inbox_dir = str(root)
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir.mkdir()
    cfg.min_pdf_bytes = 1000
    cfg.inbox_create = "create_gated"
    ensure_inbox_dirs(cfg)
    pdf = root / "drop.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"z" * 2000)
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: "10.1000/new")

    class Backend:
        def supports_write(self):
            return True

        def attach(self, *a, **k):
            class R:
                ok = True
                reason = "ok"

            return R()

        def ensure_collection_path(self, path):
            return "CK"

        def create_parent(self, payload):
            return "NEWP"

        def items_in_scope(self, keys):
            return []

    stats = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [],
        once=True,
        settle_seconds=0.0,
        collection="BBNJ",
    )
    assert stats.created_gated == 1
    rows = list_proposals(cfg)
    assert len(rows) == 1
    pid = rows[0]["id"]
    reject_proposal(cfg, pid)
    assert list_proposals(cfg) == []
    # restore pending for apply
    rows[0]["status"] = "pending"
    from paperful.inbox_match import save_proposal

    save_proposal({**rows[0], "_path": rows[0]["_path"]})
    monkeypatch.setattr(
        "paperful.inbox._default_resolve",
        lambda _cfg: lambda doi: WorkMeta(
            doi=doi,
            title="A sufficiently long new work title",
            year=2022,
            source="crossref",
            work_type="journal-article",
        ),
    )
    # PDF was moved to review/
    review = list((root / "review").glob("*.pdf"))
    assert review
    data = apply_proposal(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        pid,
    )
    assert data["status"] == "applied"
    assert data["item_key"] == "NEWP"


def test_create_auto_unique_doi(cfg, tmp_path: Path, monkeypatch):
    from paperful.resolve import WorkMeta

    root = tmp_path / "inbox"
    cfg.inbox_dir = str(root)
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir.mkdir()
    cfg.min_pdf_bytes = 1000
    cfg.inbox_create = "create_auto"
    ensure_inbox_dirs(cfg)
    pdf = root / "auto.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"z" * 2000)
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: "10.1000/auto")
    created: list[str] = []
    attached: list[str] = []
    tags: list[str] = []

    class Backend:
        def supports_write(self):
            return True

        def items_in_scope(self, keys):
            return []

        def ensure_collection_path(self, path):
            return "CK"

        def create_parent(self, payload):
            created.append(payload["DOI"])
            tags.extend(t["tag"] for t in payload.get("tags") or [])
            return "AUTO1"

        def attach(self, key, path, title=None, note=None):
            attached.append(key)

            class R:
                ok = True
                reason = "ok"

            return R()

    work = WorkMeta(
        doi="10.1000/auto",
        title="A sufficiently long auto created title",
        year=2021,
        source="crossref",
        work_type="journal-article",
    )
    stats = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [],
        once=True,
        settle_seconds=0.0,
        collection="BBNJ",
        resolve_work=lambda doi: work,
        extra_tags=["bbnj"],
    )
    assert stats.created_auto == 1
    assert created == ["10.1000/auto"]
    assert attached == ["AUTO1"]
    assert "inbox-created" in tags
    assert "inbox:inbox" in tags
    assert "bbnj" in tags


def test_create_auto_title_only_fail_closed(cfg, tmp_path: Path, monkeypatch):
    root = tmp_path / "inbox"
    cfg.inbox_dir = str(root)
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir.mkdir()
    cfg.min_pdf_bytes = 100
    cfg.inbox_create = "create_auto"
    ensure_inbox_dirs(cfg)
    pdf = root / "nodoi.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"y" * 200)
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: None)

    class Backend:
        def supports_write(self):
            return True

        def create_parent(self, payload):
            raise AssertionError("no create")

        def attach(self, *a, **k):
            raise AssertionError("no attach")

    stats = process_candidates(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        [],
        once=True,
        settle_seconds=0.0,
        collection="BBNJ",
    )
    assert stats.unmatched == 1
    assert (root / "unmatched" / "nodoi.pdf").is_file()


def test_llm_when_thin_logs_without_auto_attach(cfg, tmp_path: Path, monkeypatch):
    from paperful.inbox_match import match_ladder
    from tests.test_llm_verbs import StubLLM

    cfg.llm_enabled = True
    cfg.inbox_match = "full"
    cfg.inbox_llm_match = "when_thin"
    cfg.inbox_llm_match_min_confidence = 0.5
    cfg.inbox_llm_auto_attach_min = 0.95
    item = make_item(key="L1", doi="10.1000/l", title="LLM candidate paper title", year=2020, has_pdf=False)
    stub = StubLLM(data={"match": True, "confidence": 0.6, "item_key": "L1", "reason": "maybe"})
    monkeypatch.setattr("paperful.llm.get_client", lambda _cfg: stub)
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda _p: None)
    monkeypatch.setattr(
        "paperful.inbox_match.text_from_pdf",
        lambda *_a, **_k: "LLM candidate paper title excerpt about oceans " * 4,
    )
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    from paperful.inbox import _llm_match

    hit = _llm_match(cfg, pdf, "LLM candidate paper title excerpt about oceans " * 4, [item])
    assert hit is not None
    assert hit.how == "llm"
    assert hit.confidence == 0.6
    assert hit.confidence < cfg.inbox_llm_auto_attach_min
