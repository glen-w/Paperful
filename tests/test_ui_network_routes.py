"""Discover People co-author network routes (offline FakeOA)."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.network.run import run_orcid
from paperful.serve import create_app, fastapi_available
from paperful.ui import commands
from tests.test_network import ORCID, FakeOA, FIXTURES

pytestmark = pytest.mark.skipif(
    not fastapi_available(), reason="paperful[serve] extra missing"
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    queued: list[tuple[str, object]] = []

    def fake_enqueue(_cfg, verb, fn, *, args=None):
        queued.append((verb, fn))
        return "cmd1"

    monkeypatch.setattr(commands, "enqueue", fake_enqueue)
    monkeypatch.setattr(
        "paperful.network.run.openalex_client", lambda cfg, client=None: FakeOA()
    )

    class Env:
        pass

    e = Env()
    e.cfg, e.queued = cfg, queued
    e.client = TestClient(create_app(cfg), raise_server_exceptions=False)
    return e


def test_network_meta_empty(env):
    res = env.client.get("/discover/network/meta")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["runs"] == []


def test_network_get_and_phase(env):
    run_orcid(
        env.cfg,
        ORCID,
        phases=str(FIXTURES / "phases.toml"),
        client=FakeOA(),
        run_id="gui-gjerde",
        max_works=10,
        max_alters=10,
    )
    meta = env.client.get("/discover/network/meta").json()
    assert meta["runs"][0]["run_id"] == "gui-gjerde"
    body = env.client.get("/discover/network", params={"run_id": "gui-gjerde"}).json()
    assert body["ok"] is True
    assert body["graph"]["ego"]["orcid"] == ORCID
    phased = env.client.get(
        "/discover/network", params={"run_id": "gui-gjerde", "phase": "early"}
    ).json()
    assert phased["ok"] is True
    years = {y for e in phased["graph"]["edges"] for y in e.get("years") or []}
    assert years <= {2008, 2009, 2010}


def test_network_run_enqueues(env):
    res = env.client.post(
        "/discover/network/run",
        data={"orcid": ORCID, "phases": str(FIXTURES / "phases.toml")},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert env.queued[0][0] == "network_orcid"


def test_people_page_includes_network_panel(env):
    res = env.client.get("/discover", params={"tab": "people"})
    assert res.status_code == 200
    assert b'id="coauthorNetworkApp"' in res.content
    assert b"/discover/network/run" in res.content
    assert b"coauthor_network.js" in res.content


def test_network_get_requires_run_id(env):
    res = env.client.get("/discover/network")
    assert res.status_code == 400
    assert res.json()["ok"] is False


def test_network_unknown_run_is_404(env):
    res = env.client.get("/discover/network", params={"run_id": "missing-run"})
    assert res.status_code == 404


def test_network_unknown_phase_is_404(env):
    run_orcid(
        env.cfg,
        ORCID,
        phases=str(FIXTURES / "phases.toml"),
        client=FakeOA(),
        run_id="gui-gjerde",
        max_works=10,
        max_alters=10,
    )
    res = env.client.get(
        "/discover/network", params={"run_id": "gui-gjerde", "phase": "not-a-phase"}
    )
    assert res.status_code == 404


def test_network_run_blank_orcid_redirects_with_error(env):
    res = env.client.post(
        "/discover/network/run",
        data={"orcid": ""},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "ORCID" in res.headers.get("location", "")
    assert env.queued == []


def test_people_page_hides_panel_when_pref_off(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from paperful.serve import create_app

    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.ui_coauthor_network = "off"
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    client = TestClient(create_app(cfg), raise_server_exceptions=False)
    res = client.get("/discover", params={"tab": "people"})
    assert res.status_code == 200
    assert b'id="coauthorNetworkApp"' not in res.content
    meta = client.get("/discover/network/meta").json()
    assert meta["enabled"] is False
    assert meta["runs"] == []
