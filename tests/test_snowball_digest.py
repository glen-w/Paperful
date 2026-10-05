"""Frontier digest from a snowball queue or watch. No network."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

from typer.testing import CliRunner

from paperful.cli import app
from paperful.snowball.candidate import Candidate
from paperful.snowball.command import SnowballError
from paperful.snowball.digest import write_run_digest, write_watch_digest
from paperful.snowball.queue import write_queue
from tests.test_snowball import _cfg


def _row(
    *,
    status: str,
    doi: str,
    title: str,
    year: int | None = 2020,
    score: float = 0.0,
    why: str = "hit",
    hop: int = 0,
    direction: str = "search",
    **biblio,
):
    body = {"title": title, "year": year, "is_oa": True}
    body.update(biblio)
    return Candidate(
        "R1",
        {"type": "doi", "value": doi},
        hop,
        direction,
        {"doi": doi},
        body,
        why,
        status,
        {"backend": "openalex", "stamp": "oa:unpaywall"},
        "dry-run",
        score=score,
    )


def _queue(cfg, run_id: str, rows, *, deferred: bool = False):
    client = SimpleNamespace(requests=0, status_429=0, retries=0, deferred={"reset_at": "soon"} if deferred else None)
    write_queue(cfg.state_dir, run_id, rows, client, library_unread=False)


def _profile(cfg, name: str = "keyword-scout", **extra):
    from paperful.snowball.profile import save_profile

    (cfg.config_path.parent / "profiles").mkdir(exist_ok=True)
    body = {"mode": "search", "query": "bbnj", "gate": "dry-run"}
    body.update(extra)
    save_profile(cfg, name, body, force=False)


def test_run_digest_ranks_overlap_and_suggests_collection(tmp_path):
    cfg = _cfg(tmp_path, more='target_collection = "Inbox/Snowball Hits"\n')
    low = _row(
        status="new",
        doi="10.1000/low",
        title="Low overlap",
        score=3,
        why="one seed",
        hop=1,
        direction="refs",
        overlap=1,
    )
    high = _row(
        status="new",
        doi="10.1000/high",
        title="High overlap",
        score=2003,
        why="shares 2 references",
        hop=1,
        direction="refs",
        overlap=2,
        oa_status="gold",
    )
    exists = _row(status="exists", doi="10.1000/b", title="Beta", is_oa=False)
    _queue(cfg, "R1", [low, exists, high])
    digest = write_run_digest(cfg, "R1")
    text = digest.path.read_text(encoding="utf-8")
    assert digest.path == cfg.state_dir / "snowball" / "R1" / "digest.md"
    assert digest.counts["new"] == 2
    assert digest.counts["exists"] == 1
    assert text.index("High overlap") < text.index("Low overlap")
    assert "score 2003" in text
    assert "overlap 2" in text
    assert "hop 1 refs" in text
    assert "shares 2 references" in text
    assert "oa:gold" in text
    assert "## Exists" in text
    assert "Beta" in text
    assert 'paperful snowball apply R1 -C "Inbox/Snowball Hits"' in text
    assert "candidates.jsonl" in text
    assert "snowball digest" in digest.html
    assert "Briefing: 2 new" in digest.html


def test_run_digest_caps_new_detail(tmp_path):
    cfg = _cfg(tmp_path)
    rows = []
    for index in range(26):
        rows.append(
            _row(
                status="new",
                doi=f"10.1000/{index}",
                title=f"Title {index}",
                score=float(26 - index),
                why=f"why-{index}",
                hop=1,
                direction="refs",
                overlap=2,
            )
        )
    _queue(cfg, "R1", rows)
    text = write_run_digest(cfg, "R1").markdown
    assert "why-0" in text
    assert "why-24" in text
    assert "why-25" not in text
    assert "Title 25" in text
    assert "top 25" in text
    assert "needs `-C`" in text


def test_run_digest_flags_deferred(tmp_path):
    cfg = _cfg(tmp_path)
    _queue(cfg, "R2", [_row(status="new", doi="10.1000/c", title="Cee")], deferred=True)
    digest = write_run_digest(cfg, "R2")
    assert digest.counts["deferred"] == 1
    assert "snowball resume R2" in digest.markdown
    assert "OpenAlex stopped early" in digest.markdown


def test_run_digest_missing_queue(tmp_path):
    cfg = _cfg(tmp_path)
    try:
        write_run_digest(cfg, "missing")
    except SnowballError as exc:
        assert exc.code == 1
        assert "missing" in str(exc)
    else:
        raise AssertionError("expected SnowballError")


def test_watch_digest_uses_last_run_queue(tmp_path):
    cfg = _cfg(tmp_path)
    _profile(cfg, target_collection="Inbox/Frontier")
    from paperful.snowball.watch import save_watch

    dest = save_watch(cfg, "bbnj", "keyword-scout").parent
    new = _row(
        status="new",
        doi="10.1000/watch",
        title="Watch hit",
        score=9,
        why="keyword",
        overlap=1,
    )
    exists = _row(status="exists", doi="10.1000/old", title="Already owned")
    _queue(cfg, "R9", [exists, new])
    (dest / "inbox.jsonl").write_text(
        json.dumps(new.to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    watch = json.loads((dest / "watch.json").read_text(encoding="utf-8"))
    watch["baseline_at"] = "2026-01-01T00:00:00Z"
    watch["last_run_id"] = "R9"
    (dest / "watch.json").write_text(json.dumps(watch) + "\n", encoding="utf-8")
    summary = json.loads((cfg.state_dir / "snowball" / "R9" / "summary.json").read_text())
    summary["already_seen"] = 4
    (cfg.state_dir / "snowball" / "R9" / "summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8"
    )
    digest = write_watch_digest(cfg, "bbnj")
    text = digest.markdown
    assert digest.path == dest / "digest.md"
    assert "Already owned" in text
    assert "Watch hit" in text
    assert "inbox.jsonl" in text
    assert "pending 1" in text
    assert "Last run `R9`" in text
    assert "Already seen 4" in text
    assert "paperful snowball apply R9 -C Inbox/Frontier" in text
    assert digest.counts["exists"] == 1
    assert digest.counts["inbox"] == 1


def test_watch_digest_empty_baseline(tmp_path):
    cfg = _cfg(tmp_path)
    _profile(cfg)
    from paperful.snowball.watch import save_watch

    dest = save_watch(cfg, "bbnj", "keyword-scout").parent
    _queue(cfg, "R0", [])
    watch = json.loads((dest / "watch.json").read_text(encoding="utf-8"))
    watch["baseline_at"] = "2026-01-01T00:00:00Z"
    watch["last_run_id"] = "R0"
    (dest / "watch.json").write_text(json.dumps(watch) + "\n", encoding="utf-8")
    digest = write_watch_digest(cfg, "bbnj")
    assert "inbox is empty" in digest.markdown
    assert digest.counts["new"] == 0
    assert digest.counts["inbox"] == 0


def test_watch_digest_before_baseline(tmp_path):
    cfg = _cfg(tmp_path)
    _profile(cfg)
    from paperful.snowball.watch import save_watch

    save_watch(cfg, "bbnj", "keyword-scout")
    digest = write_watch_digest(cfg, "bbnj")
    assert "No baseline yet" in digest.markdown
    assert "watch run bbnj" in digest.markdown


def test_run_digest_includes_version_and_grey_stamp(tmp_path):
    cfg = _cfg(tmp_path)
    row = _row(status="version", doi="10.1000/v", title="Next edition", why="version of seed")
    row.provenance["lane"] = "grey:author_site"
    _queue(cfg, "R1", [row])
    text = write_run_digest(cfg, "R1").markdown
    assert "## Version" in text
    assert "Next edition" in text
    assert "grey:author_site" in text
    assert digest_has_no_exists(text)


def digest_has_no_exists(text: str) -> bool:
    return "## Exists" in text and "\nNone.\n" in text.split("## Exists", 1)[1].split("##", 1)[0]


def test_watch_digest_profile_collection_beats_config(tmp_path):
    cfg = _cfg(tmp_path, more='target_collection = "Inbox/FromConfig"\n')
    _profile(cfg, target_collection="Inbox/FromProfile")
    from paperful.snowball.watch import save_watch

    dest = save_watch(cfg, "bbnj", "keyword-scout").parent
    _queue(cfg, "R3", [_row(status="new", doi="10.1000/n", title="New")])
    watch = json.loads((dest / "watch.json").read_text(encoding="utf-8"))
    watch["baseline_at"] = "2026-01-01T00:00:00Z"
    watch["last_run_id"] = "R3"
    (dest / "watch.json").write_text(json.dumps(watch) + "\n", encoding="utf-8")
    text = write_watch_digest(cfg, "bbnj").markdown
    assert "paperful snowball apply R3 -C Inbox/FromProfile" in text
    assert "Inbox/FromConfig" not in text


def test_watch_digest_missing_last_run_queue(tmp_path):
    cfg = _cfg(tmp_path)
    _profile(cfg)
    from paperful.snowball.watch import save_watch

    dest = save_watch(cfg, "bbnj", "keyword-scout").parent
    watch = json.loads((dest / "watch.json").read_text(encoding="utf-8"))
    watch["last_run_id"] = "gone"
    (dest / "watch.json").write_text(json.dumps(watch) + "\n", encoding="utf-8")
    try:
        write_watch_digest(cfg, "bbnj")
    except SnowballError as exc:
        assert exc.code == 1
        assert "gone" in str(exc)
    else:
        raise AssertionError("expected SnowballError")


def test_watch_digest_deferred_points_at_resume(tmp_path):
    cfg = _cfg(tmp_path)
    _profile(cfg)
    from paperful.snowball.watch import save_watch

    dest = save_watch(cfg, "bbnj", "keyword-scout").parent
    _queue(cfg, "R4", [_row(status="new", doi="10.1000/d", title="Held")], deferred=True)
    summary = json.loads((cfg.state_dir / "snowball" / "R4" / "summary.json").read_text())
    summary["already_seen"] = 2
    (cfg.state_dir / "snowball" / "R4" / "summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8"
    )
    watch = json.loads((dest / "watch.json").read_text(encoding="utf-8"))
    watch["baseline_at"] = "2026-01-01T00:00:00Z"
    watch["last_run_id"] = "R4"
    (dest / "watch.json").write_text(json.dumps(watch) + "\n", encoding="utf-8")
    digest = write_watch_digest(cfg, "bbnj")
    assert digest.counts["deferred"] == 1
    assert "snowball resume R4" in digest.markdown
    assert "Already seen 2" in digest.markdown
    assert "## Exists" in digest.markdown
    exists = digest.markdown.split("## Exists", 1)[1].split("##", 1)[0]
    assert "None." in exists


def test_cli_digest_missing_queue_exits_1(tmp_path):
    cfg = _cfg(tmp_path)
    runner = CliRunner()
    res = runner.invoke(
        app,
        ["snowball", "digest", "--run-id", "missing", "-c", str(cfg.config_path)],
    )
    assert res.exit_code == 1, res.output
    assert "missing" in res.output


def test_cli_digest_writes_markdown(tmp_path):
    cfg = _cfg(tmp_path, more='target_collection = "Inbox/Snowball"\n')
    _profile(cfg)
    from paperful.snowball.watch import save_watch

    dest = save_watch(cfg, "bbnj", "keyword-scout").parent
    _queue(cfg, "R1", [_row(status="new", doi="10.1000/a", title="Alpha", score=2, why="hit")])
    watch = json.loads((dest / "watch.json").read_text(encoding="utf-8"))
    watch["last_run_id"] = "R1"
    watch["baseline_at"] = "2026-01-01T00:00:00Z"
    (dest / "watch.json").write_text(json.dumps(watch) + "\n", encoding="utf-8")
    runner = CliRunner()
    config = str(tmp_path / "config.toml")
    run = runner.invoke(app, ["snowball", "digest", "--run-id", "R1", "-c", config])
    assert run.exit_code == 0, run.output
    assert "new 1" in run.output
    assert (cfg.state_dir / "snowball" / "R1" / "digest.md").is_file()
    watch_res = runner.invoke(app, ["snowball", "watch", "digest", "bbnj", "-c", config])
    assert watch_res.exit_code == 0, watch_res.output
    assert "inbox 0" in watch_res.output
    assert (dest / "digest.md").is_file()
    help_res = runner.invoke(app, ["snowball", "watch", "run", "--help"])
    assert help_res.exit_code == 0, help_res.output
    plain_help = re.sub(r"\x1b\[[0-9;]*m", "", help_res.output)
    assert "--digest" in plain_help
