"""Localhost capability API (paperful serve)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from paperful.agent_json import envelope
from paperful.config import Config
from paperful.serve import SERVE_HINT, create_app, fastapi_available


def test_serve_missing_extra_prints_hint(monkeypatch):
    monkeypatch.setattr("paperful.serve.fastapi_available", lambda: False)
    from paperful.cli import app

    res = CliRunner().invoke(app, ["serve"])
    assert res.exit_code == 1
    assert "uv sync --extra serve" in res.stdout
    assert "FastAPI" in SERVE_HINT


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_health_and_last_run(tmp_path):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    client = TestClient(create_app(cfg))
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["ok"] is True
    assert body["version"]
    last = client.get("/v1/runs/last")
    assert last.status_code == 200
    assert last.json() == {"ok": True, "report": None}
    report = {"schema": "paperful.run_report.v1", "command": "run"}
    (cfg.state_dir / "last-run.json").write_text(json.dumps(report))
    got = client.get("/v1/runs/last")
    assert got.json()["report"]["command"] == "run"


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_refs_gap_and_ask_use_agent_ops(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    monkeypatch.setattr(
        ops,
        "run_refs_gap",
        lambda _cfg, collection: envelope(
            command="refs gap",
            summary={"cited": 1, "missing": 1, "collection": collection},
            flags={"dry_run": True},
        ),
    )
    monkeypatch.setattr(
        ops,
        "run_ask",
        lambda _cfg, question, collection="": envelope(
            command="ask",
            summary={"question": question, "answered": 1},
            items=[{"question": question, "answer": "stub"}],
            flags={"read_only": True},
        ),
    )
    monkeypatch.setattr(
        ops,
        "doctor_payload",
        lambda _cfg, probe=False: [
            {"name": "Zotero :23119", "status": "green", "code": "", "detail": "ok"}
        ],
    )
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": True, "collections": [{"path": "BBNJ", "key": "C1"}]},
    )
    client = TestClient(create_app(cfg))
    gap = client.post("/v1/refs-gap", json={"collection": "BBNJ"})
    assert gap.status_code == 200
    gbody = gap.json()
    assert gbody["schema"] == "paperful.agent.json.v1"
    assert gbody["command"] == "refs gap"
    assert gbody["ok"] is True
    assert gbody["flags"]["dry_run"] is True
    ask = client.post("/v1/ask", json={"question": "What is BBNJ?", "collection": "BBNJ"})
    assert ask.status_code == 200
    abody = ask.json()
    assert abody["schema"] == "paperful.agent.json.v1"
    assert abody["command"] == "ask"
    assert abody["flags"]["read_only"] is True
    doctor = client.get("/v1/doctor")
    assert doctor.status_code == 200
    assert doctor.json()[0]["status"] == "green"
    cols = client.get("/v1/collections")
    assert cols.status_code == 200
    assert cols.json()["ok"] is True
