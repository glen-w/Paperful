"""1.7 reliability lane: atomic writes survive crashes; torn state reads fail
closed; cross-process locks actually exclude."""

from __future__ import annotations

import pytest

from paperful import fsio
from paperful.store import load_json


def test_atomic_write_crash_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "state" / "ledger.json"
    fsio.atomic_write_json(path, {"version": 1})

    def boom(src, dst):
        raise OSError("simulated crash mid-replace")

    monkeypatch.setattr(fsio.os, "replace", boom)
    with pytest.raises(OSError):
        fsio.atomic_write_json(path, {"version": 2})
    monkeypatch.undo()
    # Original payload intact, no orphaned .part files left behind.
    assert load_json(path) == {"version": 1}
    assert not list(path.parent.glob("*.part"))


def test_atomic_write_text_crash_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "digest.md"
    fsio.atomic_write_text(path, "first")
    monkeypatch.setattr(
        fsio.os, "replace", lambda s, d: (_ for _ in ()).throw(OSError("boom"))
    )
    with pytest.raises(OSError):
        fsio.atomic_write_text(path, "second")
    monkeypatch.undo()
    assert path.read_text(encoding="utf-8") == "first"
    assert not list(tmp_path.glob("*.part"))


def test_torn_json_loads_as_none(tmp_path):
    path = tmp_path / "torn.json"
    path.write_text('{"version": 1, "items": [', encoding="utf-8")
    assert load_json(path) is None


def test_file_lock_excludes_and_releases(tmp_path):
    from filelock import Timeout

    with fsio.file_lock(tmp_path, "job", timeout=1.0):
        with pytest.raises(Timeout):
            with fsio.file_lock(tmp_path, "job", timeout=0.2):
                pass
    # Released: a fresh acquisition succeeds immediately.
    with fsio.file_lock(tmp_path, "job", timeout=1.0):
        pass
    assert (tmp_path / ".locks" / "job.lock").is_file()


def test_watch_ledgers_roundtrip_after_atomic_conversion(cfg, tmp_path):
    """keepup save/load still reads what the atomic writer wrote."""
    from paperful.keepup import Source, load_job, save_job

    path = save_job(
        cfg,
        "wave17",
        collection="ocean",
        sources=[Source(type="watch", name="w1")],
        interval_days=7,
        per_seed_limit=5,
        max_candidates=10,
    )
    assert path.is_file()
    body = load_job(cfg, "wave17")
    assert body["collection"] == "ocean"
    assert not list(path.parent.glob("*.part"))
