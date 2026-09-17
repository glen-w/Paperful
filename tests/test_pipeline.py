"""Pipeline orchestration with stubbed sources and a mocked HTTP client."""

from __future__ import annotations

import io

import httpx
import pytest
from rich.console import Console

from paperful import pipeline as pl
from paperful.attach import AttachResult
from paperful.sources.base import Candidate, Outcome
from paperful.store import (
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
    def __init__(self, ok=True, by_key=None):
        self.ok = ok
        self.by_key = by_key or {}
        self.calls = []
        self.zl = None

    def attach(self, key, path, title=None):
        self.calls.append((key, path))
        if key in self.by_key:
            return self.by_key[key]
        return AttachResult(
            self.ok,
            attachment_key="ATT1" if self.ok else None,
            reason="success" if self.ok else "denied",
        )


class FakeZL:
    def __init__(self, pdf_parents=None, items=None):
        self._pdf_parents = set(pdf_parents or [])
        self._items = items or []

    def _pdf_parent_keys(self):
        return set(self._pdf_parents)

    def items_in_scope(self, collection_keys):
        return list(self._items)


@pytest.fixture
def pipe_factory(cfg, monkeypatch):
    def _make(registry: dict, sources: list[str], handler=None, attacher=None):
        monkeypatch.setattr(pl, "REGISTRY", registry)
        monkeypatch.setattr(pl, "prepare_identifiers", lambda *a, **k: [])
        manifest = Manifest(cfg.manifest_path)
        pipe = pl.Pipeline(
            cfg,
            manifest,
            Console(file=io.StringIO()),
            sources=sources,
            attacher=attacher,
        )
        client = mock_client(
            handler or (lambda r: httpx.Response(200, content=PDF_BYTES))
        )
        pipe.client = client
        pipe.ctx.client = client
        return pipe, manifest

    return _make


def test_oa_sources_run_in_order_and_scihub_only_after_all_miss(pipe_factory, cfg):
    oa1 = StubSource("oa1")
    oa2 = StubSource("oa2", {"B": Candidate(url="https://x.test/b.pdf", source="oa2")})
    sh = StubSource(
        "scihub", {"A": Candidate(url="https://m1.test/a.pdf", source="scihub")}
    )
    pipe, manifest = pipe_factory(
        {"oa1": oa1, "oa2": oa2, "scihub": sh}, ["oa1", "oa2", "scihub"]
    )
    items = [make_item(key="A"), make_item(key="B")]
    stats = pipe.run(items)

    assert stats.ok == 2 and stats.by_source == {"oa2": 1, "scihub": 1}
    assert sh.calls == ["A"]  # B was satisfied by an OA source, never reaches Sci-Hub
    assert manifest.get("B").source == "oa2" and manifest.get("A").source == "scihub"
    assert manifest.get("B").attempts == ["oa1:not_found", "oa2:found"]
    assert (
        cfg.out_dir
        / "Col"
        / "Smith - 2019 - A sufficiently long test title about marine governance.pdf"
    ).exists()


def test_alternate_urls_are_tried_after_download_failure(pipe_factory):
    def handler(req):
        if req.url.host == "blocked.test":
            return httpx.Response(403)
        return httpx.Response(200, content=PDF_BYTES)

    src = StubSource(
        "oa",
        {
            "A": Candidate(
                url="https://blocked.test/a.pdf",
                source="oa",
                alternates=["https://repo.test/a.pdf"],
            )
        },
    )
    pipe, manifest = pipe_factory({"oa": src}, ["oa"], handler=handler)
    pipe.run([make_item(key="A")])
    rec = manifest.get("A")
    assert rec.status == STATUS_OK and rec.url == "https://repo.test/a.pdf"
    assert "oa:download-failed(HTTP 403)" in rec.attempts


def test_miss_classification(pipe_factory):
    err_src = StubSource("oa", default=Outcome.ERROR)
    pipe, manifest = pipe_factory({"oa": err_src}, ["oa"])
    pipe.run(
        [
            make_item(key="NOID", doi=None, url=None, arxiv_id=None),
            make_item(key="ERR"),
        ]
    )
    assert manifest.get("NOID").status == STATUS_NO_IDENTIFIER
    assert (
        manifest.get("ERR").status == STATUS_ERROR
    )  # only transient failures -> retried next run

    nf_src = StubSource("oa", default=Outcome.NOT_FOUND)
    pipe2, manifest2 = pipe_factory({"oa": nf_src}, ["oa"])
    pipe2.run([make_item(key="NF")])
    assert manifest2.get("NF").status == STATUS_NOT_FOUND


def test_circuit_breaker_skips_source_after_repeated_blocks(pipe_factory, cfg):
    blocked = StubSource("blocked", default=Outcome.CAPTCHA)
    oa = StubSource("oa", default=Outcome.NOT_FOUND)
    pipe, manifest = pipe_factory({"oa": oa, "blocked": blocked}, ["oa", "blocked"])
    pipe.cfg.concurrency_oa = 1
    items = [make_item(key=f"I{i}") for i in range(5)]
    pipe.run(items)

    assert blocked.calls == ["I0", "I1", "I2"]
    assert "blocked:skipped(circuit open)" in manifest.get("I3").attempts
    assert "blocked:skipped(circuit open)" in manifest.get("I4").attempts


def test_source_routing_skips_inapplicable_sources(pipe_factory, cfg):
    oa = StubSource("unpaywall", default=Outcome.NOT_FOUND)
    scholar = StubSource("scholar", default=Outcome.NOT_FOUND)
    pipe, manifest = pipe_factory(
        {"unpaywall": oa, "scholar": scholar}, ["unpaywall", "scholar"]
    )
    pipe.try_all = False
    item = make_item(
        key="N",
        doi=None,
        url="https://www.npr.org/story",
        title="A long enough title for scholar routing",
    )
    pipe.run([item])

    assert oa.calls == []
    assert scholar.calls == ["N"]
    assert "unpaywall:skipped(not applicable)" in manifest.get("N").attempts


def test_make_client_loads_scholar_cookies(cfg, tmp_path):
    cookie_file = tmp_path / "scholar-cookies.txt"
    cookie_file.write_text(".google.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n")
    cfg.scholar_cookies = cookie_file
    client = pl.make_client(cfg)
    assert any(c.name == "SID" and c.value == "test" for c in client.cookies.jar)


def test_scholar_is_serial_source():
    assert "scholar" in pl._SERIAL_SOURCES


def test_circuit_breaker_trips_serial_scihub(pipe_factory):
    sh = StubSource("scihub", default=Outcome.CAPTCHA)
    pipe, manifest = pipe_factory({"scihub": sh}, ["scihub"])
    items = [make_item(key=f"S{i}") for i in range(4)]
    pipe.run(items)
    assert len(sh.calls) == 3
    skipped = [k for k in ("S0", "S1", "S2", "S3") if k not in sh.calls]
    assert len(skipped) == 1
    assert "scihub:skipped(circuit open)" in manifest.get(skipped[0]).attempts


def test_try_all_runs_inapplicable_sources(pipe_factory):
    oa = StubSource("unpaywall", default=Outcome.NOT_FOUND)
    pipe, manifest = pipe_factory({"unpaywall": oa}, ["unpaywall"])
    pipe.try_all = True
    pipe.run([make_item(key="N", doi=None, url="https://www.npr.org/story")])
    assert oa.calls == ["N"]


def test_scihub_captcha_and_error_statuses(pipe_factory):
    sh = StubSource(
        "scihub",
        {
            "C": Candidate.miss("scihub", Outcome.CAPTCHA, "m1=captcha unsolved"),
            "E": Candidate.miss("scihub", Outcome.ERROR, "m1=HTTP 502"),
        },
    )
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
    pipe2, manifest2 = pipe_factory(
        {"oa": src2}, ["oa"], attacher=FakeAttacher(ok=False)
    )
    pipe2.run([make_item(key="B")])
    assert manifest2.get("B").status == STATUS_ATTACH_FAILED
    assert manifest2.pending_attach()[0].itemKey == "B"


def test_attach_remaps_when_parent_key_missing(pipe_factory, tmp_path):
    from paperful.store import Record

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 remapped")
    attacher = FakeAttacher(
        by_key={
            "OLDKEY": AttachResult(
                False,
                reason="{'key': '', 'code': 400, 'message': 'Parent item 1/OLDKEY not found'}",
                code="parent_missing",
            ),
            "NEWKEY": AttachResult(
                True, attachment_key="ATT9", reason="success", code="success"
            ),
        }
    )
    attacher.zl = FakeZL(
        items=[make_item(key="NEWKEY", doi="10.1000/xyz", title="Remapped Title")]
    )
    pipe, manifest = pipe_factory({"oa": StubSource("oa")}, ["oa"], attacher=attacher)
    rec = Record(
        itemKey="OLDKEY",
        status=STATUS_OK,
        title="Remapped Title",
        doi="10.1000/xyz",
        path=str(pdf),
    )
    assert pipe.attach_record(rec) is True
    assert [c[0] for c in attacher.calls] == ["OLDKEY", "NEWKEY"]
    assert manifest.get("NEWKEY").status == STATUS_ATTACHED
    assert manifest.get("OLDKEY").status == STATUS_ATTACHED
    assert "remapped to NEWKEY" in manifest.get("OLDKEY").reason


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


def test_enrich_resolution_feeds_sources(pipe_factory, monkeypatch):
    def fake_prepare(client, item, **kwargs):
        item.doi = "10.9/found"
        item.doi_source = "crossref"
        item.doi_verified = "ok"
        return ["crossref:matched(0.97)"]

    src = StubSource("oa")
    pipe, manifest = pipe_factory({"oa": src}, ["oa"])
    monkeypatch.setattr(pl, "prepare_identifiers", fake_prepare)
    pipe.run([make_item(key="X", doi=None)])
    rec = manifest.get("X")
    assert rec.doi == "10.9/found" and rec.doi_source == "crossref"
    assert rec.attempts[0] == "crossref:matched(0.97)"


def test_verify_runs_when_doi_present(pipe_factory, monkeypatch):
    seen = []

    def fake_prepare(client, item, **kwargs):
        seen.append(item.doi)
        item.doi_verified = "ok"
        return ["verify:ok(0.99)"]

    monkeypatch.setattr(pl, "prepare_identifiers", fake_prepare)
    pipe, _ = pipe_factory({"oa": StubSource("oa")}, ["oa"])
    monkeypatch.setattr(pl, "prepare_identifiers", fake_prepare)
    pipe.run([make_item(key="W", doi="10.1/x")])
    assert seen == ["10.1/x"]


def test_suspect_doi_swap_feeds_sources(pipe_factory, monkeypatch):
    def fake_prepare(client, item, **kwargs):
        item.library_doi = "10.1/wrong"
        item.doi = "10.9/right"
        item.doi_source = "crossref"
        item.doi_verified = "swapped"
        return ["verify:suspect(0.20)", "swap:10.1/wrong->10.9/right"]

    src = StubSource("oa")
    pipe, manifest = pipe_factory({"oa": src}, ["oa"])
    monkeypatch.setattr(pl, "prepare_identifiers", fake_prepare)
    pipe.run([make_item(key="S", doi="10.1/wrong")])
    rec = manifest.get("S")
    assert rec.doi == "10.9/right"
    assert rec.library_doi == "10.1/wrong"
    assert rec.doi_verified == "swapped"
    assert src.calls == ["S"]


def test_verify_api_down_keeps_original_doi(pipe_factory, monkeypatch):
    from paperful.resolve import prepare_identifiers

    src = StubSource("oa")
    pipe, manifest = pipe_factory(
        {"oa": src},
        ["oa"],
        handler=lambda r: httpx.Response(500),
    )
    monkeypatch.setattr(pl, "prepare_identifiers", prepare_identifiers)
    pipe.run([make_item(key="U", doi="10.1/original", url=None)])
    rec = manifest.get("U")
    assert rec.doi == "10.1/original"
    assert rec.library_doi == "10.1/original"
    assert rec.doi_verified == "unknown"


def test_enrich_skipped_for_webpages_via_enrich_fn(pipe_factory, monkeypatch):
    """Pipeline still calls prepare; prepare_identifiers itself skips web types."""
    from paperful.resolve import prepare_identifiers

    monkeypatch.setattr(pl, "prepare_identifiers", prepare_identifiers)
    pipe, manifest = pipe_factory({"oa": StubSource("oa")}, ["oa"])
    pipe.run([make_item(key="W", doi=None, item_type="webpage")])
    assert not any(
        "crossref:" in a or "openalex:" in a for a in (manifest.get("W").attempts or [])
    )


def test_embedded_pdf_content_skips_http_download(pipe_factory):
    src = StubSource(
        "htmlpdf",
        {
            "A": Candidate(
                url="https://news.test/a", source="htmlpdf", content=PDF_BYTES
            )
        },
    )
    pipe, manifest = pipe_factory({"htmlpdf": src}, ["htmlpdf"])
    pipe.run(
        [make_item(key="A", item_type="webpage", doi=None, url="https://news.test/a")]
    )
    rec = manifest.get("A")
    assert rec.status in {STATUS_OK, STATUS_ATTACHED}
    assert rec.source == "htmlpdf"
    assert rec.url == "https://news.test/a"


def test_htmlpdf_runs_after_ezproxy_in_serial_chain(pipe_factory):
    ez = StubSource("ezproxy", default=Outcome.NOT_FOUND)
    hp = StubSource(
        "htmlpdf",
        {
            "W": Candidate(
                url="https://news.test/w", source="htmlpdf", content=PDF_BYTES
            )
        },
    )
    pipe, manifest = pipe_factory(
        {"ezproxy": ez, "htmlpdf": hp}, ["ezproxy", "htmlpdf"]
    )
    pipe.try_all = True
    pipe.run(
        [make_item(key="W", item_type="webpage", doi=None, url="https://news.test/w")]
    )
    assert ez.calls == ["W"]
    assert hp.calls == ["W"]
    assert manifest.get("W").source == "htmlpdf"


def test_invalid_embedded_pdf_content_fails(pipe_factory):
    src = StubSource(
        "htmlpdf",
        {
            "A": Candidate(
                url="https://news.test/a", source="htmlpdf", content=b"not-a-pdf"
            )
        },
    )
    pipe, manifest = pipe_factory({"htmlpdf": src}, ["htmlpdf"])
    pipe.run(
        [make_item(key="A", item_type="webpage", doi=None, url="https://news.test/a")]
    )
    rec = manifest.get("A")
    # download-failed without a not_found → error (retried next run)
    assert rec.status == STATUS_ERROR
    assert any("invalid embedded PDF" in a for a in rec.attempts)


def test_serial_chain_ezproxy_htmlpdf_then_scihub(pipe_factory):
    ez = StubSource("ezproxy", default=Outcome.NOT_FOUND)
    hp = StubSource("htmlpdf", default=Outcome.SKIPPED)
    sh = StubSource(
        "scihub", {"J": Candidate(url="https://m.test/j.pdf", source="scihub")}
    )
    pipe, manifest = pipe_factory(
        {"ezproxy": ez, "htmlpdf": hp, "scihub": sh},
        ["ezproxy", "htmlpdf", "scihub"],
    )
    pipe.try_all = True
    pipe.run([make_item(key="J", doi="10.1000/j", item_type="journalArticle")])
    assert ez.calls == ["J"]
    assert "J" in hp.calls
    assert sh.calls == ["J"]
    assert manifest.get("J").source == "scihub"


class _StubBrowser:
    def __init__(self, pdf=PDF_BYTES):
        self.pdf = pdf
        self.urls: list[str] = []

    def available(self) -> bool:
        return True

    def fetch_pdf(self, url, timeout_ms=60_000):
        self.urls.append(url)
        return self.pdf, url

    def close(self) -> None:
        return


def test_publisher_403_retries_via_browser_and_proxifies(pipe_factory, cfg):
    cfg.ezproxy_base = "https://scpo.idm.oclc.org/login?url="
    browser = _StubBrowser()
    src = StubSource(
        "unpaywall",
        {
            "A": Candidate(
                url="https://www.sciencedirect.com/science/article/pii/S1/pdfft",
                source="unpaywall",
            )
        },
    )
    pipe, manifest = pipe_factory(
        {"unpaywall": src},
        ["unpaywall"],
        handler=lambda r: httpx.Response(403),
    )
    pipe.browser = browser
    pipe.ctx.browser = browser
    pipe.run([make_item(key="A")])
    rec = manifest.get("A")
    assert rec.status == STATUS_OK
    assert "unpaywall:browser" in rec.attempts
    assert browser.urls[0].startswith("https://scpo.idm.oclc.org/login?url=")


def test_ezproxy_uses_browser_before_httpx(pipe_factory):
    browser = _StubBrowser()
    src = StubSource(
        "ezproxy",
        {
            "A": Candidate(
                url="https://www-sciencedirect-com.scpo.idm.oclc.org/pdfft",
                source="ezproxy",
            )
        },
    )
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(403)

    pipe, manifest = pipe_factory({"ezproxy": src}, ["ezproxy"], handler=handler)
    pipe.try_all = True
    pipe.browser = browser
    pipe.ctx.browser = browser
    pipe.run([make_item(key="A")])
    assert manifest.get("A").status == STATUS_OK
    assert calls == []
    assert "ezproxy:browser" in manifest.get("A").attempts


def test_oa_skips_same_publisher_host_after_403(pipe_factory):
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(403)

    up = StubSource(
        "unpaywall",
        {
            "A": Candidate(
                url="https://www.sciencedirect.com/science/article/pii/S1/pdfft",
                source="unpaywall",
            )
        },
    )
    oa = StubSource(
        "openalex",
        {
            "A": Candidate(
                url="https://www.sciencedirect.com/science/article/pii/S1/pdfft?alt=1",
                source="openalex",
            )
        },
    )
    pipe, manifest = pipe_factory(
        {"unpaywall": up, "openalex": oa},
        ["unpaywall", "openalex"],
        handler=handler,
    )
    pipe.run([make_item(key="A")])
    assert len(calls) == 1
    rec = manifest.get("A")
    assert any("publisher already blocked" in a for a in rec.attempts)

