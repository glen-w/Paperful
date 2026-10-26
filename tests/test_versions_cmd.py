"""``paperful versions`` command paths (offline stubs)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer
from rich.console import Console

from paperful.cli_runtime import BoundScope
from paperful.run_config import ResolvedRunConfig
from paperful.versions_cmd import run_versions


def _scoped(cfg, *, apply=False):
    bound = ResolvedRunConfig(apply=apply, collections=["BBNJ"], library=False)
    return BoundScope(
        cfg=cfg,
        bound=bound,
        collection=["BBNJ"],
        library=False,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
    )


def _run(console, cfg, *, dry_run=True, apply=None, as_json=False):
    return run_versions(
        console,
        collection=["BBNJ"],
        library=False,
        dry_run=dry_run,
        apply=apply,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
        as_json=as_json,
        profile=None,
        run_config=None,
        config=None,
    )


def test_versions_rejects_dry_run_and_apply(cfg, monkeypatch):
    monkeypatch.setattr(
        "paperful.cli_runtime._bind_scoped", lambda **_k: _scoped(cfg, apply=True)
    )
    with pytest.raises(typer.Exit):
        _run(Console(record=True), cfg, dry_run=True, apply=True)


def test_versions_dry_run_writes_pack(cfg, tmp_path, monkeypatch):
    json_path = tmp_path / "pack.json"
    md_path = tmp_path / "pack.md"
    json_path.write_text("{}", encoding="utf-8")
    md_path.write_text("# versions\n", encoding="utf-8")
    monkeypatch.setattr(
        "paperful.cli_runtime._bind_scoped", lambda **_k: _scoped(cfg, apply=False)
    )
    monkeypatch.setattr(
        "paperful.cli_runtime._connect_scope",
        lambda *_a, **_k: (SimpleNamespace(), SimpleNamespace(label="BBNJ"), []),
    )
    monkeypatch.setattr("paperful.versions.classify_versions", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "paperful.versions.write_pack", lambda *_a, **_k: (json_path, md_path)
    )
    monkeypatch.setattr(
        "paperful.versions.pack_counts", lambda *_a, **_k: {"pairs": 0}
    )
    monkeypatch.setattr("paperful.versions.resolver_for", lambda *_a, **_k: lambda x: x)
    monkeypatch.setattr(
        "paperful.cli_runtime._item_progress",
        lambda **_k: __import__("contextlib").nullcontext(SimpleNamespace()),
    )
    monkeypatch.setattr("paperful.cli_runtime._track", lambda *_a, **_k: (lambda xs: xs))
    monkeypatch.setattr("paperful.cli_runtime._print_version_table", lambda _p: None)
    console = Console(record=True)
    _run(console, cfg, dry_run=True, apply=False)
    assert "Dry-run" in console.export_text()


def test_versions_json_and_apply_errors(cfg, tmp_path, monkeypatch):
    from paperful.library import LibraryError

    json_path = tmp_path / "pack.json"
    md_path = tmp_path / "pack.md"
    json_path.write_text("{}", encoding="utf-8")
    md_path.write_text("# versions\n", encoding="utf-8")
    backend = SimpleNamespace(supports_write=lambda: True)
    monkeypatch.setattr(
        "paperful.cli_runtime._bind_scoped", lambda **_k: _scoped(cfg, apply=True)
    )
    monkeypatch.setattr(
        "paperful.cli_runtime._connect_scope",
        lambda *_a, **_k: (backend, SimpleNamespace(label="BBNJ"), []),
    )
    monkeypatch.setattr("paperful.versions.classify_versions", lambda *_a, **_k: ["p"])
    monkeypatch.setattr(
        "paperful.versions.write_pack", lambda *_a, **_k: (json_path, md_path)
    )
    monkeypatch.setattr(
        "paperful.versions.pack_counts", lambda *_a, **_k: {"pairs": 1}
    )
    monkeypatch.setattr("paperful.versions.resolver_for", lambda *_a, **_k: lambda x: x)
    monkeypatch.setattr(
        "paperful.versions.http_fetch_published", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "paperful.cli_runtime._item_progress",
        lambda **_k: __import__("contextlib").nullcontext(SimpleNamespace()),
    )
    monkeypatch.setattr("paperful.cli_runtime._track", lambda *_a, **_k: (lambda xs: xs))

    def apply_ok(*_a, **_k):
        return 1, ["oops"]

    monkeypatch.setattr("paperful.versions.apply_versions", apply_ok)
    console = Console(record=True)
    with pytest.raises(typer.Exit):
        _run(console, cfg, dry_run=False, apply=True, as_json=True)

    def apply_lib(*_a, **_k):
        raise LibraryError("no write")

    monkeypatch.setattr("paperful.versions.apply_versions", apply_lib)
    monkeypatch.setattr(
        "paperful.cli_runtime._exit_env",
        lambda *_a, **_k: (_ for _ in ()).throw(typer.Exit(1)),
    )
    with pytest.raises(typer.Exit):
        _run(Console(record=True), cfg, dry_run=False, apply=True)
