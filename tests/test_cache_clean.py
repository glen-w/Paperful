"""pdf-cache cleanup verb."""

from __future__ import annotations

import hashlib

from paperful.config import Config
from paperful.sync import clean_pdf_cache, run_sync
from tests.test_sync import FakeZotero, PDF


def test_cache_clean_dry_run_and_apply(tmp_path):
    cfg = Config(
        out_dir=tmp_path / "out", state_dir=tmp_path / "state", mirror_pdfs="all"
    )
    zot = FakeZotero()
    zot.put("ITEM0001", title="Paper", collections=["COLA"])
    zot.attach("ITEM0001", "ATT00001")
    run_sync(cfg, zot, pdfs="all")

    cache = cfg.pdf_cache_dir
    cache.mkdir(parents=True, exist_ok=True)
    absorbed = cache / "ITEM0001.pdf"
    absorbed.write_bytes(PDF)
    orphan = cache / "ORPHAN01.pdf"
    orphan.write_bytes(b"%PDF orphan")
    stale = cache / "ITEM0001.pdf"  # already absorbed name; rewrite with wrong md5 after?
    # A second key that has a record MD5 but wrong cache bytes.
    zot.put("ITEM0002", title="Other", collections=["COLA"])
    zot.attach("ITEM0002", "ATT00002", bytes_=PDF)
    run_sync(cfg, zot, pdfs="all")
    wrong = cache / "ITEM0002.pdf"
    wrong.write_bytes(b"%PDF not-matching-" + hashlib.md5(b"x").digest())

    report = clean_pdf_cache(cfg, apply=False)
    assert report["apply"] is False
    assert report["removable"] >= 2  # absorbed + stale
    assert absorbed.is_file() and wrong.is_file() and orphan.is_file()

    applied = clean_pdf_cache(cfg, apply=True)
    assert applied["removed"] >= 2
    assert not absorbed.is_file()
    assert not wrong.is_file()
    assert orphan.is_file()  # no mirror folder / no matching record → kept
