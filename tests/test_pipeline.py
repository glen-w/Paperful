"""Pipeline orchestration with stubbed sources and a mocked HTTP client."""

from __future__ import annotations

import io

import httpx
import pytest
from rich.console import Console

from scihub_dl import pipeline as pl
from scihub_dl.attach import AttachResult
from scihub_dl.sources.base import Candidate, Outcome
from scihub_dl.store import (
    STATUS_ATTACH_FAILED,
    STATUS_ATTACHED,
    STATUS_CAPTCHA,
    STATUS_ERROR,
    STATUS_NO_IDENTIFIER,
    STATUS_NOT_FOUND,
    STATUS_OK,
    Manifest,
)
from tests.conftest import PDF_BYTES, make_item, mock_client


class StubSource:
    """Scripted source: `results` maps item key -> Candidate; records call order."""

    def __init__(self, name, results=None, default=Outcome.NOT_FOUND):
        self.NAME = name
        self.results = results or {}
        self.default = default
        self.calls: list[str] = []

    def find(self, item, ctx):
        self.calls.append(item.key)
        cand = self.results.get(item.key)
        if cand is None:
            return Candidate.miss(self.NAME, self.default)
        cand.source = self.NAME
        return cand


class FakeAttacher:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def attach(self, key, path, title=None):
        self.calls.append((key, path))
        return AttachResult(self.ok, attachment_key="ATT1" if self.ok else None, reason="success" if self.ok else "denied")


@pytest.fixture
def pipe_factory(cfg, monkeypatch):
    def _make(registry: dict, sources: list[str], handler=None, attacher=None):
        monkeypatch.setattr(pl, "REGISTRY", registry)
        monkeypatch.setattr(pl, "crossref_lookup", lambda *a, **k: None)
        manifest = Manifest(cfg.manifest_path)
        pipe = pl.Pipeline(cfg, manifest, Console(file=io.StringIO()), sources=sources, attacher=attacher)
        client = mock_client(handler or (lambda r: httpx.Response(200, content=PDF_BYTES)))
        pipe.client = client
        pipe.ctx.client = client
        return pipe, manifest

    return _make


def test_oa_sources_run_in_order_and_scihub_only_after_all_miss(pipe_factory, cfg):
    oa1 = StubSource("oa1")
    oa2 = StubSource("oa2", {"B": Candidate(url="https://x.test/b.pdf", source="oa2")})
    sh = StubSource("scihub", {"A": Candidate(url="https://m1.test/a.pdf", source="scihub")})
    pipe, manifest = pipe_factory({"oa1": oa1, "oa2": oa2, "scihub": sh}, ["oa1", "oa2", "scihub"])
    items = [make_item(key="A"), make_item(key="B")]
    stats = pipe.run(items)

    assert stats.ok == 2 and stats.by_source == {"oa2": 1, "scihub": 1}
    assert sh.calls == ["A"]  # B was satisfied by an OA source, never reaches Sci-Hub
    assert manifest.get("B").source == "oa2" and manifest.get("A").source == "scihub"
    assert manifest.get("B").attempts == ["oa1:not_found", "oa2:found"]
    assert (cfg.out_dir / "Col" / "Smith - 2019 - A sufficiently long test title about marine governance.pdf").exists()


def test_alternate_urls_are_tried_after_download_failure(pipe_factory):
    def handler(req):
        if req.url.host == "blocked.test":
            return httpx.Response(403)
        return httpx.Response(200, content=PDF_BYTES)

    src = StubSource("oa", {"A": Candidate(url="https://blocked.test/a.pdf", source="oa", alternates=["https://repo.test/a.pdf"])})
    pipe, manifest = pipe_factory({"oa": src}, ["oa"], handler=handler)
    pipe.run([make_item(key="A")])
    rec = manifest.get("A")
    assert rec.status == STATUS_OK and rec.url == "https://repo.test/a.pdf"
    assert "oa:download-failed(HTTP 403)" in rec.attempts


def test_miss_classification(pipe_factory):
    err_src = StubSource("oa", default=Outcome.ERROR)
    pipe, manifest = pipe_factory({"oa": err_src}, ["oa"])
    pipe.run([
        make_item(key="NOID", doi=None, url=None, arxiv_id=None),
        make_item(key="ERR"),
    ])
    assert manifest.get("NOID").status == STATUS_NO_IDENTIFIER
    assert manifest.get("ERR").status == STATUS_ERROR  # only transient failures -> retried next run

    nf_src = StubSource("oa", default=Outcome.NOT_FOUND)
    pipe2, manifest2 = pipe_factory({"oa": nf_src}, ["oa"])
    pipe2.run([make_item(key="NF")])
    assert manifest2.get("NF").status == STATUS_NOT_FOUND


def test_scihub_captcha_and_error_statuses(pipe_factory):
    sh = StubSource("scihub", {
        "C": Candidate.miss("scihub", Outcome.CAPTCHA, "m1=captcha unsolved"),
        "E": Candidate.miss("scihub", Outcome.ERROR, "m1=HTTP 502"),
    })
    pipe, manifest = pipe_factory({"scihub": sh}, ["scihub"])
    pipe.run([make_item(key="C"), make_item(key="E"), make_item(key="N")])
    assert manifest.get("C").status == STATUS_CAPTCHA
    assert manifest.get("E").status == STATUS_ERROR
    assert manifest.get("N").status == STATUS_NOT_FOUND
    assert manifest.get("C").attempts[-1].startswith("scihub:captcha(")


def test_scihub_skipped_for_items_without_doi(pipe_factory):
    sh = StubSource("scihub")
    pipe, manifest = pipe_factory({"scihub": sh}, ["scihub"])
    pipe.run([make_item(key="U", doi=None, url="https://x.test/p")])
    assert sh.calls == []
    assert manifest.get("U").status == STATUS_NOT_FOUND


def test_attach_after_download_success_and_failure(pipe_factory):
    src = StubSource("oa", {"A": Candidate(url="https://x.test/a.pdf", source="oa")})
    ok_attacher = FakeAttacher(ok=True)
    pipe, manifest = pipe_factory({"oa": src}, ["oa"], attacher=ok_attacher)
    stats = pipe.run([make_item(key="A")])
    assert manifest.get("A").status == STATUS_ATTACHED and stats.attached == 1
    assert ok_attacher.calls[0][0] == "A"

    src2 = StubSource("oa", {"B": Candidate(url="https://x.test/b.pdf", source="oa")})
    pipe2, manifest2 = pipe_factory({"oa": src2}, ["oa"], attacher=FakeAttacher(ok=False))
    pipe2.run([make_item(key="B")])
    assert manifest2.get("B").status == STATUS_ATTACH_FAILED
    assert manifest2.pending_attach()[0].itemKey == "B"


def test_batches_and_stop_flag(pipe_factory):
    src = StubSource("oa")
    pipe, manifest = pipe_factory({"oa": src}, ["oa"])
    items = [make_item(key=f"K{i}") for i in range(7)]
    pipe.run(items, batch_size=3)
    assert len(manifest.records) == 7

    pipe2, manifest2 = pipe_factory({"oa": StubSource("oa")}, ["oa"])
    pipe2.stop()
    pipe2.run([make_item(key="Z")])
    assert manifest2.get("Z") is None  # nothing processed once stopped


def test_crossref_resolution_feeds_sources(pipe_factory, monkeypatch):
    from scihub_dl.resolve import CrossrefMatch

    src = StubSource("oa")
    pipe, manifest = pipe_factory({"oa": src}, ["oa"])  # factory stubs crossref to None; override after
    monkeypatch.setattr(pl, "crossref_lookup", lambda *a, **k: CrossrefMatch("10.9/found", 0.97, "t", 2019))
    pipe.run([make_item(key="X", doi=None)])
    rec = manifest.get("X")
    assert rec.doi == "10.9/found" and rec.doi_source == "crossref"
    assert rec.attempts[0] == "crossref:matched(0.97)"


def test_crossref_not_used_for_webpages(pipe_factory, monkeypatch):
    called = []
    monkeypatch.setattr(pl, "crossref_lookup", lambda *a, **k: called.append(1))
    pipe, _ = pipe_factory({"oa": StubSource("oa")}, ["oa"])
    pipe.run([make_item(key="W", doi=None, item_type="webpage")])
    assert called == []
