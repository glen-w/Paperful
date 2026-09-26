"""Run report / end-of-run summary."""

from __future__ import annotations

import io
import json

import httpx
import pytest
from rich.console import Console

from paperful import pipeline as pl
from paperful.runreport import (
    RUN_REPORT_ITEM_KEYS,
    RUN_REPORT_KEYS,
    RUN_REPORT_PATH_KEYS,
    RUN_REPORT_SUMMARY_KEYS,
    ItemOutcome,
    build_report,
    classify_enrichment,
    error_type_for,
    low_download_advice,
    outcome_banner,
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


def test_run_report_required_keys_and_banner(cfg):
    class Stats:
        started_at = 0
        finished_at = 0
        items = []

    report = build_report(Stats(), cfg, command="run", scope="library", write_api=True)
    assert RUN_REPORT_KEYS <= report.keys()
    assert RUN_REPORT_SUMMARY_KEYS <= report["summary"].keys()
    assert RUN_REPORT_PATH_KEYS <= report["paths"].keys()
    assert report["summary"]["write_api"] is True
    assert (
        outcome_banner(report["summary"])
        == "downloaded 0 · attached 0 · deferred 0 · not_found 0 · write-api yes"
    )
    report["summary"]["pdfs_downloaded"] = 2
    report["summary"]["attached"] = 1
    report["summary"]["skipped_manifest"] = 3
    report["summary"]["linked_url_skipped"] = 1
    report["summary"]["not_found"] = 4
    report["summary"]["write_api"] = False
    assert (
        outcome_banner(report["summary"])
        == "downloaded 2 · attached 1 · deferred 4 · not_found 4 · write-api no"
    )
    item = {
        "itemKey": "K",
        "title": "T",
        "status": "ok",
        "source": "unpaywall",
        "reason": "",
        "doi": None,
        "doi_verified": "",
        "attempts": [],
        "fields_corrected": [],
        "path": None,
        "error_type": None,
    }
    assert RUN_REPORT_ITEM_KEYS <= item.keys()


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
    assert report["summary"]["browser_misses"] == {}
    assert report["summary"]["agent_after_playwright"] == 0

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


def test_browser_miss_rollup(cfg):
    stats = pl.RunStats()
    stats.items = [
        ItemOutcome(
            itemKey="A",
            title="t",
            status="not_found",
            attempts=["browser_agent:not_found(paywall @springer.com; steps 3/8)"],
        ),
        ItemOutcome(
            itemKey="B",
            title="t",
            status="not_found",
            attempts=["browser_agent:not_found(paywall @wiley.com)"],
        ),
        ItemOutcome(
            itemKey="C",
            title="t",
            status="attached",
            attempts=[
                "scholar:browser-failed(no download control @x.test)",
                "browser_agent:found(browser_agent download; after scholar:browser-failed(no download control @x.test))",
            ],
        ),
    ]
    report = build_report(stats, cfg)
    assert report["summary"]["browser_misses"] == {"paywall": 2}
    assert report["summary"]["not_downloaded"] == {"paywall": 2}
    assert report["summary"]["agent_after_playwright"] == 1


def test_not_downloaded_rollup_prefers_the_block(cfg):
    stats = pl.RunStats()
    stats.items = [
        ItemOutcome(
            itemKey="CF",
            title="t",
            status="not_found",
            reason="closed",
            attempts=[
                "unpaywall:not_found",
                "browser_agent:not_found(cloudflare @wiley.com; security verification; steps 3/8)",
            ],
        ),
        ItemOutcome(
            itemKey="CAP",
            title="t",
            status="captcha",
            reason="captcha unsolved",
            attempts=["scihub:captcha(captcha unsolved)"],
        ),
        ItemOutcome(
            itemKey="MISS",
            title="t",
            status="not_found",
            reason="closed",
            attempts=["unpaywall:not_found", "openalex:not_found"],
        ),
        ItemOutcome(
            itemKey="SAVED",
            title="t",
            status="attached",
            attempts=["browser_agent:not_found(cloudflare @springer.com)"],
        ),
        ItemOutcome(
            itemKey="EXP",
            title="t",
            status="retryable",
            reason="session expired",
            attempts=["ezproxy:skipped(session expired)"],
        ),
        ItemOutcome(
            itemKey="DL",
            title="t",
            status="error",
            reason="only transient failures",
            attempts=["unpaywall:download-failed(timeout)"],
        ),
        ItemOutcome(
            itemKey="NONE",
            title="t",
            status="no_identifier",
            reason="no DOI, arXiv id or URL",
            attempts=[],
        ),
    ]
    report = build_report(stats, cfg)
    assert report["summary"]["not_downloaded"] == {
        "cloudflare": 1,
        "captcha": 1,
        "not_found": 1,
        "session_expired": 1,
        "download_failed": 1,
        "no_identifier": 1,
    }
    buf = io.StringIO()
    print_run_summary(Console(file=buf, force_terminal=False, width=120), report)
    flat = " ".join(buf.getvalue().split())
    assert "Not downloaded" in flat
    assert "not found 1" in flat
    assert "cloudflare 1" in flat
    assert "captcha 1" in flat
    assert "session expired 1" in flat
    assert "download failed 1" in flat
    assert "no identifier 1" in flat
    assert "session login ezproxy" in flat


def test_paywall_prices_sum_unsaved_articles(cfg):
    stats = pl.RunStats()
    stats.items = [
        ItemOutcome(
            itemKey="A",
            title="t",
            status="not_found",
            attempts=["browser_agent:not_found(paywall @springer.com; price 39.95 EUR)"],
        ),
        ItemOutcome(
            itemKey="B",
            title="t",
            status="not_found",
            attempts=["browser_agent:not_found(paywall @wiley.com; price 39.95 EUR)"],
        ),
        ItemOutcome(
            itemKey="C",
            title="t",
            status="not_found",
            attempts=["browser_agent:not_found(paywall @elsevier.com; price 29.95 USD)"],
        ),
        ItemOutcome(
            itemKey="D",
            title="t",
            status="attached",
            attempts=["browser_agent:not_found(paywall @springer.com; price 39.95 EUR)"],
        ),
    ]
    report = build_report(stats, cfg)
    assert report["summary"]["paywall_prices"] == {
        "EUR": {"articles": 2, "total": "79.90"},
        "USD": {"articles": 1, "total": "29.95"},
    }
    buf = io.StringIO()
    print_run_summary(Console(file=buf, force_terminal=False, width=120), report)
    flat = " ".join(buf.getvalue().split())
    assert "To buy" in flat
    assert "€79.90 for 2 articles" in flat
    assert "$29.95 for 1 article" in flat


def test_print_run_summary_renders(cfg):
    stats = pl.RunStats(ok=2, attached=1, not_found=3, error=1)
    stats.by_source = {"unpaywall": 2}
    stats.sources_checked = {"unpaywall": {"found": 2, "not_found": 1}}
    stats.fields_corrected = {"doi_swap": 1}
    stats.errors_by_type = {"error:only_transient_failures": 1}
    stats.attach_failed_by_code = {"quota": 2}
    report = build_report(stats, cfg, command="run", scope="BBNJ")
    buf = io.StringIO()
    print_run_summary(
        Console(file=buf, force_terminal=False), report, cfg.state_dir / "last-run.json"
    )
    out = buf.getvalue()
    assert "downloaded 2 · attached 1 · deferred 0 · not_found 3 · write-api unknown" in out
    assert "PDFs downloaded" in out and "2" in out
    assert "Fields corrected" in out
    assert "Sources checked" in out
    assert "Errors" in out
    assert "Run report:" in out
    assert "Few PDFs" not in out
    flat = " ".join(out.split())
    assert "Quota:" in flat and "paperful attach" in flat


def test_low_download_advice_names_the_retry(cfg):
    assert low_download_advice(downloaded=7, sought=8) is None
    assert low_download_advice(downloaded=2, sought=7) is None
    note = low_download_advice(downloaded=108, sought=981, collection="Inbox/Basketball")
    assert note is not None
    assert "session login ezproxy" in note
    assert "session login scholar" in note
    assert 'paperful run -C "Inbox/Basketball" --retry-failed' in note
    assert "after 2021" in note
    stats = pl.RunStats(ok=108, attached=108, not_found=870)
    report = build_report(stats, cfg, command="run", scope="Inbox/Basketball")
    buf = io.StringIO()
    print_run_summary(Console(file=buf, force_terminal=False, width=120), report)
    assert 'paperful run -C "Inbox/Basketball" --retry-failed' in buf.getvalue()


def test_write_run_report_skips_pack_when_none_open(cfg):
    report = {
        "schema": "paperful.run_report.v1",
        "command": "gaps",
        "summary": {"items": 1},
        "items": [],
    }
    path = write_run_report(cfg, report, as_last_run=False)
    assert path is not None and path.exists()
    assert not (cfg.state_dir / "packs").exists()
    assert not (cfg.state_dir / "last-run.json").exists()


def test_pack_open_append_opt_out_close_show(cfg, monkeypatch):
    import pytest

    from paperful.pack import PackError, close_pack, open_pack, show_payload

    pack = open_pack(cfg, label="bbnj")
    assert (cfg.state_dir / "packs" / "current").read_text().strip() == pack["id"]
    report = {
        "schema": "paperful.run_report.v1",
        "command": "gaps",
        "scope": "BBNJ",
        "started_at": "2026-09-21T03:00:00+00:00",
        "finished_at": "2026-09-21T03:00:02+00:00",
        "summary": {
            "items": 2,
            "no_stored_pdf": 1,
            "linked_url_only": 0,
            "missing_doi": 0,
        },
        "items": [{"itemKey": "I2", "title": "T", "status": "no_stored_pdf"}],
    }
    path = write_run_report(cfg, report, as_last_run=False)
    assert path is not None
    saved = json.loads((cfg.state_dir / "packs" / f"{pack['id']}.json").read_text())
    assert saved["scope"] == "BBNJ"
    assert saved["steps"][0]["command"] == "gaps"
    assert saved["steps"][0]["report"] == path.name
    assert "itemKey" not in saved["steps"][0]

    monkeypatch.setenv("PAPERFUL_PACK", "off")
    write_run_report(cfg, {**report, "command": "lint"}, as_last_run=False)
    saved = json.loads((cfg.state_dir / "packs" / f"{pack['id']}.json").read_text())
    assert len(saved["steps"]) == 1

    monkeypatch.delenv("PAPERFUL_PACK", raising=False)
    closed = close_pack(cfg)
    assert closed["status"] == "closed"
    assert closed["closed_at"]
    assert not (cfg.state_dir / "packs" / "current").exists()
    shown = show_payload(cfg, closed)
    assert shown["steps"][0]["summary"]["items"] == 2
    assert "itemKey" not in shown["steps"][0]

    with pytest.raises(PackError):
        close_pack(cfg)
    open_pack(cfg)
    with pytest.raises(PackError):
        open_pack(cfg)


def test_blank_label_is_omitted_and_scope_sticks(cfg):
    from paperful.pack import open_pack

    pack = open_pack(cfg, label="   ")
    assert "label" not in pack
    first = {
        "schema": "paperful.run_report.v1",
        "command": "gaps",
        "scope": "BBNJ",
        "summary": {"items": 1},
        "items": [],
    }
    write_run_report(cfg, first, as_last_run=False)
    write_run_report(
        cfg,
        {**first, "command": "lint", "scope": "other"},
        as_last_run=False,
    )
    saved = json.loads((cfg.state_dir / "packs" / f"{pack['id']}.json").read_text())
    assert saved["scope"] == "BBNJ"
    assert [step["command"] for step in saved["steps"]] == ["gaps", "lint"]


def test_closed_or_corrupt_pack_does_not_append(cfg):
    from paperful.pack import PackError, close_pack, open_pack

    pack = open_pack(cfg)
    path = cfg.state_dir / "packs" / f"{pack['id']}.json"
    data = json.loads(path.read_text())
    data["status"] = "closed"
    path.write_text(json.dumps(data))
    write_run_report(
        cfg,
        {"command": "lint", "scope": "X", "summary": {"findings": 1}, "items": []},
        as_last_run=False,
    )
    assert json.loads(path.read_text())["steps"] == []

    path.write_text("{not json")
    write_run_report(
        cfg,
        {"command": "gaps", "summary": {}, "items": []},
        as_last_run=False,
    )
    assert path.read_text().startswith("{not")

    path.unlink()
    with pytest.raises(PackError, match="missing"):
        close_pack(cfg)
    assert not (cfg.state_dir / "packs" / "current").exists()


def test_show_payload_omits_missing_child_items(cfg):
    from paperful.pack import headline, show_payload

    pack = {
        "schema": "paperful.pack.v1",
        "id": "x",
        "status": "closed",
        "scope": "BBNJ",
        "steps": [{"command": "gaps", "report": "missing-gaps.json"}],
    }
    shown = show_payload(cfg, pack)
    assert shown["steps"][0]["summary"] == {}
    assert shown["steps"][0]["duration_s"] is None
    assert "items" not in shown["steps"][0]["summary"] or shown["steps"][0]["summary"] == {}

    assert "findings 3" == headline("lint", {"findings": 3, "findings_by_code": {}})
    assert "summarized 2, failed 1" == headline(
        "summarize", {"summarized": 2, "failed": 1, "dest": "both"}
    )
    assert headline("fix-metadata", {"patches_proposed": 4}) == "proposed 4"
    assert headline("fix-metadata", {"patches_proposed": 4, "patches_applied": 3}) == (
        "applied 3/4"
    )
    assert "downloaded 2" in headline(
        "run", {"pdfs_downloaded": 2, "attached": 1, "not_found": 9}
    )
    assert headline("synthesize", {"included": 5, "missing": 1}) == "included 5, missing 1"
    assert headline("other", {"ok": True, "n": 2}) == "n 2"
