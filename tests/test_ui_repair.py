"""Repair queue review tokens (wave 7)."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available
from paperful.ui import commands, jobs


def test_repair_preview_enqueues_lint_hook(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    calls: list[str] = []

    from paperful.ui import repair_mirror_jobs

    def hook(cfg, cmd_id, **kwargs):
        calls.append(kwargs.get("verb", ""))
        rec = commands.read_command(cfg, cmd_id) or {}
        rec["status"] = "done"
        rec["verb"] = "lint"
        rec["summary"] = {"findings": 0}
        commands.write_command(cfg, rec)

    repair_mirror_jobs.repair_preview_core_fn = hook
    try:
        cmd_id = commands.enqueue(
            cfg,
            "repair_lint",
            lambda cid: jobs.repair_preview(
                cfg, cid, verb="lint", collection="BBNJ"
            ),
        )
        import time

        deadline = time.time() + 2
        while time.time() < deadline:
            rec = commands.read_command(cfg, cmd_id)
            if rec and rec.get("status") == "done":
                break
            time.sleep(0.02)
        assert calls == ["lint"]
    finally:
        repair_mirror_jobs.repair_preview_core_fn = None


def test_repair_stale_token_refused(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    token = commands.create_review_token(
        cfg,
        verb="dedupe",
        collection="BBNJ",
        preset="oa",
        keys=["K1"],
        fingerprint="abc",
        command_id="x",
    )
    ok, msg = commands.consume_review(cfg, token, fingerprint="changed", keys=None)
    assert not ok
    assert "changed" in msg.lower()


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_repair_apply_http_409(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr(
        ops,
        "doctor_payload",
        lambda _cfg, probe=False: [{"name": "x", "status": "green", "code": "", "detail": ""}],
    )
    client = TestClient(create_app(cfg))
    res = client.post("/repair/apply", data={"review_token": "missing"})
    assert res.status_code == 409


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_mirror_get_does_not_write(tmp_path, monkeypatch):
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
    client.cookies.set("pf_advanced", "1")
    before = {p.name for p in cfg.state_dir.iterdir()}
    res = client.get("/mirror")
    assert res.status_code == 200
    after = {p.name for p in cfg.state_dir.iterdir()}
    assert after == before
    res2 = client.post("/mirror/apply", data={"review_token": "nope"})
    assert res2.status_code == 409
