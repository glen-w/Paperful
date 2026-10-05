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


def test_cache_clean_cli_dry_run(tmp_path):
    from typer.testing import CliRunner

    from paperful import cli

    cfg_path = tmp_path / "config.toml"
    out = tmp_path / "out"
    state = tmp_path / "state"
    out.mkdir()
    state.mkdir()
    cfg_path.write_text(
        f'out_dir = "{out}"\nstate_dir = "{state}"\n', encoding="utf-8"
    )
    cache = state / "pdf-cache"
    cache.mkdir()
    (cache / "ORPHAN01.pdf").write_bytes(b"%PDF orphan")

    runner = CliRunner()
    res = runner.invoke(cli.app, ["cache", "clean", "-c", str(cfg_path)])
    assert res.exit_code == 0, (res.exit_code, res.stdout, res.stderr, res.exception)
    assert "Would remove" in res.stdout
    assert (cache / "ORPHAN01.pdf").is_file()

    help_res = runner.invoke(cli.app, ["cache", "clean", "--help"])
    assert help_res.exit_code == 0
    assert "--apply" in help_res.stdout

    js = runner.invoke(
        cli.app, ["cache", "clean", "-c", str(cfg_path), "--format", "json"]
    )
    assert js.exit_code == 0, (js.exit_code, js.stdout, js.stderr)
    import json

    body = json.loads(js.stdout)
    assert body["command"] == "cache clean"
    assert "removable" in body["summary"]
