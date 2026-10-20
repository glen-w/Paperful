"""Alert loop / keepup job tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from paperful.config import Config
from paperful.keepup import (
    Source,
    apply_job,
    days_until_due,
    dismiss,
    load_applied,
    load_inbox,
    load_job,
    load_muted,
    load_seen,
    run_job,
    save_job,
    write_digest,
)
from paperful.keepup_cites import _why_line, probe_cites
from paperful.snowball.candidate import Candidate


def _cfg(tmp_path: Path) -> Config:
    cfg = Config(
        email="test@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        snowball_enabled=True,
        keepup_interval_days=7,
    )
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def _console() -> Console:
    return Console(file=StringIO(), highlight=False, width=120)


def test_days_until_due_respects_interval():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert days_until_due(recent, 7) >= 4
    old = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert days_until_due(old, 7) == 0
    assert days_until_due(None, 7) == 0
    assert days_until_due(recent, 0) == 0


def test_save_show_dismiss(tmp_path: Path):
    cfg = _cfg(tmp_path)
    path = save_job(
        cfg,
        "field",
        collection="Ocean/BBNJ",
        sources=[Source(type="cites")],
        interval_days=7,
    )
    assert path.is_file()
    body = load_job(cfg, "field")
    assert body["collection"] == "Ocean/BBNJ"
    assert body["sources"] == [{"type": "cites", "name": ""}]
    key = dismiss(cfg, "field", doi="10.1000/x")
    assert key == "doi:10.1000/x"
    assert "doi:10.1000/x" in load_muted(cfg, "field")


def test_interval_skip_and_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _cfg(tmp_path)
    save_job(
        cfg,
        "field",
        collection="Ocean/BBNJ",
        sources=[Source(type="cites")],
        interval_days=7,
    )
    body = load_job(cfg, "field")
    body["baseline_at"] = "2020-01-01T00:00:00Z"
    body["last_run_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (cfg.state_dir / "keepup" / "field" / "job.json").write_text(
        __import__("json").dumps(body, indent=2) + "\n", encoding="utf-8"
    )

    def boom(*_a, **_k):
        raise AssertionError("should not poll when skipped")

    monkeypatch.setattr("paperful.keepup._poll_cites", boom)
    skipped = run_job(cfg, "field", console=_console(), force=False)
    assert skipped.skipped is True
    assert skipped.days_left >= 1


def test_cites_why_line():
    assert _why_line(1, ["Alpha"]) == "cites 1 of your paper (Alpha)"
    assert _why_line(2, ["A", "B"]) == "cites 2 of your papers (A; B)"


def test_probe_cites_overlap(tmp_path: Path):
    cfg = _cfg(tmp_path)

    class _Item:
        def __init__(self, doi: str):
            self.doi = doi

    class _Lib:
        def resolve_collection(self, _path: str):
            return "root"

        def subtree_keys(self, _root):
            return ["A", "B"]

        def items_in_scope(self, _keys):
            return [_Item("10.1000/a"), _Item("10.1000/b")]

    class _Client:
        def works_by_dois(self, dois, select=""):
            return [
                {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1000/a", "display_name": "Seed A"},
                {"id": "https://openalex.org/W2", "doi": "https://doi.org/10.1000/b", "display_name": "Seed B"},
            ]

        def works_citing(self, openalex_id, *, limit, from_created_date=None, sort=None):
            return [
                {
                    "id": "https://openalex.org/W9",
                    "doi": "https://doi.org/10.1000/citer",
                    "display_name": "Citer",
                    "publication_year": 2025,
                    "cited_by_count": 3,
                    "authorships": [],
                    "primary_location": {},
                    "open_access": {},
                    "type": "article",
                    "language": "en",
                }
            ]

    rows, polled = probe_cites(
        cfg,
        collection="Ocean/BBNJ",
        run_id="keepup:field",
        from_created_date="2024-01-01",
        per_seed_limit=10,
        max_candidates=50,
        muted=set(),
        seen=set(),
        console=_console(),
        client=_Client(),
        lookup=lambda *a, **k: None,
        backend=_Lib(),
    )
    assert polled == 2
    assert len(rows) == 1
    assert rows[0].ids.get("doi") == "10.1000/citer"
    assert rows[0].biblio.get("overlap") == 2
    assert "cites 2 of your papers" in rows[0].why


def test_keepup_apply_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _cfg(tmp_path)
    save_job(
        cfg,
        "field",
        collection="Ocean/BBNJ",
        sources=[Source(type="cites")],
    )
    row = Candidate(
        run_id="keepup:field",
        seed={"type": "collection", "value": "Ocean/BBNJ"},
        hop=1,
        direction="cites",
        ids={"doi": "10.1000/new", "openalex": "W9"},
        biblio={"title": "New citer", "year": 2025, "cited_by_count": 1},
        why="cites 1 of your papers",
        status="new",
        provenance={"backend": "openalex"},
        gate="dry-run",
        keep=True,
        score=1001,
    )
    from paperful.keepup import append_inbox

    append_inbox(cfg, "field", [row])
    dry = apply_job(
        cfg,
        "field",
        console=_console(),
        apply=False,
        lookup=lambda *a, **k: None,
        backend=object(),
    )
    assert dry.dry_run is True

    created = []

    def fake_create(backend, rows, collection, **kwargs):
        created.extend(rows)
        assert collection == "Ocean/BBNJ"
        return [], {"created": len(rows), "skipped_exists": 0, "failed": 0}

    monkeypatch.setattr("paperful.snowball.ingest.create_new", fake_create)
    written = apply_job(
        cfg,
        "field",
        console=_console(),
        apply=True,
        lookup=lambda *a, **k: None,
        backend=object(),
    )
    assert written.created == 1
    assert written.ingested_path and written.ingested_path.is_file()
    assert "doi:10.1000/new" in load_applied(cfg, "field")
    again = apply_job(
        cfg,
        "field",
        console=_console(),
        apply=True,
        lookup=lambda *a, **k: None,
        backend=object(),
    )
    assert again.already_applied == 1
    assert again.created == 0


def test_write_digest(tmp_path: Path):
    cfg = _cfg(tmp_path)
    save_job(
        cfg,
        "field",
        collection="Ocean/BBNJ",
        sources=[Source(type="cites")],
    )
    path = write_digest(cfg, "field")
    text = path.read_text(encoding="utf-8")
    assert "Keepup digest field" in text
    assert "keepup apply" in text


def test_cli_keepup_help():
    from typer.testing import CliRunner

    from paperful.cli import app

    runner = CliRunner()
    res = runner.invoke(app, ["keepup", "--help"])
    assert res.exit_code == 0, res.stdout
    assert "run" in res.stdout
    assert "apply" in res.stdout
    help_all = runner.invoke(app, ["--help"])
    assert "keepup" in help_all.stdout


def test_keepup_cites_baseline_proposes_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cfg = _cfg(tmp_path)
    save_job(
        cfg,
        "field",
        collection="Ocean/BBNJ",
        sources=[Source(type="cites")],
        interval_days=0,
    )

    def fake_baseline(*_a, **_k):
        return {"doi:10.1000/old"}

    monkeypatch.setattr(
        "paperful.keepup_cites.baseline_identities", fake_baseline
    )
    result = run_job(cfg, "field", console=_console(), force=True)
    assert result.baseline is True
    assert result.proposed == 0
    assert "doi:10.1000/old" in load_seen(cfg, "field")
    assert load_inbox(cfg, "field") == []


def test_keepup_config_interval(tmp_path: Path):
    from paperful.config import _from_dict

    cfg = _from_dict({"keepup": {"interval_days": 3}}, tmp_path / "config.toml")
    assert cfg.keepup_interval_days == 3


def _cand(doi: str, *, title: str = "Work") -> Candidate:
    return Candidate(
        run_id="keepup:field",
        seed={"type": "collection", "value": "Ocean/BBNJ"},
        hop=1,
        direction="cites",
        ids={"doi": doi, "openalex": "W" + doi[-1]},
        biblio={"title": title, "year": 2025},
        why="test",
        status="new",
        provenance={"backend": "openalex"},
        gate="dry-run",
        keep=True,
        score=1,
    )


def _past_baseline(cfg: Config, name: str) -> None:
    body = load_job(cfg, name)
    body["baseline_at"] = "2020-01-01T00:00:00Z"
    body["last_run_at"] = "2020-01-02T00:00:00Z"
    (cfg.state_dir / "keepup" / name / "job.json").write_text(
        __import__("json").dumps(body, indent=2) + "\n", encoding="utf-8"
    )


def test_poll_watch_and_authorwatch_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from paperful import keepup

    cfg = _cfg(tmp_path)
    watch_row = _cand("10.1000/w", title="Watch hit")
    aw_row = _cand("10.1000/a", title="Author hit")
    already = _cand("10.1000/skip")

    class _WatchRes:
        proposed = 1
        baseline = True

    monkeypatch.setattr(
        "paperful.snowball.watch.run_watch", lambda *_a, **_k: _WatchRes()
    )
    monkeypatch.setattr("paperful.snowball.watch.load_applied", lambda *_a, **_k: set())
    monkeypatch.setattr(
        "paperful.snowball.watch.load_inbox", lambda *_a, **_k: [watch_row]
    )
    rows, note = keepup._poll_watch(
        cfg,
        Source(type="watch", name="bbnj"),
        console=_console(),
        client=None,
        backend=None,
        lookup=None,
    )
    assert [row.ids["doi"] for row in rows] == ["10.1000/w"]
    assert "watch bbnj: proposed 1" in note
    assert "(baseline)" in note

    class _AwRes:
        proposed = 2
        baseline = False

    monkeypatch.setattr("paperful.authorwatch.run_list", lambda *_a, **_k: _AwRes())
    monkeypatch.setattr(
        "paperful.authorwatch.load_applied", lambda *_a, **_k: {"doi:10.1000/skip"}
    )
    monkeypatch.setattr(
        "paperful.authorwatch.load_inbox",
        lambda *_a, **_k: [aw_row, already],
    )
    rows, note = keepup._poll_authorwatch(
        cfg,
        Source(type="authorwatch", name="people"),
        console=_console(),
        client=None,
        backend=None,
        lookup=None,
    )
    assert [row.ids["doi"] for row in rows] == ["10.1000/a"]
    assert "authorwatch people: proposed 2" in note
    assert "(baseline)" not in note


def test_run_job_merges_watch_and_cites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cfg = _cfg(tmp_path)
    save_job(
        cfg,
        "field",
        collection="Ocean/BBNJ",
        sources=[Source(type="watch", name="bbnj"), Source(type="cites")],
        interval_days=0,
    )
    _past_baseline(cfg, "field")
    watch_row = _cand("10.1000/w")
    cite_row = _cand("10.1000/c")
    dup = _cand("10.1000/w")

    monkeypatch.setattr(
        "paperful.keepup._poll_watch",
        lambda *_a, **_k: ([watch_row], "watch bbnj: proposed 1"),
    )
    monkeypatch.setattr(
        "paperful.keepup._poll_cites",
        lambda *_a, **_k: ([cite_row, dup], "cites: proposed 2 · seeds 1", set()),
    )
    result = run_job(cfg, "field", console=_console(), force=True)
    assert result.skipped is False
    assert result.baseline is False
    assert result.proposed == 2
    dois = {row.ids.get("doi") for row in load_inbox(cfg, "field")}
    assert dois == {"10.1000/w", "10.1000/c"}
    assert any("watch bbnj" in note for note in result.source_notes)
    assert any(note.startswith("cites:") for note in result.source_notes)


def test_keepup_apply_marks_nested_watch_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from paperful.keepup import append_inbox
    from paperful.snowball import watch as sw

    cfg = _cfg(tmp_path)
    save_job(
        cfg,
        "field",
        collection="Ocean/BBNJ",
        sources=[Source(type="watch", name="bbnj")],
    )
    append_inbox(cfg, "field", [_cand("10.1000/new")])

    def fake_create(backend, rows, collection, **kwargs):
        assert collection == "Ocean/BBNJ"
        return [], {"created": len(rows), "skipped_exists": 0, "failed": 0}

    monkeypatch.setattr("paperful.snowball.ingest.create_new", fake_create)
    written = apply_job(
        cfg,
        "field",
        console=_console(),
        apply=True,
        lookup=lambda *a, **k: None,
        backend=object(),
    )
    assert written.created == 1
    assert "doi:10.1000/new" in load_applied(cfg, "field")
    assert "doi:10.1000/new" in sw.load_applied(cfg, "bbnj")


def test_cli_keepup_save(tmp_path: Path):
    from typer.testing import CliRunner

    from paperful.cli import app

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n',
        encoding="utf-8",
    )
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "keepup",
            "save",
            "field",
            "-C",
            "Ocean/BBNJ",
            "--watch",
            "bbnj",
            "--source",
            "cites",
            "-c",
            str(cfg_file),
        ],
    )
    assert res.exit_code == 0, res.stdout
    body = __import__("json").loads(
        (tmp_path / "state" / "keepup" / "field" / "job.json").read_text(
            encoding="utf-8"
        )
    )
    assert body["collection"] == "Ocean/BBNJ"
    kinds = {src["type"] for src in body["sources"]}
    assert kinds == {"watch", "cites"}


def test_discover_watch_apply_fingerprint(tmp_path: Path):
    from paperful.ui import jobs
    from paperful.snowball.watch import append_inbox, watch_dir

    cfg = _cfg(tmp_path)
    dest = watch_dir(cfg, "topic-a")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "watch.json").write_text(
        '{"schema":"paperful.snowball.watch.v1","profile":"scout"}\n',
        encoding="utf-8",
    )
    (dest / "inbox.jsonl").write_text("", encoding="utf-8")
    row = Candidate(
        run_id="watch:topic-a",
        seed={"type": "query", "value": "bbnj"},
        hop=1,
        direction="refs",
        ids={"doi": "10.1000/w", "openalex": "W1"},
        biblio={"title": "W", "year": 2024},
        why="watch",
        status="new",
        provenance={},
        gate="dry-run",
        keep=True,
    )
    append_inbox(cfg, "topic-a", [row])
    fp1 = jobs._watch_apply_fingerprint(cfg, "topic-a", "Ocean/BBNJ")
    fp2 = jobs._watch_apply_fingerprint(cfg, "topic-a", "Ocean/BBNJ")
    assert fp1 == fp2
    assert len(fp1) == 64
