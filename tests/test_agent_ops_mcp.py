"""``agent_ops`` MCP runners with stubbed library (offline)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from paperful.agent_ops import (
    doctor_payload,
    gaps_envelope,
    ingest_dois_exit,
    last_run,
    run_ask,
    run_export,
    run_gaps,
    run_refs_gap,
    run_snowball_search,
    snowball_result_envelope,
)
from paperful.config import Config
from tests.conftest import make_item


def test_gaps_envelope_builds_rows():
    items = [
        make_item(key="K1", has_pdf=False, doi=""),
    ]
    items[0].has_linked_url = True
    items[0].pdf_tier = "snapshot"
    env = gaps_envelope(items, list_missing=True, handoff="inbox")
    assert env["command"] == "gaps"
    assert env["summary"]["no_stored_pdf"] >= 1
    assert env["flags"]["handoff"] == "inbox"


def test_run_gaps_requires_scope(cfg):
    out = run_gaps(cfg, collection=None, library=False)
    assert out["exit"] != 0
    assert "error" in out["summary"]


def test_run_gaps_library_empty(cfg, monkeypatch):
    class Backend:
        def items_in_scope(self, keys):
            return []

        def collections(self):
            return {}

    loaded = SimpleNamespace(items=[], label="library")

    monkeypatch.setattr("paperful.catalogue.open_library", lambda c: Backend())
    monkeypatch.setattr("paperful.scope.load_scope", lambda *a, **k: loaded)
    out = run_gaps(cfg, library=True)
    assert out["summary"]["items"] == 0


def test_run_refs_gap_missing_collection(cfg):
    out = run_refs_gap(cfg, "")
    assert out["summary"]["error"]


def test_doctor_payload_shape(cfg, monkeypatch):
    monkeypatch.setattr(
        "paperful.agent_ops.doctor_checks",
        lambda *a, **k: [SimpleNamespace(name="x", status="green", code="", detail="ok")],
    )
    rows = doctor_payload(cfg)
    assert rows[0]["name"] == "x"


def test_last_run_missing(cfg):
    assert last_run(cfg) is None


def test_ingest_dois_exit():
    assert ingest_dois_exit(apply=False, created=0, failed=0) == 0
    assert ingest_dois_exit(apply=True, created=1, failed=0) == 0


def test_snowball_result_envelope_from_dir(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text('{"hits": 2}', encoding="utf-8")
    result = SimpleNamespace(summary={}, run_dir=str(run_dir), exit_code=0)
    env = snowball_result_envelope("snowball search", result)
    assert env["summary"]["hits"] == 2


def test_run_ask_disabled(cfg, monkeypatch):
    cfg.rag_enabled = False
    out = run_ask(cfg, "why?", collection="")
    assert out["exit"] != 0 or "error" in str(out.get("summary", "")).lower()


def test_run_snowball_search_empty_query(cfg):
    out = run_snowball_search(cfg, "")
    assert out["exit"] != 0
