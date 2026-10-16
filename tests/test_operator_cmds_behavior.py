"""Direct tests for wave-6 operator ``*_cmd`` modules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from rich.console import Console

from paperful import cache_cmd, collections_cmd, doctor_cmd, mirrors_cmd, pack_cmd, session_cmd
from paperful.doctor import Check
from tests.conftest import patch_cli_runtime


def _console() -> Console:
    return Console(width=200, highlight=False, record=True)


@pytest.fixture
def cfg_paths(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
        'scihub_mirrors = ["mirror.test"]\n',
        encoding="utf-8",
    )
    (tmp_path / "out").mkdir()
    (tmp_path / "state").mkdir()
    return p


def test_run_mirrors_uses_ping(cfg_paths, monkeypatch):
    monkeypatch.setattr(
        "paperful.mirrors_cmd.ping_mirrors",
        lambda ctx: [("mirror.test", "HTTP 200"), ("bad.test", "timeout")],
    )
    monkeypatch.setattr(
        "paperful.mirrors_cmd.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    c = _console()
    mirrors_cmd.run_mirrors(c, config=cfg_paths)
    text = c.export_text()
    assert "HTTP 200" in text
    assert "timeout" in text


def test_run_cache_clean_json(cfg_paths, monkeypatch):
    monkeypatch.setattr(
        "paperful.sync.clean_pdf_cache",
        lambda cfg, apply: {
            "apply": apply,
            "removed": 0,
            "removable": 2,
            "kept": 1,
            "cache_dir": str(cfg_paths.parent / "state" / "pdf-cache"),
        },
    )
    c = _console()
    cache_cmd.run_cache_clean(c, apply=False, config=cfg_paths, fmt="json")
    # JSON mode writes to stdout via _emit_agent; human path not used


def test_run_pack_show_no_pack(cfg_paths, monkeypatch):
    monkeypatch.setattr("paperful.pack.latest_pack", lambda cfg: None)
    with pytest.raises(typer.Exit) as exc:
        pack_cmd.run_pack_show(_console(), as_json=False, config=cfg_paths)
    assert exc.value.exit_code == 0


def test_run_pack_show_json(cfg_paths, monkeypatch):
    pack = {"id": "p1", "status": "open", "label": "demo", "steps": []}
    monkeypatch.setattr("paperful.pack.latest_pack", lambda cfg: pack)
    monkeypatch.setattr(
        "paperful.pack.show_payload",
        lambda cfg, p: {"steps": [{"command": "run", "duration_s": 1.5, "summary": {}}]},
    )
    c = _console()
    pack_cmd.run_pack_show(c, as_json=True, config=cfg_paths)
    body = json.loads(c.export_text())
    assert body["steps"][0]["command"] == "run"


def test_run_pack_open_error(cfg_paths, monkeypatch):
    from paperful.pack import PackError

    monkeypatch.setattr(
        "paperful.pack.open_pack",
        lambda cfg, label=None: (_ for _ in ()).throw(PackError("nope")),
    )
    with pytest.raises(typer.Exit) as exc:
        pack_cmd.run_pack_open(_console(), label=None, config=cfg_paths)
    assert exc.value.exit_code == 1


def test_run_doctor_json_red_exits(cfg_paths, monkeypatch):
    checks = [Check("email", "red", "missing", code="email_empty")]

    def fake_run_checks(cfg, zl, probe=False):
        return checks

    monkeypatch.setattr("paperful.doctor_cmd.run_checks", fake_run_checks)
    patch_cli_runtime(monkeypatch, ZoteroLocal=lambda: object())
    with pytest.raises(typer.Exit) as exc:
        doctor_cmd.run_doctor(
            _console(),
            config=cfg_paths,
            guide=False,
            probe=False,
            as_json=True,
        )
    assert exc.value.exit_code == 2


def test_run_doctor_prints_remediations_non_tty(cfg_paths, monkeypatch):
    checks = [
        Check("email", "amber", "empty", code=""),
        Check("Zotero", "green", "ok", code=""),
    ]

    monkeypatch.setattr("paperful.doctor_cmd.run_checks", lambda *a, **k: checks)
    monkeypatch.setattr("paperful.doctor_cmd._in_docker", lambda: True)
    monkeypatch.setattr("paperful.cli_runtime._stdin_is_tty", lambda: False)
    patch_cli_runtime(monkeypatch, ZoteroLocal=lambda: object(), _cfg=lambda p: __import__(
        "paperful.config", fromlist=["load_config"]
    ).load_config(cfg_paths))
    c = _console()
    doctor_cmd.run_doctor(
        c,
        config=cfg_paths,
        guide=False,
        probe=False,
        as_json=False,
    )
    assert "doctor" in c.export_text().lower()


def test_run_collections_show_table(cfg_paths, monkeypatch):
    class Col:
        def __init__(self, key, path, name):
            self.key = key
            self.path = path
            self.name = name

    class Backend:
        def collections(self):
            return {"K": Col("K", "Ocean", "Ocean")}

        def collection_counts(self):
            return {"K": (3, 1)}

    patch_cli_runtime(
        monkeypatch,
        _cfg=lambda p: __import__("paperful.config", fromlist=["load_config"]).load_config(
            cfg_paths
        ),
        _require_manager=lambda cfg: None,
        _connect=lambda cfg: Backend(),
        _spinner=lambda msg: __import__("contextlib").contextmanager(lambda: (yield))(),
    )
    c = _console()
    collections_cmd.run_collections_show(c, config=cfg_paths)
    assert "Ocean" in c.export_text()


def test_session_login_unknown_slot(cfg_paths):
    with pytest.raises(typer.Exit) as exc:
        session_cmd.run_session_login(
            _console(), slot="nope", config=cfg_paths, engine="auto"
        )
    assert exc.value.exit_code == 1


def test_session_login_bad_engine(cfg_paths):
    with pytest.raises(typer.Exit) as exc:
        session_cmd.run_session_login(
            _console(), slot="scholar", config=cfg_paths, engine="firefox"
        )
    assert exc.value.exit_code == 1


def test_session_status_quiet(cfg_paths, monkeypatch):
    import paperful.session as sess

    monkeypatch.setattr(sess, "sessions_dir", lambda cfg: cfg_paths.parent / "sessions")
    monkeypatch.setattr(sess, "chromium_dir", lambda cfg: cfg_paths.parent / "chromium")
    monkeypatch.setattr(sess, "profile_ready", lambda cfg: False)
    monkeypatch.setattr(sess, "load_meta", lambda cfg: {})
    monkeypatch.setattr(sess, "vault_cookies_path", lambda cfg: cfg_paths.parent / "vault.txt")
    monkeypatch.setattr(sess, "storage_state_path", lambda cfg: cfg_paths.parent / "state.json")
    c = _console()
    session_cmd.run_session_status(c, config=cfg_paths, probe=False)
    assert "Vault:" in c.export_text()


def test_ezproxy_empty_base_exits(cfg_paths, monkeypatch):
    cfg = __import__("paperful.config", fromlist=["load_config"]).load_config(cfg_paths)
    cfg.ezproxy_base = ""
    patch_cli_runtime(monkeypatch, _cfg=lambda p: cfg)
    with pytest.raises(typer.Exit) as exc:
        session_cmd.run_ezproxy(_console(), config=cfg_paths, open_browser=False)
    assert exc.value.exit_code == 1
