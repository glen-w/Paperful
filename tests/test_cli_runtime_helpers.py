"""Unit tests for ``cli_runtime`` helpers (no live Zotero)."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import pytest
import typer
from rich.console import Console

from paperful import cli_runtime
from paperful.config import Config


class _Colour(Enum):
    red = "red"


def test_typer_opt_unwraps_option_info():
    from typer.models import OptionInfo

    opt = OptionInfo(default="x")
    assert cli_runtime._typer_opt(opt) == "x"
    assert cli_runtime._typer_opt(opt, default="fallback") == "x"
    bare = OptionInfo(default=...)
    assert cli_runtime._typer_opt(bare, default=7) == 7
    assert cli_runtime._typer_opt("plain") == "plain"


def test_typer_enum_value():
    assert cli_runtime._typer_enum_value(_Colour.red) == "red"
    assert cli_runtime._typer_enum_value(None) is None
    assert cli_runtime._typer_enum_value("doi") == "doi"


def test_resolve_source_names_preset_and_list(cfg):
    names = cli_runtime._resolve_source_names(None, "oa")
    assert names is not None and "ezproxy" not in names
    listed = cli_runtime._resolve_source_names("direct,unpaywall", None)
    assert listed == ["direct", "unpaywall"]
    token = cli_runtime._resolve_source_names("oa", None)
    assert token is not None and "unpaywall" in token


def test_resolve_source_names_unknown_preset_exits():
    with pytest.raises(typer.Exit) as exc:
        cli_runtime._resolve_source_names(None, "not-a-preset")
    assert exc.value.exit_code == 1


def test_source_list_appends_scihub(cfg):
    cfg.sources = ["direct"]
    out = cli_runtime._source_list(cfg, None, enable_scihub=True)
    assert out[-1] == "scihub"
    out2 = cli_runtime._source_list(cfg, "direct", enable_scihub=False)
    assert out2 == ["direct"]


def test_env_code_classifies_messages():
    assert cli_runtime._env_code("no write support") == "zotero_no_write"
    assert cli_runtime._env_code("Allow other applications") == "zotero_api_off"
    assert cli_runtime._env_code("HTTP 400 bad host") == "zotero_bad_host"
    assert cli_runtime._env_code("nodename nor servname") == "zotero_host_unresolved"
    assert cli_runtime._env_code("connection refused") == "zotero_down"
    assert cli_runtime._env_code("something else") == ""


def test_zotero_next_steps_include_doctor_hint():
    steps = cli_runtime._zotero_next_steps("zotero_down", in_doctor=False)
    assert any("doctor" in s.lower() for s in steps)
    in_doc = cli_runtime._zotero_next_steps("zotero_down", in_doctor=True)
    assert not any("doctor for a full" in s for s in in_doc)


def test_print_exit_ladder_mendeley_and_endnote(cfg, monkeypatch):
    c = Console(width=120, record=True)
    monkeypatch.setattr(cli_runtime, "console", c)
    mcfg = Config(
        out_dir=cfg.out_dir,
        state_dir=cfg.state_dir,
        manager="mendeley",
    )
    cli_runtime._print_exit_ladder(mcfg)
    text = c.export_text()
    assert "mendeley" in text.lower()
    ecfg = Config(out_dir=cfg.out_dir, state_dir=cfg.state_dir, manager="endnote")
    c2 = Console(width=120, record=True)
    monkeypatch.setattr(cli_runtime, "console", c2)
    cli_runtime._print_exit_ladder(ecfg)
    assert "Library.enl" in c2.export_text()


def test_require_manager_rejects_unknown(cfg):
    cfg.manager = "unknown-lib"
    with pytest.raises(typer.Exit) as exc:
        cli_runtime._require_manager(cfg)
    assert exc.value.exit_code == 1


def test_cfg_loads_from_path(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "a@b.org"\nout_dir = "{tmp_path / "o"}"\n'
        f'state_dir = "{tmp_path / "s"}"\n',
        encoding="utf-8",
    )
    loaded = cli_runtime._cfg(p)
    assert loaded.email == "a@b.org"


def test_warn_disclaimers(monkeypatch):
    c = Console(width=120, record=True)
    monkeypatch.setattr(cli_runtime, "console", c)
    cli_runtime._warn_if_scihub(["scihub"])
    cli_runtime._warn_if_recover(["browser_agent"])
    cli_runtime._warn_if_camofox(["camofox"])
    blob = c.export_text().lower()
    assert "sci-hub" in blob or "scihub" in blob
    assert "browser" in blob or "recover" in blob


def test_offline_flag(monkeypatch):
    monkeypatch.delenv("PAPERFUL_OFFLINE", raising=False)
    cli_runtime._OFFLINE = False
    assert cli_runtime._offline() is False
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    assert cli_runtime._offline() is True
    cli_runtime._OFFLINE = True
    monkeypatch.delenv("PAPERFUL_OFFLINE", raising=False)
    assert cli_runtime._offline() is True
    cli_runtime._OFFLINE = False


class _FakeBound:
    collections = ["ocean"]
    library = False
    year_from = 2010
    year_to = 2020
    types = ["journalArticle"]
    limit = 2
    apply = False


def test_bind_scoped_refuses_unset():
    with pytest.raises(typer.Exit) as exc:
        cli_runtime._bind_scoped(
            collection=[],
            library=None,
            profile=None,
            run_config=None,
            config=None,
        )
    assert exc.value.exit_code == 1


def test_bind_scoped_and_connect_scope(cfg, monkeypatch):
    monkeypatch.setattr(cli_runtime, "_cfg", lambda path: cfg)
    monkeypatch.setattr(cli_runtime, "_bind_run", lambda cfg, **k: _FakeBound())
    scoped = cli_runtime._bind_scoped(
        collection=["ocean"],
        library=False,
        profile=None,
        run_config=None,
        config=None,
        year_from=2010,
        year_to=2020,
        item_type=["journalArticle"],
        limit=2,
    )
    assert scoped.collection == ["ocean"]
    assert scoped.limit == 2
    assert scoped.cfg is cfg

    class Loaded:
        items = ["a", "b", "c"]
        label = "ocean"

    backend = object()
    required: list[bool] = []

    def _require(cfg):
        required.append(True)

    monkeypatch.setattr(cli_runtime, "_require_manager", _require)
    monkeypatch.setattr(cli_runtime, "_connect", lambda cfg, quiet=False: backend)
    monkeypatch.setattr(
        cli_runtime, "_load_scope", lambda *a, **k: Loaded()
    )
    got, loaded, items = cli_runtime._connect_scope(
        scoped, quiet=True, json_out=True, require_manager=True
    )
    assert required == [True]
    assert got is backend
    assert loaded.label == "ocean"
    assert items == ["a", "b"]


def test_bind_scoped_refuses_empty_after_bind(cfg, monkeypatch):
    class Empty:
        collections: list[str] = []
        library = False
        year_from = None
        year_to = None
        types: list[str] = []
        limit = None

    monkeypatch.setattr(cli_runtime, "_cfg", lambda path: cfg)
    monkeypatch.setattr(cli_runtime, "_bind_run", lambda cfg, **k: Empty())
    with pytest.raises(typer.Exit) as exc:
        cli_runtime._bind_scoped(
            collection=["ghost"],
            library=False,
            profile=None,
            run_config=None,
            config=None,
        )
    assert exc.value.exit_code == 1
