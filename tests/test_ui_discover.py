"""Discover write paths (wave 5)."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.ui import commands, jobs


def test_topic_enqueues_without_apply(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    applied = []
    searched = []

    def run_fn(cfg, cmd_id, payload=None, collection=""):
        searched.append(getattr(payload, "query", ""))

    def apply(cfg, run_id="", collection=""):
        applied.append(run_id)

    jobs.snowball_run_fn = run_fn
    jobs.snowball_apply_fn = apply

    cmd_id = commands.enqueue(
        cfg,
        "snowball_search",
        lambda cid: jobs.track_topic(cfg, cid, query="BBNJ", collection="ocean"),
    )
    import time

    deadline = time.time() + 2
    while time.time() < deadline:
        rec = commands.read_command(cfg, cmd_id)
        if rec and rec.get("status") == "done":
            break
        time.sleep(0.02)
    assert searched == ["BBNJ"]
    assert applied == []
    jobs.discover_apply_snowball(cfg, "run1", "ocean")
    assert applied == ["run1"]
    jobs.snowball_run_fn = None
    jobs.snowball_apply_fn = None


def test_follow_without_backfill(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    calls = []

    def run_fn(cfg, orcid="", list_name="", backfill_from=None):
        calls.append({"orcid": orcid, "backfill": backfill_from})

    jobs.authorwatch_run_fn = run_fn
    jobs.follow_person(cfg, "x", orcid="0000-0002-1825-0097", list_name="p", backfill_from=None)
    assert calls[0]["backfill"] is None
    jobs.authorwatch_run_fn = None


def test_advanced_direction_only_when_posted(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    jobs.snowball_run_calls.clear()
    jobs.snowball_run_fn = lambda *a, **k: None
    jobs.track_topic(cfg, "c1", query="BBNJ", collection="ocean")
    jobs.track_topic(cfg, "c2", query="BBNJ", collection="ocean", direction="cites")
    assert jobs.snowball_run_calls[0]["kind"] == "search"
    assert jobs.snowball_run_calls[1]["kind"] == "search"
    jobs.snowball_run_fn = None
    jobs.snowball_run_calls.clear()


def test_check_again_does_not_create_parents(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    applied: list[str] = []
    jobs.authorwatch_apply_fn = lambda cfg, list_name="", collection="": applied.append(list_name)
    jobs.authorwatch_run_fn = lambda cfg, orcid="", list_name="", backfill_from=None: None
    jobs.follow_person(cfg, "x", orcid="0000-0002-1825-0097", list_name="p", backfill_from=None)
    assert applied == []
    jobs.authorwatch_apply_fn = None
    jobs.authorwatch_run_fn = None


@pytest.mark.skipif(
    __import__("paperful.serve", fromlist=["fastapi_available"]).fastapi_available() is False,
    reason="paperful[serve] extra missing",
)
def test_discover_topic_kind_doi_enqueues(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        ops, "collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    jobs.snowball_run_calls.clear()
    jobs.snowball_run_fn = lambda *a, **k: None
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_advanced", "1")
    client.post(
        "/discover/topic",
        data={"kind": "doi", "seeds": "10.1000/example", "query": ""},
    )
    deadline = time.time() + 2
    while time.time() < deadline:
        if jobs.snowball_run_calls:
            break
        time.sleep(0.02)
    assert jobs.snowball_run_calls
    assert jobs.snowball_run_calls[-1]["kind"] == "doi"
    assert "10.1000/example" in jobs.snowball_run_calls[-1]["seeds"]
    jobs.snowball_run_fn = None
    jobs.snowball_run_calls.clear()
