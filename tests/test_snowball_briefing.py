"""Markdown briefing from a snowball queue or watch inbox. No network."""

from __future__ import annotations

import json
from types import SimpleNamespace

from typer.testing import CliRunner

from paperful.cli import app
from paperful.snowball.briefing import write_run_briefing, write_watch_briefing
from paperful.snowball.candidate import Candidate
from paperful.snowball.command import SnowballError
from paperful.snowball.queue import write_queue
from paperful.snowball.watch import SCHEMA, save_watch
from tests.test_snowball import _cfg


def _row(*, status: str, doi: str, title: str, year: int | None = 2020, **biblio):
    body = {"title": title, "year": year, "is_oa": True}
    body.update(biblio)
    return Candidate(
        "R1",
        {"type": "doi", "value": doi},
        0,
        "search",
        {"doi": doi},
        body,
        "hit",
        status,
        {"backend": "openalex", "stamp": "oa:unpaywall"},
        "dry-run",
    )


def test_run_briefing_splits_new_and_exists(tmp_path):
    cfg = _cfg(tmp_path)
    client = SimpleNamespace(requests=0, status_429=0, retries=0, deferred=None)
    write_queue(
        cfg.state_dir,
        "R1",
        [
            _row(status="new", doi="10.1000/a", title="Alpha"),
            _row(status="exists", doi="10.1000/b", title="Beta", is_oa=False),
        ],
        client,
        library_unread=False,
    )
    briefing = write_run_briefing(cfg, "R1")
    text = briefing.path.read_text(encoding="utf-8")
    assert briefing.path == cfg.state_dir / "snowball" / "R1" / "briefing.md"
    assert briefing.counts["new"] == 1
    assert briefing.counts["exists"] == 1
    assert briefing.counts["deferred"] == 0
    assert "## New" in text
    assert "Alpha" in text
    assert "`10.1000/a`" in text
    assert "oa:unpaywall" in text
    assert "## Exists" in text
    assert "Beta" in text
    assert "## Deferred" not in text
    assert "Snowball briefing R1: 1 new" in briefing.html


def test_run_briefing_flags_deferred_openalex(tmp_path):
    cfg = _cfg(tmp_path)
    client = SimpleNamespace(
        requests=1,
        status_429=0,
        retries=0,
        deferred={"reset_at": "soon"},
    )
    write_queue(
        cfg.state_dir,
        "R2",
        [_row(status="new", doi="10.1000/c", title="Cee")],
        client,
        library_unread=False,
    )
    briefing = write_run_briefing(cfg, "R2")
    assert briefing.counts["deferred"] == 1
    assert "snowball resume R2" in briefing.markdown


def test_run_briefing_missing_queue(tmp_path):
    cfg = _cfg(tmp_path)
    try:
        write_run_briefing(cfg, "missing")
    except SnowballError as exc:
        assert exc.code == 1
        assert "missing" in str(exc)
    else:
        raise AssertionError("expected SnowballError")


def test_watch_briefing_from_inbox(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "profiles").mkdir()
    from paperful.snowball.profile import save_profile

    save_profile(
        cfg,
        "keyword-scout",
        {"mode": "search", "query": "bbnj", "gate": "dry-run"},
        force=False,
    )
    dest = save_watch(cfg, "bbnj", "keyword-scout").parent
    row = _row(status="new", doi="10.1000/watch", title="Watch hit", oa_status="gold")
    (dest / "inbox.jsonl").write_text(
        json.dumps(row.to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    watch = json.loads((dest / "watch.json").read_text(encoding="utf-8"))
    watch["baseline_at"] = "2026-01-01T00:00:00Z"
    watch["last_run_id"] = "R9"
    (dest / "watch.json").write_text(json.dumps(watch) + "\n", encoding="utf-8")
    briefing = write_watch_briefing(cfg, "bbnj")
    assert briefing.path == dest / "briefing.md"
    assert "Watch hit" in briefing.markdown
    assert "oa:gold" in briefing.markdown
    assert "Last run `R9`" in briefing.markdown
    assert SCHEMA in (dest / "watch.json").read_text(encoding="utf-8")


def test_cli_snowball_briefing_writes_markdown(tmp_path):
    cfg = _cfg(tmp_path)
    client = SimpleNamespace(requests=0, status_429=0, retries=0, deferred=None)
    write_queue(
        cfg.state_dir,
        "R1",
        [_row(status="new", doi="10.1000/a", title="Alpha")],
        client,
        library_unread=False,
    )
    runner = CliRunner()
    res = runner.invoke(
        app,
        ["snowball", "briefing", "--run-id", "R1", "-c", str(tmp_path / "config.toml")],
    )
    assert res.exit_code == 0, res.output
    assert "new 1" in res.output
    assert (cfg.state_dir / "snowball" / "R1" / "briefing.md").is_file()


def test_watch_briefing_empty_after_baseline(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "profiles").mkdir()
    from paperful.snowball.profile import save_profile

    save_profile(
        cfg,
        "keyword-scout",
        {"mode": "search", "query": "bbnj", "gate": "dry-run"},
        force=False,
    )
    dest = save_watch(cfg, "bbnj", "keyword-scout").parent
    watch = json.loads((dest / "watch.json").read_text(encoding="utf-8"))
    watch["baseline_at"] = "2026-01-01T00:00:00Z"
    (dest / "watch.json").write_text(json.dumps(watch) + "\n", encoding="utf-8")
    briefing = write_watch_briefing(cfg, "bbnj")
    assert "inbox is empty" in briefing.markdown
    assert briefing.counts["new"] == 0
