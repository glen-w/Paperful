"""keepup job ledger: validation, listing, deletion, status output."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from rich.console import Console

from paperful.config import Config
from paperful.keepup import (
    KeepupError,
    Source,
    days_until_due,
    delete_job,
    job_dir,
    list_jobs,
    load_job,
    save_job,
    show_job,
)


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state", keepup_interval_days=5)
    c.state_dir.mkdir(parents=True)
    return c


def _stamp(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _show(cfg, name) -> str:
    buf = StringIO()
    show_job(cfg, name, console=Console(file=buf, highlight=False, width=140))
    return buf.getvalue()


@pytest.mark.parametrize("bad", ["", "../x", "a/b", ".hidden", "-lead", "has space", "tab\t"])
def test_job_names_are_validated_before_touching_disk(cfg, bad):
    with pytest.raises(KeepupError, match="Invalid keepup name"):
        job_dir(cfg, bad)
    with pytest.raises(KeepupError, match="Invalid keepup name"):
        save_job(cfg, bad, collection="C", sources=[Source("cites")])
    assert not (cfg.state_dir / "keepup").exists()


def test_save_job_validation(cfg):
    with pytest.raises(KeepupError, match="needs -C"):
        save_job(cfg, "j", collection="  ", sources=[Source("cites")])
    with pytest.raises(KeepupError, match="at least one source"):
        save_job(cfg, "j", collection="C", sources=[])
    with pytest.raises(KeepupError, match="Unknown source type"):
        save_job(cfg, "j", collection="C", sources=[Source("rss")])
    with pytest.raises(KeepupError, match="watch source needs a name"):
        save_job(cfg, "j", collection="C", sources=[Source("watch", "  ")])
    with pytest.raises(KeepupError, match="authorwatch source needs a name"):
        save_job(cfg, "j", collection="C", sources=[Source("authorwatch")])
    with pytest.raises(KeepupError, match="interval_days must be >= 0"):
        save_job(cfg, "j", collection="C", sources=[Source("cites")], interval_days=-1)
    assert list_jobs(cfg) == []


def test_save_job_normalises_and_keeps_state_on_resave(cfg):
    path = save_job(
        cfg, "j", collection=" Ocean ",
        sources=[Source(" CITES "), Source("Watch", " w1 ")],
        per_seed_limit=0, max_candidates=-5,
    )
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["collection"] == "Ocean" and body["interval_days"] == 5  # config default
    assert body["per_seed_limit"] == 1 and body["max_candidates"] == 0
    assert body["sources"] == [{"type": "cites", "name": ""}, {"type": "watch", "name": "w1"}]

    body["baseline_at"], body["last_run_at"] = "2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z"
    path.write_text(json.dumps(body), encoding="utf-8")
    (job_dir(cfg, "j") / "seen.json").write_text(json.dumps({"identities": ["doi:x"]}), encoding="utf-8")
    save_job(cfg, "j", collection="Ocean", sources=[Source("cites")], interval_days=0)
    again = load_job(cfg, "j")
    assert again["baseline_at"] == "2025-01-01T00:00:00Z" and again["last_run_at"] == "2025-02-01T00:00:00Z"
    assert again["interval_days"] == 0 and again["sources"] == [{"type": "cites", "name": ""}]
    assert json.loads((job_dir(cfg, "j") / "seen.json").read_text())["identities"] == ["doi:x"]


def test_save_job_recovers_from_a_corrupt_non_object_job_file(cfg):
    save_job(cfg, "j", collection="C", sources=[Source("cites")])
    (job_dir(cfg, "j") / "job.json").write_text("[1, 2, 3]", encoding="utf-8")
    save_job(cfg, "j", collection="C2", sources=[Source("cites")])
    assert load_job(cfg, "j")["collection"] == "C2"


def test_list_and_delete_jobs(cfg):
    assert list_jobs(cfg) == []
    save_job(cfg, "b-job", collection="C", sources=[Source("cites")])
    save_job(cfg, "a-job", collection="C", sources=[Source("cites")])
    (cfg.state_dir / "keepup" / "stray.txt").write_text("x", encoding="utf-8")
    (cfg.state_dir / "keepup" / "no-job-file").mkdir()
    assert list_jobs(cfg) == ["a-job", "b-job"]
    removed = delete_job(cfg, "a-job")
    assert not removed.exists() and list_jobs(cfg) == ["b-job"]
    with pytest.raises(KeepupError, match="Unknown keepup job"):
        delete_job(cfg, "a-job")


def test_load_job_unknown(cfg):
    with pytest.raises(KeepupError):
        load_job(cfg, "ghost")


def test_show_job_before_any_run(cfg):
    save_job(cfg, "j", collection="Ocean", sources=[Source("cites"), Source("watch", "w1")])
    out = _show(cfg, "j")
    assert "keepup j" in out and "collection · Ocean" in out and "interval_days · 5" in out
    assert "baseline · not yet" in out and "last run" not in out
    assert "source · cites" in out and "source · watch w1" in out
    assert "inbox pending · 0" in out


def test_show_job_after_run_reports_due_state(cfg):
    save_job(cfg, "j", collection="Ocean", sources=[Source("cites")], interval_days=7)
    path = job_dir(cfg, "j") / "job.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body.update(baseline_at="2025-01-01T00:00:00Z", last_run_at=_stamp(1))
    path.write_text(json.dumps(body), encoding="utf-8")
    out = _show(cfg, "j")
    assert "baseline · 2025-01-01T00:00:00Z" in out
    assert "next due · in" in out and "(or --force)" in out

    body["last_run_at"] = _stamp(30)
    path.write_text(json.dumps(body), encoding="utf-8")
    assert "next due · now" in _show(cfg, "j")


@pytest.mark.parametrize(
    ("last", "interval", "due"),
    [
        (None, 7, True),
        ("", 7, True),
        ("garbage", 7, True),
        (_stamp(100), 0, True),
        (_stamp(100), -3, True),
        (_stamp(0.01), 7, False),
    ],
)
def test_days_until_due_edge_inputs(last, interval, due):
    assert (days_until_due(last, interval) == 0) is due


def test_days_until_due_accepts_naive_timestamps_and_floors_to_one_day():
    naive = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    assert days_until_due(naive, 7) >= 6
    almost = (datetime.now(timezone.utc) - timedelta(days=1) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert days_until_due(almost, 1) == 1  # never reports 0 days while still not due


def test_source_from_dict_normalises():
    assert Source.from_dict({"type": " Cites ", "name": " x "}) == Source("cites", "x")
    assert Source.from_dict({}) == Source("", "")
