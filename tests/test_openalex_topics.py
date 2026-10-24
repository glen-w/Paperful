"""OpenAlex Oct 2026 topic housekeeping: run stamp, watch rebaseline, doctor, scoring fixture."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from paperful.config import Config
from paperful.snowball.candidate import Candidate
from paperful.snowball.openalex import chosen_keywords
from paperful.snowball.openalex_epoch import (
    EPOCH_AFTER,
    EPOCH_BEFORE,
    openalex_stamp,
    predates_migration,
)
from paperful.snowball.rank import apply_overlap
from paperful.snowball.watch import (
    list_watch_names,
    load_watch,
    rebaseline_watch,
    save_watch,
    watch_dir,
)

FIXTURE = Path(__file__).parent / "fixtures" / "openalex_topics" / "keyword_scoring_before_after.json"


# ---- run stamp ---------------------------------------------------------------------


def test_openalex_stamp_marks_the_epoch():
    assert openalex_stamp(date(2026, 10, 13)) == {
        "openalex_run_date": "2026-10-13",
        "openalex_topic_epoch": EPOCH_BEFORE,
    }
    assert openalex_stamp(date(2026, 10, 14))["openalex_topic_epoch"] == EPOCH_AFTER
    assert openalex_stamp()["openalex_run_date"]  # today, always present


def test_predates_migration_handles_timestamps_and_junk():
    assert predates_migration("2026-09-01T10:00:00Z")
    assert not predates_migration("2026-10-14T00:00:00Z")
    assert not predates_migration("")
    assert not predates_migration("not a date")
    assert not predates_migration(None)


# ---- watch rebaseline --------------------------------------------------------------


def _cfg(tmp_path) -> Config:
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.fixture
def cfg(tmp_path) -> Config:
    return _cfg(tmp_path)


def _profile_loader(monkeypatch, profiles: dict[str, dict]):
    monkeypatch.setattr(
        "paperful.snowball.watch.load_profile", lambda _cfg, name: dict(profiles[name])
    )
    monkeypatch.setattr("paperful.snowball.watch.check_profile_name", lambda _n: None)


def test_rebaseline_dry_run_then_apply_once(cfg, monkeypatch):
    _profile_loader(monkeypatch, {"kw": {"kind": "snowball", "mode": "search"}})
    save_watch(cfg, "bbnj", "kw")
    path = watch_dir(cfg, "bbnj") / "watch.json"
    body = load_watch(cfg, "bbnj")
    body["baseline_at"] = "2026-08-01T00:00:00Z"
    body["last_run_at"] = "2026-09-01T00:00:00Z"
    path.write_text(json.dumps(body), encoding="utf-8")
    (watch_dir(cfg, "bbnj") / "seen.json").write_text(
        json.dumps({"identities": ["doi:10.1/a"]}), encoding="utf-8"
    )
    (watch_dir(cfg, "bbnj") / "inbox.jsonl").write_text('{"x": 1}\n', encoding="utf-8")

    dry = rebaseline_watch(cfg, "bbnj")
    assert dry["action"] == "rebaseline" and dry["applied"] is False
    assert load_watch(cfg, "bbnj")["baseline_at"] == "2026-08-01T00:00:00Z"

    done = rebaseline_watch(cfg, "bbnj", apply=True)
    assert done["applied"] is True
    after = load_watch(cfg, "bbnj")
    assert after["baseline_at"] is None
    assert after["rebaselined_for"] == EPOCH_AFTER
    assert after["last_run_at"] == "2026-09-01T00:00:00Z"
    # seen and inbox are left alone: the next run absorbs, it does not forget.
    assert json.loads((watch_dir(cfg, "bbnj") / "seen.json").read_text())["identities"] == ["doi:10.1/a"]
    assert (watch_dir(cfg, "bbnj") / "inbox.jsonl").read_text() == '{"x": 1}\n'

    # Once only.
    again = rebaseline_watch(cfg, "bbnj", apply=True)
    assert again["action"] == "skip"
    # A baseline reset again would need --force; a missing baseline is the first run anyway.
    assert rebaseline_watch(cfg, "bbnj", force=True)["reason"].startswith("no baseline")


def test_rebaseline_skips_new_baselines_and_non_keyword_watches(cfg, monkeypatch):
    _profile_loader(
        monkeypatch,
        {
            "kw": {"kind": "snowball", "mode": "search"},
            "refs": {"kind": "snowball", "mode": "doi", "direction": "refs"},
        },
    )
    save_watch(cfg, "fresh", "kw")
    save_watch(cfg, "refsonly", "refs")
    for name, when in (("fresh", "2026-11-02T00:00:00Z"), ("refsonly", "2026-01-01T00:00:00Z")):
        path = watch_dir(cfg, name) / "watch.json"
        body = load_watch(cfg, name)
        body["baseline_at"] = when
        path.write_text(json.dumps(body), encoding="utf-8")
    assert "after the topic change" in rebaseline_watch(cfg, "fresh", apply=True)["reason"]
    assert rebaseline_watch(cfg, "refsonly", apply=True)["reason"] == "not keyword-based"
    assert load_watch(cfg, "fresh")["baseline_at"] == "2026-11-02T00:00:00Z"
    assert list_watch_names(cfg) == ["fresh", "refsonly"]


def test_rebaseline_cli_dry_run_and_apply(cfg, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from paperful import cli

    _profile_loader(monkeypatch, {"kw": {"kind": "snowball", "mode": "search"}})
    save_watch(cfg, "bbnj", "kw")
    path = watch_dir(cfg, "bbnj") / "watch.json"
    body = load_watch(cfg, "bbnj")
    body["baseline_at"] = "2026-05-01T00:00:00Z"
    path.write_text(json.dumps(body), encoding="utf-8")
    conf = tmp_path / "config.toml"
    conf.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        "[snowball]\nenabled = true\n"
    )
    runner = CliRunner()
    res = runner.invoke(cli.app, ["snowball", "watch", "rebaseline", "--all", "-c", str(conf)])
    assert res.exit_code == 0, res.stdout
    assert "would reset" in res.stdout and "Dry run" in res.stdout
    assert load_watch(cfg, "bbnj")["baseline_at"] == "2026-05-01T00:00:00Z"
    res = runner.invoke(
        cli.app, ["snowball", "watch", "rebaseline", "--all", "--apply", "-c", str(conf)]
    )
    assert res.exit_code == 0, res.stdout
    assert load_watch(cfg, "bbnj")["baseline_at"] is None
    bad = runner.invoke(cli.app, ["snowball", "watch", "rebaseline", "-c", str(conf)])
    assert bad.exit_code == 1


# ---- doctor ------------------------------------------------------------------------


def _store_cfg(tmp_path, snapshot_date: str) -> Config:
    cfg = _cfg(tmp_path)
    cfg.openalex_store_backend = "local_duckdb"
    cfg.openalex_store_parquet_glob = "/data/works/*.parquet"
    cfg.openalex_store_snapshot_date = snapshot_date
    return cfg


def test_doctor_warns_when_the_snapshot_predates_the_topic_change(tmp_path):
    from paperful.doctor import _openalex_store_check

    old = _openalex_store_check(_store_cfg(tmp_path, "2026-08-20"))
    assert old.status == "amber"
    assert "reload fully" in old.detail and "2026-08-20" in old.detail


def test_doctor_is_quiet_for_a_current_or_unset_snapshot(tmp_path):
    from paperful.doctor import _openalex_store_check

    current = _openalex_store_check(_store_cfg(tmp_path, "2026-10-20"))
    assert "predates" not in current.detail
    unset = _openalex_store_check(_store_cfg(tmp_path, ""))
    assert "snapshot_date unset" in unset.detail
    assert "predates" not in unset.detail


def test_snapshot_date_is_read_from_config(tmp_path):
    from paperful.config import load_config

    conf = tmp_path / "config.toml"
    conf.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        '[openalex_store]\nbackend = "local_duckdb"\nsnapshot_date = "2026-09-30T12:00"\n'
    )
    assert load_config(conf).openalex_store_snapshot_date == "2026-09-30"


# ---- before / after scoring fixture ------------------------------------------------


def _candidate(work: dict, shared: list[str]) -> Candidate:
    short = work["id"].rsplit("/", 1)[-1]
    return Candidate(
        run_id="r",
        seed={"type": "doi", "value": "10.1/seed"},
        hop=1,
        direction="keywords",
        ids={"openalex": short},
        biblio={"title": work["title"], "cited_by_count": work["cited_by_count"], "keyword_overlap": len(shared)},
        why="",
        status="new",
        provenance={},
        gate="",
    )


@pytest.mark.parametrize("epoch", ["pre-2026-10", "2026-10"])
def test_keyword_scoring_matches_the_frozen_before_after_fixture(epoch):
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data, want = fx["epochs"][epoch], fx["epochs"][epoch]["expected"]
    min_score, limit = fx["min_score"], fx["keyword_limit"]
    seed = chosen_keywords(data["seed"], limit=limit, min_score=min_score)
    assert seed == want["seed_keywords"]
    rows = []
    for work in data["neighbours"]:
        shared = [k for k in chosen_keywords(work, limit=0, min_score=min_score) if k in seed]
        rows.append(_candidate(work, shared))
    apply_overlap(rows)
    by_id = {r.ids["openalex"]: r for r in rows}
    assert {k: v.biblio["overlap"] for k, v in by_id.items()} == want["overlap"]
    assert {k: v.score for k, v in by_id.items()} == want["scores"]
    assert [r.ids["openalex"] for r in sorted(rows, key=lambda r: -r.score)] == want["ranked"]


def test_the_two_epochs_rank_the_same_neighbours_differently():
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    before = fx["epochs"]["pre-2026-10"]["expected"]["ranked"]
    after = fx["epochs"]["2026-10"]["expected"]["ranked"]
    assert before != after and sorted(before) == sorted(after)
