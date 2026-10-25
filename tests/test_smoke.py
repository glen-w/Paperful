"""Minimal CI gate: package boots and the workbench serves pages.

Keep these assertions coarse. Copy, nav order, and feature contracts belong
in the full suite — not here — so routine UI edits do not turn CI red.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from paperful import cli
from paperful.config import Config
from paperful.serve import create_app, fastapi_available

runner = CliRunner()


@pytest.mark.smoke
def test_cli_version():
    res = runner.invoke(cli.app, ["version"])
    assert res.exit_code == 0
    assert res.stdout.strip()


@pytest.mark.smoke
def test_cli_help():
    res = runner.invoke(cli.app, ["--help"])
    assert res.exit_code == 0
    assert "paperful" in res.stdout.lower() or "Usage" in res.stdout


@pytest.mark.smoke
@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_workbench_boots(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    doctor = lambda _cfg, probe=False: [
        {"name": "Zotero", "status": "red", "code": "zotero_down", "detail": "down"}
    ]
    monkeypatch.setattr(ops, "doctor_payload", doctor)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", doctor)
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": False, "error": "Zotero is not reachable", "collections": []},
    )
    client = TestClient(create_app(cfg))
    assert client.get("/", follow_redirects=False).status_code == 302
    for path in ("/wanted", "/discover", "/ask", "/library", "/activity", "/system"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert "Paperful" in res.text
