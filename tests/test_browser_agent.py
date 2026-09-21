"""Browser-agent source, runner plumbing, routing, and recover CLI (stubbed)."""

from __future__ import annotations

import httpx
import pytest

from paperful import browser_agent as ba
from paperful.browser_agent import BrowserAgentError, RecoverResult, recover_start_url
from paperful.config import DEFAULT_SOURCES
from paperful.pipeline import _SERIAL_SOURCES
from paperful.routing import source_applicable
from paperful.sources import REGISTRY
from paperful.sources.base import Outcome
from paperful.sources.browser_agent import find, set_runner
from tests.conftest import PDF_BYTES, make_item


class _StubRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, cfg, item, url):
        self.calls.append(url)
        return self.result


@pytest.fixture
def stub_runner():
    def _install(result):
        r = _StubRunner(result)
        set_runner(r)
        return r

    yield _install
    set_runner(None)


# ---- registry / routing ------------------------------------------------------


def test_browser_agent_registered_serial_not_default():
    assert "browser_agent" in REGISTRY
    assert "browser_agent" not in DEFAULT_SOURCES
    assert "browser_agent" in _SERIAL_SOURCES


def test_routing_requires_llm_and_identifier(cfg):
    item = make_item()
    assert not source_applicable(item, cfg, "browser_agent")
    cfg.llm_enabled = True
    assert source_applicable(item, cfg, "browser_agent")
    assert source_applicable(
        make_item(doi=None, url="https://x.test/p"), cfg, "browser_agent"
    )
    assert not source_applicable(make_item(doi=None, url=None), cfg, "browser_agent")


def test_recover_start_url_prefers_doi():
    assert (
        recover_start_url(make_item(doi="10.1/a", url="https://x"))
        == "https://doi.org/10.1/a"
    )
    assert (
        recover_start_url(make_item(doi=None, url="https://x.test/p"))
        == "https://x.test/p"
    )
    assert recover_start_url(make_item(doi=None, url="ftp://x")) is None
    assert recover_start_url(make_item(doi=None, url=None)) is None


# ---- source.find -------------------------------------------------------------


def test_find_skipped_when_llm_off(ctx_factory, cfg, stub_runner):
    stub_runner(RecoverResult(PDF_BYTES, "stub"))
    cand = find(make_item(), ctx_factory(lambda r: httpx.Response(404)))
    assert cand.outcome is Outcome.SKIPPED and "llm.enabled" in cand.note


def test_find_skipped_without_identifier(ctx_factory, cfg, stub_runner, monkeypatch):
    cfg.llm_enabled = True
    monkeypatch.setattr(
        "paperful.sources.browser_agent.browser_agent_extra_available", lambda: True
    )
    stub_runner(RecoverResult(PDF_BYTES, "stub"))
    cand = find(
        make_item(doi=None, url=None), ctx_factory(lambda r: httpx.Response(404))
    )
    assert cand.outcome is Outcome.SKIPPED and "no DOI" in cand.note


def test_find_skipped_without_extra(ctx_factory, cfg, monkeypatch):
    cfg.llm_enabled = True
    monkeypatch.setattr(
        "paperful.sources.browser_agent.browser_agent_extra_available", lambda: False
    )
    cand = find(make_item(), ctx_factory(lambda r: httpx.Response(404)))
    assert cand.outcome is Outcome.SKIPPED and "browser-agent" in cand.note


def test_find_found_with_stub(ctx_factory, cfg, stub_runner, monkeypatch):
    cfg.llm_enabled = True
    monkeypatch.setattr(
        "paperful.sources.browser_agent.browser_agent_extra_available", lambda: True
    )
    r = stub_runner(RecoverResult(PDF_BYTES, "stub"))
    cand = find(make_item(doi="10.1000/x"), ctx_factory(lambda r: httpx.Response(404)))
    assert cand.outcome is Outcome.FOUND and cand.content == PDF_BYTES
    assert cand.source == "browser_agent" and r.calls == ["https://doi.org/10.1000/x"]


def test_find_captcha_stub(ctx_factory, cfg, stub_runner, monkeypatch):
    cfg.llm_enabled = True
    monkeypatch.setattr(
        "paperful.sources.browser_agent.browser_agent_extra_available", lambda: True
    )
    stub_runner(RecoverResult(None, "captcha", captcha=True))
    cand = find(make_item(), ctx_factory(lambda r: httpx.Response(404)))
    assert cand.outcome is Outcome.CAPTCHA


def test_find_not_found_stub(ctx_factory, cfg, stub_runner, monkeypatch):
    cfg.llm_enabled = True
    monkeypatch.setattr(
        "paperful.sources.browser_agent.browser_agent_extra_available", lambda: True
    )
    stub_runner(RecoverResult(None, "no PDF in download folder"))
    cand = find(make_item(), ctx_factory(lambda r: httpx.Response(404)))
    assert cand.outcome is Outcome.NOT_FOUND and "download folder" in cand.note


def test_find_runner_exception_is_error(ctx_factory, cfg, monkeypatch):
    cfg.llm_enabled = True
    monkeypatch.setattr(
        "paperful.sources.browser_agent.browser_agent_extra_available", lambda: True
    )

    class Boom:
        def run(self, *a):
            raise RuntimeError("agent exploded")

    set_runner(Boom())
    try:
        cand = find(make_item(), ctx_factory(lambda r: httpx.Response(404)))
    finally:
        set_runner(None)
    assert cand.outcome is Outcome.ERROR and cand.note == "RuntimeError"


# ---- runner plumbing ---------------------------------------------------------


def test_run_recover_requires_extra(cfg, monkeypatch):
    monkeypatch.setattr(ba, "browser_agent_extra_available", lambda: False)
    with pytest.raises(BrowserAgentError, match="browser-agent"):
        ba.run_recover(cfg, make_item(), "https://x")


def test_run_recover_requires_vault(cfg, monkeypatch):
    monkeypatch.setattr(ba, "browser_agent_extra_available", lambda: True)
    monkeypatch.setattr(ba, "profile_ready", lambda cfg: False)
    with pytest.raises(BrowserAgentError, match="session login"):
        ba.run_recover(cfg, make_item(), "https://x")


def test_run_recover_uses_injected_runner(cfg, monkeypatch):
    monkeypatch.setattr(ba, "browser_agent_extra_available", lambda: True)
    monkeypatch.setattr(ba, "profile_ready", lambda cfg: True)
    r = _StubRunner(RecoverResult(PDF_BYTES, "ok"))
    assert (
        ba.run_recover(cfg, make_item(), "https://x", runner=r).pdf_bytes == PDF_BYTES
    )


def test_largest_pdf_in_folder(tmp_path):
    (tmp_path / "a.pdf").write_bytes(PDF_BYTES)
    (tmp_path / "b.pdf").write_bytes(PDF_BYTES + b"x" * 500)
    (tmp_path / "c.pdf").write_bytes(b"<html>not a pdf</html>")
    (tmp_path / "tiny.pdf").write_bytes(b"%PDF-1.4 tiny")
    best = ba._largest_pdf_in(tmp_path, 1000)
    assert best == PDF_BYTES + b"x" * 500
    assert ba._largest_pdf_in(tmp_path / "missing", 1000) is None


# ---- pipeline integration: content candidate lands in manifest ---------------


def test_pipeline_records_browser_agent_source(cfg, stub_runner, monkeypatch):
    from rich.console import Console

    from paperful.pipeline import Pipeline
    from paperful.store import STATUS_OK, Manifest

    cfg.llm_enabled = True
    monkeypatch.setattr(
        "paperful.sources.browser_agent.browser_agent_extra_available", lambda: True
    )
    stub_runner(RecoverResult(PDF_BYTES, "stub"))
    manifest = Manifest(cfg.manifest_path)
    pipe = Pipeline(
        cfg,
        manifest,
        Console(quiet=True),
        sources=["browser_agent"],
        try_all=True,
        use_browser=False,
    )
    assert pipe.browser is None
    item = make_item(key="REC1")
    stats = pipe.run([item])
    rec = manifest.get("REC1")
    assert stats.ok == 1 and rec is not None
    assert rec.status == STATUS_OK and rec.source == "browser_agent"
    assert rec.path and rec.path.endswith(".pdf")
    assert stats.by_source.get("browser_agent") == 1


# ---- doctor floor pattern ----------------------------------------------------


@pytest.mark.parametrize(
    "model,small",
    [
        ("qwen2.5:7b", True),
        ("llama3.1:8b", True),
        ("qwen2.5:14b", False),
        ("qwen3:32b", False),
        ("gpt-4.1-mini", False),
        ("phi3:3.8b", True),
    ],
)
def test_doctor_model_floor(model, small):
    from paperful.doctor import _model_below_agent_floor

    assert _model_below_agent_floor(model) is small
