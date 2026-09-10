"""Run report / end-of-run summary."""

from __future__ import annotations

import io
import json

import httpx
from rich.console import Console

from paperful import pipeline as pl
from paperful.runreport import (
    build_report,
    classify_enrichment,
    error_type_for,
    print_run_summary,
    write_run_report,
)
from paperful.sources.base import Candidate, Outcome
from paperful.store import (
    STATUS_ATTACHED,
    STATUS_ERROR,
    STATUS_NOT_FOUND,
    STATUS_OK,
    Manifest,
)
from tests.conftest import PDF_BYTES, make_item, mock_client
from tests.test_pipeline import FakeAttacher, StubSource


def test_classify_enrichment():
    assert classify_enrichment(["verify:ok(0.95)"]) == ["doi_verified"]
    assert classify_enrichment(["crossref:matched(0.97)", "swap:10.1->10.2"]) == [
        "doi_crossref",
        "doi_swap",
    ]
    assert classify_enrichment(["pubmed:matched", "verify:suspect(0.4)"]) == [
        "doi_pubmed"
    ]


def test_error_type_for():
    assert error_type_for("ok") is None
    assert error_type_for("not_found") is None
    assert error_type_for("captcha") == "captcha"
    assert error_type_for("attach_failed", attach_code="quota") == "attach:quota"
    assert (
        error_type_for("error", "only transient failures")
        == "error:only_transient_failures"
    )


def test_pipeline_populates_run_stats(cfg, monkeypatch):
    def fake_prepare(client, item, **kwargs):
        item.doi = "10.9/found"
        item.doi_source = "crossref"
        item.doi_verified = "ok"
        return ["crossref:matched(0.97)"]

    src = StubSource("oa", {"A": Candidate(url="https://x.test/a.pdf", source="oa")})
    miss = StubSource("oa2", default=Outcome.NOT_FOUND)
    monkeypatch.setattr(pl, "REGISTRY", {"oa": src, "oa2": miss})
    monkeypatch.setattr(pl, "prepare_identifiers", fake_prepare)
    manifest = Manifest(cfg.manifest_path)
    pipe = pl.Pipeline(
        cfg, manifest, Console(file=io.StringIO()), sources=["oa", "oa2"]
    )
    pipe.client = mock_client(lambda r: httpx.Response(200, content=PDF_BYTES))
    pipe.ctx.client = pipe.client
    stats = pipe.run([make_item(key="A", doi=None), make_item(key="B", doi="10.0/b")])

    assert stats.ok == 1
    assert stats.not_found == 1
    assert stats.fields_corrected.get("doi_crossref") == 2  # both items enriched
    assert stats.sources_checked["oa"]["found"] == 1
    assert stats.sources_checked["oa2"]["not_found"] >= 1
    assert len(stats.items) == 2
    assert {i.status for i in stats.items} == {STATUS_OK, STATUS_NOT_FOUND}

    report = build_report(stats, cfg, command="run", scope="library")
    assert report["schema"] == "paperful.run_report.v1"
    assert report["summary"]["pdfs_downloaded"] == 1
    assert report["summary"]["fields_corrected"] >= 1
    assert "oa" in report["summary"]["sources_checked"]

    path = write_run_report(cfg, report)
    assert path is not None and path.exists()
    assert (cfg.state_dir / "last-run.json").exists()
    data = json.loads(path.read_text())
    assert data["summary"]["pdfs_downloaded"] == 1
    assert len(data["items"]) == 2


def test_attached_does_not_double_count_downloads(cfg, monkeypatch):
    src = StubSource("oa", {"A": Candidate(url="https://x.test/a.pdf", source="oa")})
    monkeypatch.setattr(pl, "REGISTRY", {"oa": src})
    monkeypatch.setattr(pl, "prepare_identifiers", lambda *a, **k: [])
    manifest = Manifest(cfg.manifest_path)
    pipe = pl.Pipeline(
        cfg,
        manifest,
        Console(file=io.StringIO()),
        sources=["oa"],
        attacher=FakeAttacher(ok=True),
    )
    pipe.client = mock_client(lambda r: httpx.Response(200, content=PDF_BYTES))
    pipe.ctx.client = pipe.client
    stats = pipe.run([make_item(key="A")])
    assert stats.ok == 1 and stats.attached == 1
    report = build_report(stats, cfg)
    assert report["summary"]["pdfs_downloaded"] == 1
    assert report["summary"]["attached"] == 1
    assert stats.items[0].status == STATUS_ATTACHED


def test_error_types_recorded(cfg, monkeypatch):
    src = StubSource("oa", default=Outcome.ERROR)
    monkeypatch.setattr(pl, "REGISTRY", {"oa": src})
    monkeypatch.setattr(pl, "prepare_identifiers", lambda *a, **k: [])
    manifest = Manifest(cfg.manifest_path)
    pipe = pl.Pipeline(cfg, manifest, Console(file=io.StringIO()), sources=["oa"])
    pipe.client = mock_client(lambda r: httpx.Response(500))
    pipe.ctx.client = pipe.client
    stats = pipe.run([make_item(key="E")])
    assert stats.error == 1
    assert (
        any(k.startswith("error:") for k in stats.errors_by_type)
        or "error" in stats.errors_by_type
    )
    assert stats.items[0].status == STATUS_ERROR


def test_print_run_summary_renders(cfg):
    stats = pl.RunStats(ok=2, attached=1, not_found=3, error=1)
    stats.by_source = {"unpaywall": 2}
    stats.sources_checked = {"unpaywall": {"found": 2, "not_found": 1}}
    stats.fields_corrected = {"doi_swap": 1}
    stats.errors_by_type = {"error:only_transient_failures": 1}
    report = build_report(stats, cfg, command="run", scope="BBNJ")
    buf = io.StringIO()
    print_run_summary(
        Console(file=buf, force_terminal=False), report, cfg.state_dir / "last-run.json"
    )
    out = buf.getvalue()
    assert "PDFs downloaded" in out and "2" in out
    assert "Fields corrected" in out
    assert "Sources checked" in out
    assert "Errors" in out
    assert "Run report:" in out
