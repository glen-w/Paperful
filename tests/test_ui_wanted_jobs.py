"""Wanted Advanced job hooks."""

from __future__ import annotations

import time

import pytest

from paperful.config import Config
from paperful.ui import commands, wanted_jobs


def test_attach_preview_apply_hook(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    calls: list[dict] = []

    def fake_attach(cfg, *, keys, allow_mismatch, allow_short):
        calls.append(
            {
                "keys": keys,
                "allow_mismatch": allow_mismatch,
                "allow_short": allow_short,
            }
        )
        return {}

    monkeypatch.setattr(wanted_jobs, "attach_pending_fn", fake_attach)
    monkeypatch.setattr(
        wanted_jobs,
        "_load_items",
        lambda _c, _col: (None, [], __import__("paperful.store", fromlist=["Manifest"]).Manifest(cfg.manifest_path)),
    )
    from paperful.store import Manifest

    monkeypatch.setattr(
        wanted_jobs,
        "_load_items",
        lambda _c, _col: (object(), [], Manifest(cfg.manifest_path)),
    )
    cmd_id = "a1"
    commands.write_command(
        cfg,
        {
            "id": cmd_id,
            "verb": "attach",
            "status": "running",
            "review_token": "",
            "error": "",
            "report_path": "",
            "created": time.time(),
        },
    )
    token = wanted_jobs.attach_preview(
        cfg,
        cmd_id,
        collection="ocean/BBNJ",
        keys=["K1"],
        allow_mismatch=True,
        allow_short=False,
    )
    ok, msg = wanted_jobs.attach_apply(cfg, token=token)
    assert ok, msg
    assert calls and calls[0]["allow_mismatch"] is True


@pytest.mark.skipif(
    __import__("paperful.serve", fromlist=["fastapi_available"]).fastapi_available() is False,
    reason="paperful[serve] extra missing",
)
def test_wanted_attach_http_409(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr(
        ops,
        "doctor_payload",
        lambda _cfg, probe=False: [{"name": "x", "status": "green", "code": "", "detail": ""}],
    )
    client = TestClient(create_app(cfg))
    res = client.post("/wanted/attach", data={"review_token": "missing"})
    assert res.status_code == 409


def test_handoff_list_hook(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr(
        wanted_jobs,
        "handoff_fn",
        lambda cfg, **kw: {"mode": kw["mode"], "count": 0},
    )
    result = wanted_jobs.handoff_run(
        cfg, "h1", collection="x", keys=None, mode="list", include_doi_tabs=False
    )
    assert result["mode"] == "list"
