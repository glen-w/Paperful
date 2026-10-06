"""Settings and Advanced cookie (wave 6)."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_advanced_cookie_reveals_nav_without_llm(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    assert cfg.llm_enabled is False
    monkeypatch.setattr(
        ops,
        "doctor_payload",
        lambda _cfg, probe=False: [{"name": "x", "status": "green", "code": "", "detail": ""}],
    )
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )
    client = TestClient(create_app(cfg))
    res = client.post("/prefs/advanced", data={"advanced": "1"}, follow_redirects=False)
    assert res.status_code == 303
    client.cookies.update(res.cookies)
    res2 = client.get("/wanted")
    assert "/settings" in res2.text
    assert cfg.llm_enabled is False


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_settings_saves_preset_cookie(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.config_path = tmp_path / "config.toml"
    cfg.config_path.write_text('email = "a@b.c"\n', encoding="utf-8")
    monkeypatch.setattr(
        ops,
        "doctor_payload",
        lambda _cfg, probe=False: [{"name": "x", "status": "green", "code": "", "detail": ""}],
    )
    client = TestClient(create_app(cfg))
    res = client.post(
        "/settings",
        data={
            "email": "a@b.c",
            "preset": "eoi",
            "attach_verified": "1",
            "out_dir": str(tmp_path / "out"),
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "pf_preset=eoi" in (res.headers.get("set-cookie") or "")
    assert cfg.llm_enabled is False
