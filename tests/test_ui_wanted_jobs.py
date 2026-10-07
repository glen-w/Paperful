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


class _Item:
    def __init__(self, key: str, doi: str = "") -> None:
        self.key = key
        self.doi = doi
        self.title = key


def test_attach_preview_fingerprint_matches_pending_subset(tmp_path, monkeypatch):
    """Preview hashes the pending keys, not the whole collection (false 409)."""
    from paperful.store import STATUS_OK, Manifest, Record

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    items = [_Item("K1", "10.1/a"), _Item("K2", "10.2/b")]
    manifest = Manifest(cfg.manifest_path)
    manifest.write(
        Record(itemKey="K1", status=STATUS_OK, doi="10.1/a", path="a.pdf")
    )
    monkeypatch.setattr(
        wanted_jobs,
        "_load_items",
        lambda _c, _col: (object(), items, manifest),
    )
    monkeypatch.setattr(wanted_jobs, "attach_pending_fn", lambda *a, **k: {})
    cmd_id = "a2"
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
        keys=None,
        allow_mismatch=False,
        allow_short=False,
    )
    ok, msg = wanted_jobs.attach_apply(cfg, token=token)
    assert ok, msg


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


@pytest.mark.skipif(
    __import__("paperful.serve", fromlist=["fastapi_available"]).fastapi_available() is False,
    reason="paperful[serve] extra missing",
)
def test_wanted_attach_keys_ignore_stale_preview(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app
    from paperful.ui import jobs

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    commands.create_review_token(
        cfg,
        verb="attach",
        collection="ocean/BBNJ",
        preset="oa",
        keys=["OLD"],
        fingerprint="stale",
        command_id="stale-attach",
    )
    monkeypatch.setattr(
        ops,
        "doctor_payload",
        lambda _cfg, probe=False: [{"name": "x", "status": "green", "code": "", "detail": ""}],
    )
    attached: list[str] = []

    def fake_attach_run(cfg, *, keys, collection):
        attached.extend(keys)
        return True, ""

    monkeypatch.setattr(jobs, "attach_run", fake_attach_run)
    client = TestClient(create_app(cfg))
    res = client.post(
        "/wanted/attach",
        data={"keys": ["K1", "K2"]},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert attached == ["K1", "K2"]


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
