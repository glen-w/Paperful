"""1.7 platform wave: UI token guard, opt-in update check, conformance helpers."""

from __future__ import annotations

import pytest

from paperful.config import Config, load_config
from paperful.serve import create_app, fastapi_available
from paperful.update_check import (
    cached_latest,
    check_for_update,
    newer_version,
)


# ---- UI token guard -------------------------------------------------------


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_ui_token_required_when_configured(tmp_path):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    client = TestClient(create_app(cfg, ui_token="s3cret"))
    assert client.get("/health").status_code == 200  # exempt
    assert client.get("/v1/runs/last").status_code == 401
    assert (
        client.get(
            "/v1/runs/last", headers={"Authorization": "Bearer s3cret"}
        ).status_code
        == 200
    )
    assert (
        client.get("/v1/runs/last", headers={"X-Paperful-Token": "s3cret"}).status_code
        == 200
    )
    assert (
        client.get(
            "/v1/runs/last", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_ui_no_token_by_default(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.delenv("PAPERFUL_UI_TOKEN", raising=False)
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    client = TestClient(create_app(cfg))
    assert client.get("/v1/runs/last").status_code == 200


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_ui_token_from_env(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PAPERFUL_UI_TOKEN", "env-token")
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    client = TestClient(create_app(cfg))
    assert client.get("/v1/runs/last").status_code == 401
    assert (
        client.get(
            "/v1/runs/last", headers={"Authorization": "Bearer env-token"}
        ).status_code
        == 200
    )


# ---- benchmark harness ----------------------------------------------------


def test_bench_synthetic_builds_scannable_mirror(tmp_path):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "bench_synthetic.py"
    spec = importlib.util.spec_from_file_location("bench_synthetic", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = module.build_mirror(tmp_path, 25)
    from paperful.mirror import MirrorIndex

    assert len(MirrorIndex.scan(out).keys()) == 25


# ---- update check ---------------------------------------------------------


def test_newer_version_compare():
    assert newer_version("1.6.5", "1.7.0")
    assert newer_version("1.6.5", "1.6.10")
    assert not newer_version("1.7.0", "1.7.0")
    assert not newer_version("1.7.0", "1.6.9")
    assert not newer_version("1.7.0", "junk")
    assert not newer_version("junk", "1.7.0")


def test_check_for_update_uses_cache(tmp_path):
    calls: list[int] = []

    def fetcher() -> str:
        calls.append(1)
        return "9.9.9"

    assert check_for_update("1.6.5", tmp_path, fetcher=fetcher, now=1000.0) == "9.9.9"
    # Second call within the TTL must not fetch again.
    assert check_for_update("1.6.5", tmp_path, fetcher=fetcher, now=2000.0) == "9.9.9"
    assert len(calls) == 1
    assert cached_latest(tmp_path, now=2000.0) == "9.9.9"
    # After the TTL the cache is stale.
    assert cached_latest(tmp_path, now=1000.0 + 25 * 3600) == ""


def test_check_for_update_silent_when_current_or_offline(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    assert check_for_update("9.9.9", a, fetcher=lambda: "9.9.9", now=1.0) == ""
    assert check_for_update("1.0.0", b, fetcher=lambda: "", now=1.0) == ""


def test_updates_config_section(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        'email = "t@example.org"\n[updates]\ncheck = true\n', encoding="utf-8"
    )
    cfg = load_config(cfg_path)
    assert cfg.update_check is True
    assert Config().update_check is False


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_ui_token_not_accepted_via_query_or_empty_bearer(tmp_path):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    client = TestClient(create_app(cfg, ui_token="s3cret"))
    # A token in the query string must never authenticate (it would leak
    # into logs/history); only headers count.
    assert client.get("/v1/runs/last?token=s3cret").status_code == 401
    assert client.get("/v1/runs/last?ui_token=s3cret").status_code == 401
    # Empty / scheme-only bearer values are rejected, not treated as open.
    assert (
        client.get("/v1/runs/last", headers={"Authorization": "Bearer "}).status_code
        == 401
    )
    assert (
        client.get("/v1/runs/last", headers={"Authorization": "Bearer"}).status_code
        == 401
    )
    assert (
        client.get("/v1/runs/last", headers={"X-Paperful-Token": ""}).status_code == 401
    )
    # Scheme matching is case-insensitive, per RFC 7235.
    assert (
        client.get(
            "/v1/runs/last", headers={"Authorization": "bearer s3cret"}
        ).status_code
        == 200
    )


def test_check_for_update_survives_corrupt_cache(tmp_path):
    (tmp_path / "update-check.json").write_text("{torn", encoding="utf-8")
    assert cached_latest(tmp_path, now=1000.0) == ""
    assert (
        check_for_update("1.0.0", tmp_path, fetcher=lambda: "2.0.0", now=1000.0)
        == "2.0.0"
    )
    # The corrupt file is replaced atomically with a valid cache.
    assert cached_latest(tmp_path, now=1000.0) == "2.0.0"


def test_playwright_is_an_extra_not_core():
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib
    from pathlib import Path

    data = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    core = " ".join(data["project"]["dependencies"])
    assert "playwright" not in core.lower()
    extras = data["project"]["optional-dependencies"]
    assert any("playwright" in dep for dep in extras["browser"])
    assert extras["htmlpdf"] == extras["browser"]


def test_doctor_playwright_check_names_the_extra(monkeypatch):
    from paperful import doctor, session as sess

    monkeypatch.setattr(sess, "playwright_available", lambda: False)
    check = doctor._playwright_check()
    assert check.status == "amber"
    assert "paperful[browser]" in check.detail


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_ui_token_unequal_length_is_401_not_500(tmp_path):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    client = TestClient(create_app(cfg, ui_token="a" * 32))
    # compare_digest must not raise when the supplied secret is shorter.
    assert (
        client.get("/v1/runs/last", headers={"Authorization": "Bearer x"}).status_code
        == 401
    )
    assert (
        client.get("/v1/runs/last", headers={"X-Paperful-Token": "x" * 8}).status_code
        == 401
    )


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_ui_health_stays_open_with_wrong_token(tmp_path):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    client = TestClient(create_app(cfg, ui_token="s3cret"))
    assert client.get("/health").status_code == 200
    assert (
        client.get("/health", headers={"Authorization": "Bearer wrong"}).status_code
        == 200
    )


def test_config_check_knows_updates_section(tmp_path):
    from paperful.config_check import check_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[updates]\ncheck = true\n", encoding="utf-8")
    assert check_config(cfg_path) == []
