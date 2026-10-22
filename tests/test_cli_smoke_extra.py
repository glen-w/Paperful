"""Extra CLI smoke: thin paths that bump coverage without live network."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from paperful import cli, cli_runtime

runner = CliRunner()


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
        'scihub_mirrors = ["m1.test"]\n'
    )
    return p


@pytest.fixture
def stub_zotero(monkeypatch):
    from tests.test_cli import StubZL

    zl = StubZL()
    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: zl)
    monkeypatch.setattr(cli_runtime, "ZoteroLocal", lambda *a, **k: zl)
    return zl


def _smoke_patches(monkeypatch):
    monkeypatch.setattr("paperful.screen.screen_items", lambda *a, **k: [])
    monkeypatch.setattr("paperful.lint.lint_items", lambda *a, **k: [])
    monkeypatch.setattr(
        "paperful.pipeline.make_client",
        lambda cfg: type("C", (), {"close": lambda self: None})(),
    )
    monkeypatch.setattr(
        "paperful.sync.run_sync",
        lambda *a, **k: __import__(
            "paperful.sync", fromlist=["SyncStats"]
        ).SyncStats(),
    )
    monkeypatch.setattr(
        "paperful.mirrors_cmd.ping_mirrors",
        lambda ctx: [("m1.test", "HTTP 200")],
    )


@pytest.mark.parametrize(
    "args",
    [
        ["gaps", "--library", "--format", "json"],
        ["screen", "--library", "--format", "json"],
        ["ocr-ignore", "list"],
        ["doctor", "--json"],
        ["cache", "clean"],
        ["cache", "clean", "--format", "json"],
        ["lint", "--library", "--format", "json"],
        ["collections", "list"],
        ["sync", "--dry-run"],
        ["mirrors"],
        ["pack", "show", "--json"],
        ["session", "status"],
        ["versions", "--library", "--dry-run", "--json"],
        ["refs", "gap", "--collection", "BBNJ", "--format", "json"],
        ["attach"],
    ],
)
def test_cli_smoke_commands(cfg_file, stub_zotero, monkeypatch, args, tmp_path):
    _smoke_patches(monkeypatch)
    monkeypatch.setattr(
        "paperful.cli_runtime._load_scope",
        lambda *a, **k: type("L", (), {"items": [], "label": "library"})(),
    )

    class _B:
        def items_in_scope(self, keys):
            return []

        def collections(self):
            return {}

        def collection_counts(self):
            return {}

        def supports_write(self):
            return True

        def close(self):
            pass

    monkeypatch.setattr("paperful.cli_runtime._connect", lambda *a, **k: _B())
    res = runner.invoke(cli.app, [*args, "-c", str(cfg_file)])
    assert res.exit_code == 0, res.stdout + res.stderr
    if args[:2] == ["gaps", "--library"] and "--format" in args:
        body = json.loads(res.stdout)
        assert body.get("schema") == "paperful.agent.json.v1"
    if args[:2] == ["screen", "--library"] and "--format" in args:
        body = json.loads(res.stdout)
        assert body.get("command") == "screen"
