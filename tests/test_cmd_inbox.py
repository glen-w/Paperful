"""``paperful inbox watch`` and ``inbox proposals apply`` wiring (library and matcher stubbed)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from paperful import cli, cli_runtime
from paperful.inbox import WatchStats

runner = CliRunner()


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    from rich.console import Console

    monkeypatch.setattr(cli, "console", Console(highlight=False, width=250, height=100))
    monkeypatch.setattr(cli_runtime, "console", cli.console)


@pytest.fixture
def cfg_file(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n[inbox]\ndir = "{drop}"\n'
    )
    return p


class Backend:
    def __init__(self, write=True):
        self._write = write
        self.flushed = False

    def supports_write(self):
        return self._write

    def flush_writes(self):
        self.flushed = True


def _wire(monkeypatch, backend):
    monkeypatch.setattr(cli_runtime, "_connect", lambda cfg, quiet=False: backend)
    monkeypatch.setattr(
        cli_runtime,
        "_load_scope",
        lambda b, json_out=False, **scope: SimpleNamespace(items=[], label="library"),
    )


def test_inbox_watch_defaults_to_whole_library_and_reports(cfg_file, monkeypatch):
    backend = Backend()
    _wire(monkeypatch, backend)
    seen: dict = {}

    def fake_process(cfg, backend_, manifest, items, **kw):
        seen.update(kw)
        return WatchStats(attached=2, unmatched=1, skipped=3, quit_reason="idle")

    monkeypatch.setattr("paperful.inbox.process_candidates", fake_process)
    res = runner.invoke(cli.app, ["inbox", "watch", "--idle", "1.5", "--tag", "inbox", "-c", str(cfg_file)])
    assert res.exit_code == 0, res.output
    assert "watching" in res.output and "library" in res.output
    assert "Inbox attached 2, unmatched 1" in res.output and "(idle)" in res.output
    assert "Inbox report:" in res.output
    assert seen["once"] is False and seen["idle_seconds"] == 1.5
    assert seen["extra_tags"] == ["inbox"] and seen["collection"] == ""
    assert backend.flushed


def test_inbox_watch_passes_first_collection_and_requires_write(cfg_file, monkeypatch):
    backend = Backend(write=False)
    _wire(monkeypatch, backend)
    monkeypatch.setattr(
        "paperful.inbox.process_candidates",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run read-only")),
    )
    res = runner.invoke(cli.app, ["inbox", "watch", "-C", "Ocean", "-c", str(cfg_file)])
    assert res.exit_code == 2
    assert "inbox watch needs library write support" in res.output

    backend._write = True
    seen: dict = {}
    monkeypatch.setattr(
        "paperful.inbox.process_candidates", lambda *a, **k: seen.update(k) or WatchStats()
    )
    res = runner.invoke(cli.app, ["inbox", "watch", "-C", "Ocean", "-c", str(cfg_file)])
    assert res.exit_code == 0, res.output
    assert seen["collection"] == "Ocean"


def test_inbox_watch_reports_bad_inbox_dir(cfg_file, monkeypatch):
    _wire(monkeypatch, Backend())

    def bad(cfg):
        raise ValueError("inbox.dir must be outside out/")

    monkeypatch.setattr("paperful.inbox.ensure_inbox_dirs", bad)
    res = runner.invoke(cli.app, ["inbox", "watch", "-c", str(cfg_file)])
    assert res.exit_code == 1 and "inbox.dir must be outside out/" in res.output


def _apply(cfg_file, *extra):
    return runner.invoke(cli.app, ["inbox", "proposals", "apply", "P1", "-c", str(cfg_file), *extra])


def test_inbox_proposals_apply_success_json_and_human(cfg_file, monkeypatch):
    backend = Backend()
    _wire(monkeypatch, backend)
    got: dict = {}

    def fake_apply(cfg, backend_, manifest, pid, extra_tags=None):
        got.update(pid=pid, tags=extra_tags)
        return {"item_key": "K9", "action": "attach", "id": pid}

    monkeypatch.setattr("paperful.inbox.apply_proposal", fake_apply)
    human = _apply(cfg_file, "--tag", "t1")
    assert human.exit_code == 0, human.output
    assert "Applied proposal P1" in human.output and "K9" in human.output
    assert got == {"pid": "P1", "tags": ["t1"]}
    assert backend.flushed

    res = _apply(cfg_file, "--format", "json")
    body = json.loads(res.stdout)
    assert body["command"] == "inbox proposals apply"
    assert body["summary"] == {"id": "P1", "item_key": "K9", "action": "attach"}


@pytest.mark.parametrize("exc", [FileNotFoundError("no proposal P1"), ValueError("not pending")])
def test_inbox_proposals_apply_errors_exit_1(cfg_file, monkeypatch, exc):
    _wire(monkeypatch, Backend())
    monkeypatch.setattr(
        "paperful.inbox.apply_proposal", lambda *a, **k: (_ for _ in ()).throw(exc)
    )
    res = _apply(cfg_file)
    assert res.exit_code == 1 and str(exc) in res.output


def test_inbox_proposals_apply_needs_write_support(cfg_file, monkeypatch):
    _wire(monkeypatch, Backend(write=False))
    res = _apply(cfg_file)
    assert res.exit_code == 2 and "inbox proposals apply needs library write support" in res.output
