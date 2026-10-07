"""Workbench shell pages (wave 1)."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_root_redirect_and_pages_render(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    doctor = lambda _cfg, probe=False: [
        {"name": "Zotero", "status": "red", "code": "zotero_down", "detail": "down"}
    ]
    monkeypatch.setattr(ops, "doctor_payload", doctor)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", doctor)
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": False, "error": "Zotero is not reachable", "collections": []},
    )
    client = TestClient(create_app(cfg))
    assert client.get("/", follow_redirects=False).status_code == 302
    assert client.get("/", follow_redirects=False).headers["location"] == "/wanted"
    for path in ("/wanted", "/discover", "/library", "/activity", "/system"):
        res = client.get(path)
        assert res.status_code == 200
        assert "Paperful" in res.text
    wanted = client.get("/wanted")
    assert wanted.status_code == 200
    nav = wanted.text
    assert nav.index('href="/wanted"') < nav.index('href="/discover"')
    assert "Zotero offline" in wanted.text
    assert "Start Zotero" in wanted.text or "Pick a collection" in wanted.text
    assert 'formaction="/wanted/attach"' in wanted.text
    assert "/repair" not in wanted.text
    client.cookies.set("pf_advanced", "1")
    res = client.get("/wanted")
    assert "/repair" in res.text
    assert "/v1/ask" not in res.text
    assert client.get("/repair").status_code == 200
    assert client.get("/mirror").status_code == 200
    assert client.get("/index").status_code == 200
    assert client.get("/briefs").status_code == 200
    assert "/briefs" in res.text
    wanted_adv = client.get("/wanted")
    assert "Recover" in wanted_adv.text
    assert "Handoff" in wanted_adv.text
    discover_adv = client.get("/discover")
    assert "Refs gap" in discover_adv.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_html_pages_do_not_block_on_doctor(tmp_path, monkeypatch):
    """Health chip must not run full doctor on ordinary HTML routes (GUI hang)."""
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    calls = {"n": 0}

    def counting_doctor(_cfg, probe=False):
        calls["n"] += 1
        return [
            {"name": "Zotero", "status": "red", "code": "zotero_down", "detail": "down"}
        ]

    # mount_ui binds doctor_payload at import time — patch the UI module name.
    monkeypatch.setattr("paperful.ui.app.doctor_payload", counting_doctor)
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )
    client = TestClient(create_app(cfg))

    wanted = client.get("/wanted")
    assert wanted.status_code == 200
    assert "health-amber" in wanted.text
    assert calls["n"] == 0

    settings = client.get("/settings")
    assert settings.status_code == 200
    assert calls["n"] == 0

    system = client.get("/system")
    assert system.status_code == 200
    assert calls["n"] == 1
    assert "health-red" in system.text

    wanted2 = client.get("/wanted")
    assert wanted2.status_code == 200
    assert "health-red" in wanted2.text
    assert calls["n"] == 1


def test_dockerfile_includes_serve_extra():
    from pathlib import Path

    text = Path("Dockerfile").read_text(encoding="utf-8")
    assert "--extra serve" in text
