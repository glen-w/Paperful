"""Workbench snowball_run fallback dispatch (offline)."""

from __future__ import annotations

from paperful.config import Config
from paperful.snowball.command import SnowballError
from paperful.ui import commands, jobs
from paperful.ui.snowball_form import parse_discover_topic


def _cfg(tmp_path) -> Config:
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def test_snowball_run_dispatches_kinds(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    jobs.snowball_run_fn = None
    jobs.snowball_run_calls.clear()
    seen = []

    monkeypatch.setattr(
        "paperful.snowball.command.run_search",
        lambda *_a, **_k: seen.append("search"),
    )
    monkeypatch.setattr(
        "paperful.snowball.command.run_hybrid",
        lambda *_a, **_k: seen.append("hybrid"),
    )
    monkeypatch.setattr(
        "paperful.snowball.command.run_doi",
        lambda *_a, **_k: seen.append("doi"),
    )
    monkeypatch.setattr(
        "paperful.snowball.command.run_orcid",
        lambda *_a, **_k: seen.append("orcid"),
    )
    monkeypatch.setattr(
        "paperful.snowball.command.run_collection",
        lambda *_a, **_k: seen.append("collection"),
    )

    def go(kind, form, collection="BBNJ"):
        cmd_id = f"sb-{kind}"
        commands.write_command(cfg, {"id": cmd_id, "status": "running"})
        payload = parse_discover_topic(form, advanced=True)
        payload.twenty_writeback = True
        jobs.snowball_run(cfg, cmd_id, payload=payload, collection=collection)

    go("search", {"kind": "search", "query": "krill"})
    go("hybrid", {"kind": "hybrid", "query": "krill"})
    go("doi", {"kind": "doi", "query": "10.1000/abc"})
    go("orcid", {"kind": "orcid", "query": "0000-0002-1825-0097"})
    go("collection", {"kind": "collection"}, collection="BBNJ")
    assert seen == ["search", "hybrid", "doi", "orcid", "collection"]
    assert cfg.twenty_writeback_listings is True


def test_snowball_run_records_error(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    jobs.snowball_run_fn = None
    cmd_id = "sb-err"
    commands.write_command(cfg, {"id": cmd_id, "status": "running"})
    payload = parse_discover_topic({"kind": "search"}, advanced=True)
    monkeypatch.setattr(
        "paperful.snowball.command.run_search",
        lambda *_a, **_k: (_ for _ in ()).throw(SnowballError("Enter a keyword query.")),
    )
    try:
        jobs.snowball_run(cfg, cmd_id, payload=payload, collection="BBNJ")
        raise AssertionError("expected SnowballError")
    except SnowballError:
        rec = commands.read_command(cfg, cmd_id)
        assert rec["status"] == "failed"
        assert "keyword" in rec["error"].lower() or rec["error"]
