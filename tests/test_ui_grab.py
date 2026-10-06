"""Preview and Grab review tokens (wave 4)."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.store import Manifest, Record, STATUS_OK
from paperful.ui import commands, jobs
from paperful.ui.pages import scope_fingerprint


class _Item:
    def __init__(self, key: str, doi: str):
        self.key = key
        self.title = key
        self.doi = doi
        self.has_pdf = False
        self.arxiv_id = None
        self.url = ""


def test_grab_stale_token_and_attach_match_only(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    items = [_Item("K1", "10.1/a"), _Item("K2", "10.2/b")]
    manifest = Manifest(cfg.manifest_path)
    manifest.write(
        Record(
            itemKey="K1",
            status=STATUS_OK,
            doi="10.1/a",
            pdf_doi="10.1/a",
            source="unpaywall",
            path="a.pdf",
        )
    )
    fp = scope_fingerprint(items, manifest)

    attached: list[str] = []

    def fake_run(*args, **kwargs):
        return None

    def fake_attach(cfg, keys=None):
        attached.extend(keys or [])

    jobs.run_fetch_fn = fake_run
    jobs.attach_fn = fake_attach
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))

    token = commands.create_review_token(
        cfg,
        verb="preview_run",
        collection="BBNJ",
        preset="oa",
        keys=["K1", "K2"],
        fingerprint=fp,
        command_id="abc",
    )
    ok, _ = jobs.grab_run(cfg, token=token, attach_verified=True)
    assert ok
    assert attached == ["K1"]

    ok2, msg2 = jobs.grab_run(cfg, token=token, attach_verified=True)
    assert not ok2
    assert "token" in msg2.lower()

    token2 = commands.create_review_token(
        cfg,
        verb="preview_run",
        collection="BBNJ",
        preset="oa",
        keys=["K1"],
        fingerprint="wrong",
        command_id="def",
    )
    ok3, msg3 = jobs.grab_run(cfg, token=token2, attach_verified=True)
    assert not ok3
    jobs.run_fetch_fn = None
    jobs.attach_fn = None
