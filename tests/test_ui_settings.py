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
        lambda _cfg, probe=False: [
            {"name": "x", "status": "green", "code": "", "detail": ""}
        ],
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
        lambda _cfg, probe=False: [
            {"name": "x", "status": "green", "code": "", "detail": ""}
        ],
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
        lambda _cfg, probe=False: [
            {"name": "x", "status": "green", "code": "", "detail": ""}
        ],
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
    assert "[ui]" in text
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


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_settings_quotes_values_and_scopes_root_keys(tmp_path, monkeypatch):
    """A quote in out_dir must not corrupt config.toml; root keys stay in the root table."""
    import sys

    from fastapi.testclient import TestClient

    tomllib = __import__("tomllib" if sys.version_info >= (3, 11) else "tomli")
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.config_path = tmp_path / "config.toml"
    cfg.config_path.write_text(
        '# header comment\n[twenty]\nemail = "crm@example.org"\n\n[ui]\nweb_search = "on"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    client = TestClient(create_app(cfg))
    weird = tmp_path / 'my "papers"'
    res = client.post(
        "/settings",
        data={"email": "me@example.org", "preset": "oa", "out_dir": str(weird)},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/settings?saved=1"
    data = tomllib.loads(cfg.config_path.read_text(encoding="utf-8"))
    assert data["email"] == "me@example.org"
    assert data["out_dir"] == str(weird)
    assert data["twenty"]["email"] == "crm@example.org", (
        "root key must not hit [twenty]"
    )
    assert data["ui"]["web_search"] == "off"
    assert "# header comment" in cfg.config_path.read_text(encoding="utf-8")


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_settings_rejects_bad_values_without_writing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.config_path = tmp_path / "config.toml"
    original = 'email = "a@b.c"\n'
    cfg.config_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    client = TestClient(create_app(cfg))
    res = client.post(
        "/settings",
        data={"email": "not an email", "preset": "oa"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "error=" in res.headers["location"]
    assert cfg.config_path.read_text(encoding="utf-8") == original
    page = client.get(res.headers["location"])
    assert "Nothing was written" in page.text
    res = client.post(
        "/settings",
        data={
            "email": "a@b.c",
            "preset": "oa",
            "out_dir": str(tmp_path / "no" / "such" / "x"),
        },
        follow_redirects=False,
    )
    assert "error=" in res.headers["location"]
    assert cfg.config_path.read_text(encoding="utf-8") == original


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_cookies_are_port_scoped_and_strict(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    app = create_app(cfg)
    default = TestClient(app, base_url="http://127.0.0.1:8765")
    res = default.post(
        "/prefs/advanced", data={"advanced": "1"}, follow_redirects=False
    )
    cookie = res.headers["set-cookie"]
    assert cookie.startswith("pf_advanced=1")
    assert "samesite=strict" in cookie.lower()
    other = TestClient(app, base_url="http://127.0.0.1:8799")
    res = other.post("/prefs/advanced", data={"advanced": "1"}, follow_redirects=False)
    assert res.headers["set-cookie"].startswith("pf_advanced_8799=1")
    # A chip set on 8799 is not read on 8765 and vice versa.
    other.cookies.set("pf_collection_8799", "ocean")
    assert "ocean" in other.get("/wanted").text
    default.cookies.set("pf_collection_8799", "ocean")
    assert "no collection" in default.get("/wanted").text
