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
from paperful.sources.base import Candidate, Outcome
from paperful.sources.browser_agent import find, set_runner
from tests.conftest import PDF_BYTES, make_item, mock_client


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


def test_recover_uses_system_chrome_not_bundled_chromium():
    kwargs = ba._browser_launch_kwargs()
    assert kwargs["channel"] == "chrome"
    assert kwargs["enable_default_extensions"] is True


def test_empty_extension_cache_is_dropped(tmp_path):
    (tmp_path / "good.crx").write_bytes(b"Cr24")
    (tmp_path / "empty.crx").write_bytes(b"")
    broken = tmp_path / "empty"
    broken.mkdir()
    (broken / "leftover.txt").write_text("x", encoding="utf-8")
    kept = tmp_path / "good"
    kept.mkdir()
    (kept / "manifest.json").write_text("{}", encoding="utf-8")

    ba._drop_empty_extension_cache(tmp_path)

    assert (tmp_path / "good.crx").is_file()
    assert (kept / "manifest.json").is_file()
    assert not (tmp_path / "empty.crx").exists()
    assert not broken.exists()


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


def test_stable_largest_pdf_waits_for_unchanged_size(tmp_path):
    path = tmp_path / "growing.pdf"
    path.write_bytes(PDF_BYTES)
    sizes: dict[str, int] = {}
    assert ba._stable_largest_pdf(tmp_path, 1000, sizes) is None
    assert ba._stable_largest_pdf(tmp_path, 1000, sizes) == PDF_BYTES
    path.write_bytes(PDF_BYTES + b"x" * 100)
    assert ba._stable_largest_pdf(tmp_path, 1000, sizes) is None
    assert ba._stable_largest_pdf(tmp_path, 1000, sizes) == PDF_BYTES + b"x" * 100


def test_result_from_downloads_prefers_pdf_over_miss(tmp_path):
    (tmp_path / "a.pdf").write_bytes(PDF_BYTES)
    got = ba._result_from_downloads(tmp_path, 1000, miss="timeout", captcha=False)
    assert got.pdf_bytes == PDF_BYTES and got.note == "browser_agent download"
    empty = ba._result_from_downloads(tmp_path / "none", 1000, miss="timeout")
    assert empty.pdf_bytes is None and empty.note == "timeout"


def test_run_until_pdf_stops_agent_when_file_lands(tmp_path):
    import asyncio

    class FakeAgent:
        def __init__(self):
            self.stopped = False
            self.steps = 0

        def stop(self):
            self.stopped = True

        async def run(self, max_steps=20, on_step_end=None):
            for _ in range(max_steps):
                if self.stopped:
                    return
                self.steps += 1
                if self.steps == 1:
                    (tmp_path / "hit.pdf").write_bytes(PDF_BYTES)
                if on_step_end is not None:
                    await on_step_end(self)
                await asyncio.sleep(0.05)

    agent = FakeAgent()
    asyncio.run(
        ba._run_until_pdf(
            agent,
            tmp_path,
            1000,
            max_steps=20,
            max_wall_s=5.0,
            interval_s=0.05,
        )
    )
    assert agent.stopped
    assert agent.steps < 20


def test_stop_when_pdf_lands_calls_stop(tmp_path):
    import asyncio

    class Stub:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    agent = Stub()
    (tmp_path / "a.pdf").write_bytes(PDF_BYTES)
    asyncio.run(
        asyncio.wait_for(
            ba._stop_when_pdf_lands(agent, tmp_path, 1000, interval_s=0.05),
            timeout=2.0,
        )
    )
    assert agent.stopped


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


def test_pipeline_recover_after_scholar_miss(cfg, monkeypatch):
    import io

    from rich.console import Console

    from paperful.pipeline import Pipeline
    from paperful.store import STATUS_OK, Manifest
    from tests.test_pipeline import StubSource

    cfg.llm_enabled = True
    scholar = StubSource("scholar", default=Outcome.NOT_FOUND)
    agent = StubSource(
        "browser_agent",
        {"A": Candidate(url="", source="browser_agent", content=PDF_BYTES)},
    )
    monkeypatch.setattr(
        "paperful.pipeline.REGISTRY",
        {"unpaywall": StubSource("unpaywall"), "scholar": scholar, "browser_agent": agent},
    )
    monkeypatch.setattr("paperful.pipeline.prepare_identifiers", lambda *a, **k: [])
    pipe = Pipeline(
        cfg,
        Manifest(cfg.manifest_path),
        Console(file=io.StringIO()),
        sources=["unpaywall", "scholar", "browser_agent"],
        try_all=True,
        use_browser=False,
    )
    stats = pipe.run([make_item(key="A")])
    rec = pipe.manifest.get("A")
    assert scholar.calls == ["A"] and agent.calls == ["A"]
    assert stats.ok == 1 and rec is not None and rec.source == "browser_agent"
    assert rec.status == STATUS_OK


def test_pipeline_recover_skipped_without_browser_lane_failure(cfg, monkeypatch):
    import io

    from rich.console import Console

    from paperful.pipeline import Pipeline
    from paperful.store import Manifest
    from tests.test_pipeline import StubSource

    cfg.llm_enabled = True
    scholar = StubSource("scholar")
    agent = StubSource(
        "browser_agent",
        {"N": Candidate(url="", source="browser_agent", content=PDF_BYTES)},
    )
    monkeypatch.setattr(
        "paperful.pipeline.REGISTRY",
        {"unpaywall": StubSource("unpaywall"), "scholar": scholar, "browser_agent": agent},
    )
    monkeypatch.setattr("paperful.pipeline.prepare_identifiers", lambda *a, **k: [])
    pipe = Pipeline(
        cfg,
        Manifest(cfg.manifest_path),
        Console(file=io.StringIO()),
        sources=["unpaywall", "scholar", "browser_agent"],
        try_all=False,
        use_browser=False,
    )
    item = make_item(key="N", doi=None, title="x", url="https://x.test/p")
    pipe.run([item])
    rec = pipe.manifest.get("N")
    assert scholar.calls == []
    assert agent.calls == []
    assert rec is not None
    assert "browser_agent:skipped(no browser-lane failure)" in rec.attempts


def test_pipeline_releases_browser_before_agent(cfg, monkeypatch):
    import io

    from rich.console import Console

    from paperful.pipeline import Pipeline
    from paperful.store import Manifest
    from tests.test_pipeline import StubSource

    class FakeBrowser:
        def __init__(self):
            self.closed = 0

        def close(self):
            self.closed += 1

        def available(self):
            return True

    scholar = StubSource("scholar", default=Outcome.NOT_FOUND)
    agent = StubSource("browser_agent", default=Outcome.NOT_FOUND)
    monkeypatch.setattr(
        "paperful.pipeline.REGISTRY",
        {"scholar": scholar, "browser_agent": agent},
    )
    monkeypatch.setattr("paperful.pipeline.prepare_identifiers", lambda *a, **k: [])
    pipe = Pipeline(
        cfg,
        Manifest(cfg.manifest_path),
        Console(file=io.StringIO()),
        sources=["scholar", "browser_agent"],
        try_all=True,
        use_browser=False,
    )
    fake = FakeBrowser()
    pipe.browser = fake
    pipe.ctx.browser = fake
    pipe.run([make_item(key="A")])
    assert fake.closed == 1
    assert pipe.browser is None
    assert agent.calls == ["A"]


def test_pipeline_oa_hit_never_calls_recover(cfg, monkeypatch):
    import io

    from rich.console import Console

    from paperful.pipeline import Pipeline
    from paperful.store import Manifest
    from tests.test_pipeline import StubSource

    oa = StubSource(
        "unpaywall",
        {"A": Candidate(url="https://x.test/a.pdf", source="unpaywall")},
    )
    scholar = StubSource("scholar")
    agent = StubSource("browser_agent")
    monkeypatch.setattr(
        "paperful.pipeline.REGISTRY",
        {"unpaywall": oa, "scholar": scholar, "browser_agent": agent},
    )
    monkeypatch.setattr("paperful.pipeline.prepare_identifiers", lambda *a, **k: [])
    pipe = Pipeline(
        cfg,
        Manifest(cfg.manifest_path),
        Console(file=io.StringIO()),
        sources=["unpaywall", "scholar", "browser_agent"],
        try_all=True,
        use_browser=False,
    )
    pipe.client = mock_client(lambda r: httpx.Response(200, content=PDF_BYTES))
    pipe.ctx.client = pipe.client
    pipe.run([make_item(key="A")])
    assert scholar.calls == [] and agent.calls == []
    assert pipe.manifest.get("A").source == "unpaywall"


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
