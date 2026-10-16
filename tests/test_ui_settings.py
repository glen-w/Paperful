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
            "out_dir": str(tmp_path / "out"),
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "pf_preset=eoi" in (res.headers.get("set-cookie") or "")
    assert cfg.llm_enabled is False


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_settings_saves_attach_mode(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.store import Manifest, Record, STATUS_ATTACHED

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    Manifest(cfg.manifest_path).write(
        Record(itemKey="K1", status=STATUS_ATTACHED, path="a.pdf")
    )
    cfg.config_path = tmp_path / "config.toml"
    cfg.config_path.write_text(
        'email = "a@b.c"\n\n[ui]\nlibrary_page_size = 50\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ops,
        "doctor_payload",
        lambda _cfg, probe=False: [{"name": "x", "status": "green", "code": "", "detail": ""}],
    )
    client = TestClient(create_app(cfg))
    page = client.get("/settings")
    assert "After Grab" in page.text
    assert "Manual" in page.text
    res = client.post(
        "/settings",
        data={"email": "a@b.c", "preset": "oa", "attach_mode": "auto"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert cfg.ui_attach_mode == "auto"
    text = cfg.config_path.read_text(encoding="utf-8")
    assert '[ui]' in text
    assert 'attach_mode = "auto"' in text
    assert text.index("[ui]") < text.index('attach_mode = "auto"')
    again = client.post(
        "/settings",
        data={"email": "a@b.c", "preset": "oa", "attach_mode": "manual"},
        follow_redirects=False,
    )
    assert again.status_code == 303
    assert cfg.ui_attach_mode == "manual"
    rewritten = cfg.config_path.read_text(encoding="utf-8")
    assert rewritten.count("attach_mode") == 1
    assert 'attach_mode = "manual"' in rewritten
    ignored = client.post(
        "/settings",
        data={"email": "a@b.c", "preset": "oa", "attach_mode": "sometimes"},
        follow_redirects=False,
    )
    assert ignored.status_code == 303
    assert cfg.ui_attach_mode == "manual"
