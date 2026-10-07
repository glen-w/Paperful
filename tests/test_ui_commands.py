"""GUI command ledger (wave 3)."""

from __future__ import annotations

import time

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available
from paperful.ui import jobs


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_noop_enqueue_and_poll(tmp_path):
    from fastapi.testclient import TestClient

    jobs.noop_sleep = 0.08
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    client = TestClient(create_app(cfg))
    res = client.post("/v1/gui/noop")
    assert res.status_code == 202
    body = res.json()
    cmd_id = body["id"]
    assert body["status"] == "queued"
    deadline = time.time() + 3.0
    status = "queued"
    while time.time() < deadline:
        got = client.get(f"/v1/runs/{cmd_id}").json()
        status = got.get("status")
        if status == "done":
            break
        time.sleep(0.02)
    assert status == "done"
    last = client.get("/v1/runs/last")
    assert last.status_code == 200
    assert "report" in last.json()


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_second_enqueue_stays_queued(tmp_path):
    from fastapi.testclient import TestClient

    jobs.noop_sleep = 0.25
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    client = TestClient(create_app(cfg))
    first = client.post("/v1/gui/noop").json()["id"]
    second = client.post("/v1/gui/noop").json()["id"]
    rec = client.get(f"/v1/runs/{second}").json()
    assert rec.get("status") in {"queued", "running"}
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if client.get(f"/v1/runs/{first}").json().get("status") == "done":
            break
        time.sleep(0.02)
