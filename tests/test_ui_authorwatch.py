"""Authorwatch Discover routes."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_aw_save_creates_list(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    client = TestClient(create_app(cfg))
    res = client.post(
        "/discover/aw/save",
        data={"name": "lab-list"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert (cfg.state_dir / "authorwatch" / "lab-list" / "watch.json").is_file()


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_index_report_route_404(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_advanced", "1")
    assert client.get("/index/report/no-such-slug").status_code == 404
