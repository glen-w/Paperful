"""Discover Web search routes (offline FakeSearXNG; enqueue is stubbed)."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.search.run import run_search
from paperful.serve import create_app, fastapi_available
from paperful.ui import commands

pytestmark = pytest.mark.skipif(
    not fastapi_available(), reason="paperful[serve] extra missing"
)

PDF = "https://portals.iucn.org/library/sites/library/files/documents/2018-gjerde.pdf"
LANDING = "https://www.iucn.org/resources/publication/gjerde-high-seas-2018"


class FakeSearXNG:
    def __call__(self, query: str) -> dict:
        return {
            "results": [
                {"url": PDF, "title": "Gjerde IUCN 2018"},
                {"url": LANDING, "title": "IUCN landing"},
                {"url": "https://scholar.google.com/scholar?q=x", "title": "Scholar"},
            ]
        }


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.searxng_base_url = "http://searx.test"
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    queued: list[tuple[str, object]] = []

    def fake_enqueue(_cfg, verb, fn, *, args=None):
        queued.append((verb, fn))
        return "cmd1"

    monkeypatch.setattr(commands, "enqueue", fake_enqueue)

    class Env:
        pass

    e = Env()
    e.cfg, e.queued = cfg, queued
    e.client = TestClient(create_app(cfg), raise_server_exceptions=False)
    return e


def test_search_meta_empty(env):
    res = env.client.get("/discover/search/meta")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["searxng"] is True
    assert body["runs"] == []


def test_search_get_and_web_tab(env):
    run_search(
        env.cfg,
        ["Gjerde"],
        hosts="iucn.org",
        run_id="gui-web",
        probe=False,
        getter=FakeSearXNG(),
    )
    meta = env.client.get("/discover/search/meta").json()
    assert meta["runs"][0]["run_id"] == "gui-web"
    body = env.client.get("/discover/search", params={"run_id": "gui-web"}).json()
    assert body["ok"] is True
    assert body["candidates"]
    page = env.client.get("/discover", params={"tab": "web"})
    assert page.status_code == 200
    assert b'id="discoverWebSection"' in page.content
    assert b"/discover/search/run" in page.content
    assert b"Preview apply" in page.content


def test_search_run_enqueues_when_searxng_set(env):
    res = env.client.post(
        "/discover/search/run",
        data={"query": "Gjerde IUCN", "hosts": "iucn.org", "filetype": "pdf", "max": "10"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert env.queued[0][0] == "search"


def test_search_get_requires_run_id(env):
    res = env.client.get("/discover/search")
    assert res.status_code == 400
    assert res.json()["ok"] is False


def test_search_unknown_run_is_404(env):
    res = env.client.get("/discover/search", params={"run_id": "missing-run"})
    assert res.status_code == 404


def test_search_run_blank_query_does_not_enqueue(env):
    res = env.client.post(
        "/discover/search/run",
        data={"query": ""},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert env.queued == []


def test_search_run_unset_searxng_does_not_enqueue(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.searxng_base_url = ""
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    queued: list = []
    monkeypatch.setattr(
        commands, "enqueue", lambda *_a, **_k: queued.append("nope") or "cmd1"
    )
    client = TestClient(create_app(cfg), raise_server_exceptions=False)
    res = client.post(
        "/discover/search/run",
        data={"query": "Gjerde"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "SearXNG" in res.headers.get("location", "")
    assert queued == []
    page = client.get("/discover", params={"tab": "web"})
    assert page.status_code == 200
    assert b"SearXNG is unset" in page.content


def test_web_tab_hidden_when_pref_off(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.ui_web_search = "off"
    cfg.searxng_base_url = "http://searx.test"
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    queued: list = []
    monkeypatch.setattr(commands, "enqueue", lambda *_a, **_k: queued.append("x") or "cmd1")
    client = TestClient(create_app(cfg), raise_server_exceptions=False)
    res = client.get("/discover", params={"tab": "web"})
    assert res.status_code == 200
    assert b'id="discoverWebSection"' not in res.content
    meta = client.get("/discover/search/meta").json()
    assert meta["enabled"] is False
    assert meta["runs"] == []
    missing = client.get("/discover/search", params={"run_id": "x"})
    assert missing.status_code == 404
    post = client.post(
        "/discover/search/run",
        data={"query": "Gjerde"},
        follow_redirects=False,
    )
    assert post.status_code == 303
    assert queued == []
