"""Camofox recover lane: config, routing, and mocked REST recover."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import httpx
import pytest

from paperful.camofox_client import CamofoxClient, CamofoxLink
from paperful.camofox_recover import _rank_pdf_links, run_camofox_recover
from paperful.config import Config
from paperful.routing import order_run, with_camofox_lane, with_recover_lane
from paperful.sources import camofox as camofox_src
from paperful.sources.base import Context, Outcome
from tests.conftest import PDF_BYTES, make_item


def test_with_camofox_lane_disabled(cfg: Config):
    listed = with_camofox_lane(cfg, ["unpaywall", "ezproxy", "htmlpdf"])
    assert "camofox" not in listed


def test_with_camofox_lane_inserts_before_browser_agent(cfg: Config, monkeypatch):
    cfg.camofox_enabled = True
    cfg.llm_enabled = True
    monkeypatch.setattr(
        "paperful.browser_agent.browser_agent_extra_available", lambda: True
    )
    listed = with_recover_lane(cfg, ["unpaywall", "ezproxy", "htmlpdf"])
    listed = with_camofox_lane(cfg, listed)
    assert listed.index("camofox") < listed.index("browser_agent")
    assert listed.index("htmlpdf") < listed.index("camofox")


def test_with_camofox_lane_cli_off(cfg: Config):
    cfg.camofox_enabled = True
    listed = with_camofox_lane(
        cfg, ["unpaywall", "ezproxy"], during_run=False
    )
    assert "camofox" not in listed


def test_order_run_places_camofox_before_agent(cfg: Config):
    steps = order_run(
        cfg, ["ezproxy", "camofox", "browser_agent", "scihub"]
    )
    names = [s.name for s in steps]
    assert names.index("camofox") < names.index("browser_agent")


def test_rank_pdf_links_prefers_pdf_href():
    ranked = _rank_pdf_links(
        [
            CamofoxLink(href="https://ex.test/about", text="About"),
            CamofoxLink(href="/article.pdf", text="PDF", ref="e1"),
            CamofoxLink(href="https://ex.test/full", text="Download PDF", ref="e2"),
        ],
        "https://ex.test/landing",
    )
    assert ranked[0].href.endswith(".pdf")
    assert ranked[0].ref == "e1"


def test_client_health_and_create_tab():
    pdf = b"%PDF-1.4 minimal"
    b64 = base64.b64encode(pdf).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/health"):
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/tabs") and request.method == "POST":
            return httpx.Response(200, json={"tabId": "t1", "url": "https://ex.test"})
        if path.endswith("/snapshot"):
            return httpx.Response(200, json={"snapshot": "[link e1] Download PDF"})
        if path.endswith("/links"):
            return httpx.Response(
                200,
                json={
                    "links": [
                        {
                            "href": "https://ex.test/paper.pdf",
                            "text": "Download PDF",
                            "ref": "e1",
                        }
                    ]
                },
            )
        if path.endswith("/click"):
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/fetch-current-resource"):
            return httpx.Response(415, json={"error": "not pdf"})
        if path.endswith("/downloads"):
            return httpx.Response(
                200,
                json={
                    "downloads": [
                        {
                            "filename": "paper.pdf",
                            "state": "completed",
                            "data": b64,
                        }
                    ]
                },
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"error": "missing"})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://camofox.test")
    client = CamofoxClient("http://camofox.test", client=http)
    assert client.health()
    assert client.create_tab(user_id="paperful", session_key="k", url="https://ex.test") == "t1"


def test_run_camofox_recover_hit(cfg: Config, monkeypatch):
    cfg.camofox_enabled = True
    cfg.camofox_base_url = "http://camofox.test"
    cfg.min_pdf_bytes = 10
    pdf = b"%PDF-1.4 " + b"x" * 40
    b64 = base64.b64encode(pdf).decode()
    state = {"clicked": False}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/health"):
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/tabs") and request.method == "POST":
            return httpx.Response(200, json={"tabId": "t1"})
        if path.endswith("/fetch-current-resource"):
            return httpx.Response(415)
        if path.endswith("/snapshot"):
            return httpx.Response(200, json={"snapshot": "Article body"})
        if path.endswith("/links"):
            return httpx.Response(
                200,
                json={
                    "links": [
                        {
                            "href": "https://ex.test/a.pdf",
                            "text": "PDF",
                            "ref": "e1",
                        }
                    ]
                },
            )
        if path.endswith("/click"):
            state["clicked"] = True
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/downloads"):
            if not state["clicked"]:
                return httpx.Response(200, json={"downloads": []})
            return httpx.Response(
                200,
                json={
                    "downloads": [
                        {"filename": "a.pdf", "data": b64, "state": "completed"}
                    ]
                },
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    class FakeClient(CamofoxClient):
        def __init__(self, base_url: str, **kwargs: object) -> None:
            http = httpx.Client(transport=transport)
            super().__init__(base_url, client=http, timeout=5.0)

    monkeypatch.setattr("paperful.camofox_recover.CamofoxClient", FakeClient)
    monkeypatch.setattr("paperful.camofox_recover._DOWNLOAD_PAUSE_S", 0)
    monkeypatch.setattr("paperful.camofox_recover._DOWNLOAD_POLLS", 2)

    result = run_camofox_recover(cfg, make_item())
    assert result.pdf_bytes == pdf
    assert result.captcha is False


def test_run_camofox_recover_captcha(cfg: Config, monkeypatch):
    cfg.camofox_base_url = "http://camofox.test"
    cfg.min_pdf_bytes = 10

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/health"):
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/tabs") and request.method == "POST":
            return httpx.Response(200, json={"tabId": "t1"})
        if path.endswith("/fetch-current-resource"):
            return httpx.Response(415)
        if path.endswith("/downloads"):
            return httpx.Response(200, json={"downloads": []})
        if path.endswith("/snapshot"):
            return httpx.Response(
                200,
                json={"snapshot": "Checking your browser before accessing cloudflare"},
            )
        if path.endswith("/links"):
            return httpx.Response(200, json={"links": []})
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    class FakeClient(CamofoxClient):
        def __init__(self, base_url: str, **kwargs: object) -> None:
            http = httpx.Client(transport=transport)
            super().__init__(base_url, client=http, timeout=5.0)

    monkeypatch.setattr("paperful.camofox_recover.CamofoxClient", FakeClient)
    monkeypatch.setattr("paperful.camofox_recover._DOWNLOAD_PAUSE_S", 0)
    monkeypatch.setattr("paperful.camofox_recover._DOWNLOAD_POLLS", 1)

    result = run_camofox_recover(cfg, make_item())
    assert result.pdf_bytes is None
    assert result.captcha is True


def test_source_find_skipped_when_disabled(cfg: Config):
    ctx = Context(config=cfg, client=MagicMock())
    cand = camofox_src.find(make_item(), ctx)
    assert cand.outcome is Outcome.SKIPPED


def test_source_find_skipped_when_server_unreachable(cfg: Config, monkeypatch):
    cfg.camofox_enabled = True
    cfg.camofox_base_url = "http://camofox.test"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(503, json={"error": "down"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    class FakeClient(CamofoxClient):
        def __init__(self, base_url: str, **kwargs: object) -> None:
            http = httpx.Client(transport=transport)
            super().__init__(base_url, client=http, timeout=5.0)

    monkeypatch.setattr("paperful.camofox_recover.CamofoxClient", FakeClient)
    ctx = Context(config=cfg, client=MagicMock())
    cand = camofox_src.find(make_item(), ctx)
    assert cand.outcome is Outcome.SKIPPED
    assert "unreachable" in cand.note


def test_pipeline_camofox_skipped_without_browser_lane_failure(cfg, monkeypatch):
    import io

    from rich.console import Console

    from paperful.pipeline import Pipeline
    from paperful.sources.base import Candidate, Outcome
    from paperful.store import Manifest
    from tests.conftest import make_item
    from tests.test_pipeline import StubSource

    cfg.camofox_enabled = True
    scholar = StubSource("scholar")
    fox = StubSource(
        "camofox",
        {"N": Candidate(url="", source="camofox", content=PDF_BYTES)},
    )
    monkeypatch.setattr(
        "paperful.pipeline.REGISTRY",
        {"unpaywall": StubSource("unpaywall"), "scholar": scholar, "camofox": fox},
    )
    monkeypatch.setattr("paperful.pipeline.prepare_identifiers", lambda *a, **k: [])
    pipe = Pipeline(
        cfg,
        Manifest(cfg.manifest_path),
        Console(file=io.StringIO()),
        sources=["unpaywall", "scholar", "camofox"],
        try_all=False,
        use_browser=False,
    )
    item = make_item(key="N", doi=None, title="x", url="https://x.test/p")
    pipe.run([item])
    rec = pipe.manifest.get("N")
    assert scholar.calls == []
    assert fox.calls == []
    assert rec is not None
    assert "camofox:skipped(no browser-lane failure)" in rec.attempts


def test_pipeline_camofox_runs_after_vault_miss(cfg, monkeypatch):
    import io

    from rich.console import Console

    from paperful.pipeline import Pipeline
    from paperful.sources.base import Candidate, Outcome
    from paperful.store import STATUS_OK, Manifest
    from tests.conftest import make_item
    from tests.test_pipeline import StubSource

    cfg.camofox_enabled = True
    scholar = StubSource("scholar", default=Outcome.NOT_FOUND)
    fox = StubSource(
        "camofox",
        {
            "A": Candidate(
                url="https://ex.test/a.pdf", source="camofox", content=PDF_BYTES
            )
        },
    )
    monkeypatch.setattr(
        "paperful.pipeline.REGISTRY",
        {"unpaywall": StubSource("unpaywall"), "scholar": scholar, "camofox": fox},
    )
    monkeypatch.setattr("paperful.pipeline.prepare_identifiers", lambda *a, **k: [])
    pipe = Pipeline(
        cfg,
        Manifest(cfg.manifest_path),
        Console(file=io.StringIO()),
        sources=["unpaywall", "scholar", "camofox"],
        try_all=True,
        use_browser=False,
    )
    stats = pipe.run([make_item(key="A")])
    rec = pipe.manifest.get("A")
    assert scholar.calls == ["A"] and fox.calls == ["A"]
    assert stats.ok == 1 and rec is not None and rec.source == "camofox"
    assert rec.status == STATUS_OK


def test_config_parses_camofox_table(tmp_path):
    from paperful.config import load_config

    path = tmp_path / "config.toml"
    path.write_text(
        """
[camofox]
enabled = true
during_run = false
base_url = "http://127.0.0.1:9999"
max_wall_s = 45
""",
        encoding="utf-8",
    )
    loaded = load_config(path)
    assert loaded.camofox_enabled is True
    assert loaded.camofox_during_run is False
    assert loaded.camofox_base_url == "http://127.0.0.1:9999"
    assert loaded.camofox_max_wall_s == 45.0
