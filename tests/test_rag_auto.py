"""Auto-ingest selection, its hook in commands that land PDFs, and the doctor rows."""

from __future__ import annotations

import types

import pytest
from typer.testing import CliRunner

import paperful.rag.auto as auto_mod
from paperful import cli
from paperful.doctor import _rag_checks
from paperful.llm.validate import LlmConfigError
from paperful.ocr import OcrBatch, OcrRow
from paperful.rag.auto import affected_keys, auto_ingest
from paperful.rag.index import ledger_path
from paperful.rag.ledger import Ledger
from paperful.snapshot import run_snapshot
from paperful.store import (
    STATUS_ATTACHED,
    STATUS_NOT_FOUND,
    STATUS_OK,
    Manifest,
    Record,
)
from tests.conftest import make_item
from tests.ragfakes import BODY, FakeEmbedder, TextFileParser, add_item

runner = CliRunner()


@pytest.fixture
def rag_cfg(cfg):
    cfg.rag_enabled = True
    cfg.rag_auto_ingest = True
    cfg.out_dir.mkdir(parents=True)
    cfg.state_dir.mkdir(parents=True)
    return cfg


def _log(cfg, key, status=STATUS_OK, path="ocean/x.pdf") -> float:
    manifest = Manifest(cfg.manifest_path)
    manifest.write(Record(itemKey=key, status=status, path=path))
    return manifest.get(key).ts


# ---- affected_keys -----------------------------------------------------------


def test_affected_keys_takes_recent_pdf_landings_and_named_items(rag_cfg):
    old = _log(rag_cfg, "OLD00001")
    since = old + 0.001
    Manifest(rag_cfg.manifest_path)  # reload path is exercised below
    import time

    time.sleep(0.005)
    _log(rag_cfg, "NEW00001")
    _log(rag_cfg, "NEW00002", status=STATUS_ATTACHED)
    _log(rag_cfg, "MISS0001", status=STATUS_NOT_FOUND, path=None)
    assert affected_keys(rag_cfg, since) == {"NEW00001", "NEW00002"}
    assert affected_keys(rag_cfg, since, keys=["SNAP0001", ""]) == {
        "NEW00001",
        "NEW00002",
        "SNAP0001",
    }
    assert affected_keys(rag_cfg, since + 10_000) == set()
    assert affected_keys(rag_cfg, 0.0) >= {"OLD00001", "NEW00001"}


def test_auto_ingest_is_off_by_default(cfg, monkeypatch):
    def unreachable(*a, **k):
        raise AssertionError("auto-ingest must do nothing unless switched on")

    monkeypatch.setattr(auto_mod, "ingest_entries", unreachable)
    monkeypatch.setattr(auto_mod, "mirror_entries", unreachable)
    assert auto_ingest(cfg, since=0.0, keys=["AAAA1111"]) is None
    cfg.rag_enabled = True
    assert auto_ingest(cfg, since=0.0, keys=["AAAA1111"]) is None
    cfg.rag_enabled, cfg.rag_auto_ingest = False, True
    assert auto_ingest(cfg, since=0.0, keys=["AAAA1111"]) is None


def test_auto_ingest_does_nothing_when_nothing_landed(rag_cfg, monkeypatch):
    def unreachable(*a, **k):
        raise AssertionError("no affected items; the mirror must not be walked")

    monkeypatch.setattr(auto_mod, "mirror_entries", unreachable)
    assert auto_ingest(rag_cfg, since=0.0) is None


def test_auto_ingest_indexes_only_the_affected_items(rag_cfg):
    pytest.importorskip("lancedb")
    add_item(rag_cfg, "AAAA1111", pdf=BODY)
    add_item(rag_cfg, "BBBB2222", title="Whales", pdf=BODY.replace("Krill", "Whales"))
    batch = auto_ingest(
        rag_cfg,
        since=0.0,
        keys=["AAAA1111", "GONE0000"],
        embedder=FakeEmbedder(),
        parser=TextFileParser(),
        ocr_available=lambda: False,
    )
    assert [row.key for row in batch.rows] == ["AAAA1111"]
    assert Ledger(ledger_path(rag_cfg)).keys() == {"AAAA1111"}
    assert auto_ingest(rag_cfg, since=0.0, keys=["GONE0000"]) is None


# ---- hooks -------------------------------------------------------------------


def test_snapshot_reports_which_items_had_a_pdf_exported(cfg, monkeypatch):
    exported = {"KEY00002"}

    def snapshot_item(out_dir, item, backend, cols, summaries_dir, pdfs, *, dry_run):
        return 1, int(item.key in exported), 0, {"key": item.key}

    monkeypatch.setattr("paperful.snapshot.snapshot_item", snapshot_item)
    items = [make_item(key="KEY00001"), make_item(key="KEY00002")]
    stats = run_snapshot(cfg, object(), items, pdfs="all", dry_run=True, manifest=None)
    assert stats.pdf_keys == ["KEY00002"] and stats.pdf_exports == 1


def _ocr_cli(tmp_path, monkeypatch, *, apply: bool):
    config = tmp_path / "config.toml"
    config.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
    )
    items = [make_item(key="SCAN0001"), make_item(key="TEXT0001")]
    loaded = types.SimpleNamespace(items=items, label="library")
    monkeypatch.setenv("PAPERFUL_PACK", "off")
    monkeypatch.setattr(cli, "_connect", lambda cfg: object())
    monkeypatch.setattr(cli, "_load_scope", lambda backend, **scope: loaded)

    def ocr_items(
        cfg, items, manifest, backend, *, apply, attach=False, max_seconds=None, track=None
    ):
        batch = OcrBatch()
        status = "ocr" if apply else "would"
        batch.rows.append(OcrRow("SCAN0001", "Scan", "a.pdf", status, "no text"))
        batch.rows.append(OcrRow("TEXT0001", "Text", "b.pdf", "skip", "has text"))
        return batch

    monkeypatch.setattr("paperful.ocr.ocr_items", ocr_items)
    calls = []
    monkeypatch.setattr(
        cli, "_rag_auto", lambda cfg, since, keys=(): calls.append((since, list(keys)))
    )
    args = ["ocr", "--library", "--config", str(config)] + (["--apply"] if apply else [])
    res = runner.invoke(cli.app, args)
    assert res.exit_code == 0, res.stdout
    return calls


def test_ocr_apply_hands_rewritten_items_to_auto_ingest(tmp_path, monkeypatch):
    calls = _ocr_cli(tmp_path, monkeypatch, apply=True)
    assert len(calls) == 1 and calls[0][1] == ["SCAN0001"] and calls[0][0] > 0


def test_ocr_dry_run_does_not_trigger_auto_ingest(tmp_path, monkeypatch):
    assert _ocr_cli(tmp_path, monkeypatch, apply=False) == []


def test_every_command_that_lands_pdfs_calls_the_hook():
    """Guards the wiring: a new landing path should add its own call."""
    import inspect

    hooked = {
        "run": cli.run,
        "gaps": cli.gaps,
        "attach": cli.attach,
        "inbox watch": cli.inbox_watch,
        "inbox drain": cli.inbox_drain,
        "snapshot": cli.snapshot,
        "ocr": cli.ocr,
        "handoff walk": cli._run_session_handoff,
        "handoff inbox": cli._inbox_handoff_session,
        "snowball": cli._run_snowball,
    }
    for name, fn in hooked.items():
        assert "_rag_auto(" in inspect.getsource(fn), name


# ---- doctor ------------------------------------------------------------------


def test_doctor_rag_row_is_green_and_quiet_when_off(cfg):
    (check,) = _rag_checks(cfg)
    assert (check.name, check.status) == ("RAG index", "green")
    assert "disabled" in check.detail


def test_doctor_ambers_missing_lancedb(cfg, monkeypatch):
    import importlib.util

    cfg.rag_enabled = True
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name == "lancedb" else real(name, *a)
    )
    (check,) = _rag_checks(cfg)
    assert check.status == "amber" and "--extra rag" in check.detail


def test_doctor_ambers_missing_model_and_unbuilt_index(cfg, monkeypatch):
    pytest.importorskip("lancedb")
    cfg.rag_enabled = True

    def missing(cfg):
        raise LlmConfigError("Try: ollama pull nomic-embed-text")

    monkeypatch.setattr("paperful.llm.preflight.validate_embedder", missing)
    embeddings, index = _rag_checks(cfg)
    assert embeddings.status == "amber" and "ollama pull" in embeddings.detail
    assert index.status == "amber" and "paperful rag ingest" in index.detail


def test_doctor_greens_a_built_index(rag_cfg, monkeypatch):
    pytest.importorskip("lancedb")
    from paperful.rag.ingest import ingest_entries, select_entries

    add_item(rag_cfg, "AAAA1111", pdf=BODY)
    embedder = FakeEmbedder()
    ingest_entries(
        rag_cfg,
        select_entries(rag_cfg),
        embedder=embedder,
        parser=TextFileParser(),
        ocr_available=lambda: False,
    )
    monkeypatch.setattr("paperful.llm.preflight.validate_embedder", lambda cfg: embedder)
    embeddings, index = _rag_checks(rag_cfg)
    assert embeddings.status == "green" and "nomic-embed-text" in embeddings.detail
    assert index.status == "green" and index.detail.startswith("1 items, ")
