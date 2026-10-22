"""GUI command ledger (wave 3)."""

from __future__ import annotations

import json
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
def test_run_events_sse(tmp_path):
    from fastapi.testclient import TestClient

    jobs.noop_sleep = 0.08
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    client = TestClient(create_app(cfg))
    res = client.post("/v1/gui/noop")
    cmd_id = res.json()["id"]
    statuses: list[str] = []
    with client.stream("GET", f"/v1/runs/{cmd_id}/events") as stream:
        assert stream.status_code == 200
        assert "text/event-stream" in (stream.headers.get("content-type") or "")
        buffer = ""
        deadline = time.time() + 3.0
        for chunk in stream.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                if block.startswith(":"):
                    continue
                for line in block.split("\n"):
                    if line.startswith("data: "):
                        body = json.loads(line[6:])
                        statuses.append(body.get("status", ""))
            if statuses and statuses[-1] in {"done", "failed"}:
                break
            if time.time() > deadline:
                break
    assert "queued" in statuses or "running" in statuses
    assert statuses[-1] == "done"


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_run_events_terminal_single_frame(tmp_path):
    from fastapi.testclient import TestClient

    from paperful.ui import commands

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cmd_id = "deadbeef0001"
    commands.write_command(
        cfg,
        {
            "id": cmd_id,
            "verb": "noop",
            "status": "done",
            "review_token": "",
            "error": "",
            "report_path": "",
            "created": time.time(),
        },
    )
    client = TestClient(create_app(cfg))
    chunks: list[str] = []
    with client.stream("GET", f"/v1/runs/{cmd_id}/events") as stream:
        assert stream.status_code == 200
        for chunk in stream.iter_text():
            chunks.append(chunk)
    body = "".join(chunks)
    assert "event: status" in body
    assert '"status":"done"' in body or '"status": "done"' in body
    assert body.count("event: status") == 1


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_run_events_not_found(tmp_path):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    client = TestClient(create_app(cfg))
    res = client.get("/v1/runs/nosuchid/events")
    assert res.status_code == 404


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
