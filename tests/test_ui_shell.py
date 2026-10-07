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
    assert client.get("/index").status_code == 200
    assert client.get("/briefs").status_code == 200
    assert "/briefs" in res.text


def test_dockerfile_includes_serve_extra():
    from pathlib import Path

    text = Path("Dockerfile").read_text(encoding="utf-8")
    assert "--extra serve" in text
