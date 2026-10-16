"""Workbench repair/mirror job cores (``repair_mirror_jobs``)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from paperful.config import Config
from paperful.scope import ItemScope
from paperful.sync import SyncStats
from paperful.ui import commands
from paperful.ui import repair_mirror_jobs as rmj
from tests.conftest import make_item


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    c.state_dir.mkdir(parents=True)
    c.out_dir.mkdir(parents=True)
    return c


class _WriteBackend:
    library_type = "user"

    def __init__(self):
        self.merged = 0

    def supports_write(self) -> bool:
        return True

    def children(self, key):
        return []

    def flush_writes(self) -> None:
        return None


def _cmd_record(cmd_id: str, verb: str = "repair_lint") -> dict:
    return {
        "id": cmd_id,
        "verb": verb,
        "status": "running",
        "review_token": "",
        "error": "",
        "report_path": "",
        "created": time.time(),
    }


@pytest.fixture
def scoped_backend(monkeypatch):
    title = "The BBNJ agreement and marine biodiversity beyond national jurisdiction"
    items = [
        make_item(key="KEEP", doi="10.1000/bbnj.1", title=title, collection_paths=["BBNJ"]),
        make_item(
            key="DROP",
            title=title,
            doi="10.1000/bbnj.1",
            collection_paths=["BBNJ"],
            date_added="2024-01-01T00:00:00Z",
        ),
    ]
    backend = _WriteBackend()

    def load_scope(backend_arg, *, collections, library=False, **kwargs):
        assert backend_arg is backend
        return ItemScope(items=items, label="BBNJ", keys=["C1"])

    monkeypatch.setattr("paperful.scope.load_scope", load_scope)
    monkeypatch.setattr("paperful.catalogue.open_library", lambda _cfg: backend)
    return backend, items


def test_gui_scope_error_on_empty_collection(cfg):
    with pytest.raises(rmj.GuiScopeError, match="collection"):
        rmj._require_collection("")


def test_repair_preview_lint_sets_review_token(cfg, scoped_backend, monkeypatch):
    from paperful.lint import Finding

    monkeypatch.setattr(
        "paperful.lint.lint_items",
        lambda *a, **k: [Finding("KEEP", "missing_doi", "T", "no DOI")],
    )
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    cmd_id = "lint-preview"
    commands.write_command(cfg, _cmd_record(cmd_id))
    rmj.run_repair_preview(cfg, cmd_id, verb="lint", collection="BBNJ")
    rec = commands.read_command(cfg, cmd_id)
    assert rec["review_token"]
    assert rec.get("read_only") is True
    assert rec["summary"]["findings"] == 1
    assert Path(rec["report_path"]).is_file()


def test_repair_preview_dedupe_writes_pack(cfg, scoped_backend):
    cmd_id = "dedupe-preview"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="repair_dedupe"))
    rmj.run_repair_preview(cfg, cmd_id, verb="dedupe", collection="BBNJ")
    rec = commands.read_command(cfg, cmd_id)
    assert rec["review_token"]
    report = Path(rec["report_path"])
    assert report.is_file()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema"] == "paperful.dedupe_pack.v1"
    assert rec["summary"]["groups"] >= 1


def test_repair_apply_refuses_read_only_lint(cfg, scoped_backend, monkeypatch):
    from paperful.lint import Finding

    monkeypatch.setattr("paperful.lint.lint_items", lambda *a, **k: [])
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    cmd_id = "lint-ro"
    commands.write_command(cfg, _cmd_record(cmd_id))
    rmj.run_repair_preview(cfg, cmd_id, verb="lint", collection="BBNJ")
    rec = commands.read_command(cfg, cmd_id)
    ok, msg, summary = rmj.run_repair_apply(cfg, token=rec["review_token"])
    assert not ok
    assert "read-only" in msg.lower()
    assert summary == {}


def test_repair_apply_dedupe_consumes_token(cfg, scoped_backend, monkeypatch):
    merged_calls: list[bool] = []

    def fake_merge(backend, groups, **kwargs):
        merged_calls.append(True)
        return 1, []

    monkeypatch.setattr("paperful.dedupe.apply_merge", fake_merge)
    cmd_id = "dedupe-apply"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="repair_dedupe"))
    rmj.run_repair_preview(cfg, cmd_id, verb="dedupe", collection="BBNJ")
    rec = commands.read_command(cfg, cmd_id)
    token = rec["review_token"]
    ok, msg, summary = rmj.run_repair_apply(cfg, token=token)
    assert ok, msg
    assert merged_calls
    assert summary.get("merged") == 1
    ok2, msg2, _ = rmj.run_repair_apply(cfg, token=token)
    assert not ok2


def test_mirror_preview_sync_writes_preview(cfg, monkeypatch, tmp_path):
    stats = SyncStats(written=2, gone=1, pdf_exports=3)

    def fake_sync(cfg, backend, *, dry_run, pdfs, accept_gone):
        assert dry_run is True
        return stats

    monkeypatch.setattr("paperful.sync.run_sync", fake_sync)
    monkeypatch.setattr("paperful.catalogue.open_library", lambda _c: _WriteBackend())
    cmd_id = "mirror-sync"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="mirror_sync"))
    rmj.run_mirror_preview(cfg, cmd_id, verb="sync", collection="")
    rec = commands.read_command(cfg, cmd_id)
    assert rec["review_token"]
    assert rec["summary"]["written"] == 2
    preview = json.loads(Path(rec["report_path"]).read_text(encoding="utf-8"))
    assert preview["verb"] == "sync"
    assert preview["stats"]["pdf_exports"] == 3


def test_mirror_apply_sync_after_preview(cfg, monkeypatch):
    seen: list[bool] = []

    def fake_sync(cfg, backend, *, dry_run, pdfs, accept_gone):
        seen.append(dry_run)
        return SyncStats(written=5, gone=0, pdf_exports=1)

    monkeypatch.setattr("paperful.sync.run_sync", fake_sync)
    monkeypatch.setattr("paperful.catalogue.open_library", lambda _c: _WriteBackend())
    cmd_id = "mirror-apply-sync"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="mirror_sync"))
    rmj.run_mirror_preview(cfg, cmd_id, verb="sync", collection="")
    rec = commands.read_command(cfg, cmd_id)
    ok, msg, summary = rmj.run_mirror_apply(
        cfg, token=rec["review_token"], collection=""
    )
    assert ok, msg
    assert summary["written"] == 5
    assert seen == [True, False]


def test_mirror_preview_cache_clean(cfg, monkeypatch):
    report_data = {"removable": 2, "kept": 10, "paths": ["/tmp/a.pdf"]}

    monkeypatch.setattr("paperful.sync.clean_pdf_cache", lambda c, apply: report_data)
    cmd_id = "cache-clean"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="mirror_cache"))
    rmj.run_mirror_preview(cfg, cmd_id, verb="cache clean", collection="")
    rec = commands.read_command(cfg, cmd_id)
    assert rec["summary"]["removable"] == 2


def test_repair_preview_hook_short_circuit(cfg):
    calls: list[str] = []

    def hook(cfg, cmd_id, **kw):
        calls.append(kw.get("verb", ""))
        commands.write_command(
            cfg,
            {**_cmd_record(cmd_id), "status": "done", "summary": {"ok": True}},
        )

    rmj.repair_preview_core_fn = hook
    try:
        rmj.run_repair_preview(cfg, "x", verb="lint", collection="BBNJ")
        assert calls == ["lint"]
    finally:
        rmj.repair_preview_core_fn = None


def test_repair_preview_fix_metadata_and_apply(cfg, scoped_backend, monkeypatch):
    from paperful.metadata import Patch

    patch = Patch(
        itemKey="KEEP",
        title="T",
        before={},
        after={"DOI": "10.1000/bbnj.1"},
        source="lint",
    )
    monkeypatch.setattr(
        "paperful.metadata.collect_patches",
        lambda *a, **k: [patch],
    )
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    monkeypatch.setattr(
        "paperful.metadata.apply_patches",
        lambda backend, patches: (1, []),
    )
    cmd_id = "fix-meta"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="repair_fix"))
    rmj.run_repair_preview(
        cfg, cmd_id, verb="fix-metadata", collection="BBNJ", overwrite=True
    )
    rec = commands.read_command(cfg, cmd_id)
    ok, msg, summary = rmj.run_repair_apply(cfg, token=rec["review_token"])
    assert ok, msg
    assert summary.get("applied") == 1


def test_repair_preview_ocr(cfg, scoped_backend, monkeypatch):
    from paperful.ocr import OcrBatch

    monkeypatch.setattr(
        "paperful.ocr.ocr_items",
        lambda *a, **k: OcrBatch(would=2, skipped=1, ignored=0, failed=0),
    )
    cmd_id = "ocr-prev"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="repair_ocr"))
    rmj.run_repair_preview(
        cfg,
        cmd_id,
        verb="ocr",
        collection="BBNJ",
        surgery={"attach": True, "force_retry": False},
    )
    rec = commands.read_command(cfg, cmd_id)
    assert rec["summary"]["would_ocr"] == 2
    assert rec["review_token"]


def test_repair_preview_attachments(cfg, scoped_backend, monkeypatch):
    from paperful.attachments import Scan

    monkeypatch.setattr(
        "paperful.attachments.plan_actions",
        lambda *a, **k: Scan(findings=[], actions=[], refusals=[]),
    )
    cmd_id = "att-prev"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="repair_attach"))
    rmj.run_repair_preview(cfg, cmd_id, verb="attachments", collection="BBNJ")
    rec = commands.read_command(cfg, cmd_id)
    assert "review_token" in rec
    assert rec["summary"]["findings"] == {}


def test_repair_apply_attachments_requires_surgery_flags(cfg, scoped_backend, monkeypatch):
    from paperful.attachments import Scan

    monkeypatch.setattr(
        "paperful.attachments.plan_actions",
        lambda *a, **k: Scan(findings=[], actions=[], refusals=[]),
    )
    cmd_id = "att-apply"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="repair_attach"))
    rmj.run_repair_preview(cfg, cmd_id, verb="attachments", collection="BBNJ")
    rec = commands.read_command(cfg, cmd_id)
    ok, msg, _ = rmj.run_repair_apply(cfg, token=rec["review_token"])
    assert not ok
    assert "surgery" in msg.lower()


def test_mirror_preview_snapshot(cfg, scoped_backend, monkeypatch):
    from paperful.snapshot import SnapshotStats

    monkeypatch.setattr(
        "paperful.snapshot.run_snapshot",
        lambda *a, **k: SnapshotStats(records=3, pdf_exports=1),
    )
    cmd_id = "snap-prev"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="mirror_snapshot"))
    rmj.run_mirror_preview(cfg, cmd_id, verb="snapshot", collection="BBNJ")
    rec = commands.read_command(cfg, cmd_id)
    assert rec["summary"]["records"] == 3


def test_mirror_apply_cache_clean(cfg, monkeypatch):
    preview_report = {"removable": 1, "kept": 0, "paths": ["/x.pdf"]}

    def fake_clean(cfg, apply):
        assert apply is False
        return preview_report

    monkeypatch.setattr("paperful.sync.clean_pdf_cache", fake_clean)
    cmd_id = "cache-prev"
    commands.write_command(cfg, _cmd_record(cmd_id, verb="mirror_cache"))
    rmj.run_mirror_preview(cfg, cmd_id, verb="cache clean", collection="")
    rec = commands.read_command(cfg, cmd_id)

    monkeypatch.setattr(
        "paperful.sync.clean_pdf_cache",
        lambda c, apply: {"removed": 1, "removable": 1, "kept": 0},
    )
    ok, msg, summary = rmj.run_mirror_apply(
        cfg, token=rec["review_token"], collection=""
    )
    assert ok, msg
    assert summary.get("removed") == 1


def test_jobs_repair_preview_uses_mirror_module(cfg, scoped_backend, monkeypatch):
    """jobs.repair_preview delegates to repair_mirror_jobs (not legacy repair_jobs)."""
    from paperful.lint import Finding
    from paperful.ui import jobs

    monkeypatch.setattr(
        "paperful.lint.lint_items",
        lambda *a, **k: [Finding("KEEP", "x", "T", "d")],
    )
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    cmd_id = commands.enqueue(
        cfg,
        "repair_lint",
        lambda cid: jobs.repair_preview(cfg, cid, verb="lint", collection="BBNJ"),
    )
    deadline = time.time() + 3
    rec: dict = {}
    while time.time() < deadline:
        rec = commands.read_command(cfg, cmd_id) or {}
        if rec.get("review_token"):
            break
        time.sleep(0.02)
    assert rec.get("review_token")
    assert rec.get("read_only") is True
