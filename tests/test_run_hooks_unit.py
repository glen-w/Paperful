"""Small helpers in ``run_hooks`` (no live browser)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from paperful.config import Config
from paperful.run_hooks import (
    confirm_session_login,
    flush_backend,
    gaps_downloads_dir,
    rag_auto_after_command,
    stdin_is_tty,
)


def test_gaps_downloads_dir_override_and_default(tmp_path, cfg):
    custom = tmp_path / "dl"
    assert gaps_downloads_dir(cfg, custom) == custom
    cfg.gaps_downloads_dir = str(tmp_path / "from_cfg")
    assert gaps_downloads_dir(cfg, None) == Path(cfg.gaps_downloads_dir)
    cfg.gaps_downloads_dir = ""
    assert gaps_downloads_dir(cfg, None) == Path.home() / "Downloads"


def test_confirm_session_login_eof(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: (_ for _ in ()).throw(EOFError))
    confirm_session_login(Console(record=True))  # should not raise


def test_flush_backend_warns_unrefreshed():
    class Backend:
        unrefreshed = ["K1"]

    flush_backend(Console(record=True), Backend())


def test_flush_backend_endnote_bundle():
    class Backend:
        unrefreshed = []

        def flush_writes(self):
            return "/tmp/paperful.xml"

    flush_backend(Console(record=True), Backend())


def test_rag_auto_skips_when_disabled(cfg, monkeypatch):
    cfg.rag_enabled = False
    rag_auto_after_command(Console(record=True), cfg, since=0.0)


def test_rag_auto_prints_summary(cfg, monkeypatch):
    cfg.rag_enabled = True
    cfg.rag_auto_ingest = True

    class Batch:
        chunks = 4

        def count(self, *a):
            return 2

    monkeypatch.setattr(
        "paperful.rag.auto.auto_ingest",
        lambda *a, **k: Batch(),
    )
    c = Console(record=True)
    rag_auto_after_command(c, cfg, since=0.0)
    assert "Index:" in c.export_text()


def test_stdin_is_tty_delegates(monkeypatch):
    monkeypatch.setattr("paperful.cli_runtime._stdin_is_tty", lambda: False)
    assert stdin_is_tty() is False
