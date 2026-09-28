"""Soft-blocked PDF handoff and manual attach."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperful.handoff import (
    HINT_DOI,
    HINT_OPENABLE,
    MissingPdf,
    attach_pdf_file,
    classify_missing_hint,
    list_missing_pdfs,
    newest_pdf_in_dir,
    open_tabs,
    parse_handoff,
    soft_attempts,
    walk_missing,
    write_missing_export,
)
from paperful.routing import browser_lane_failed, soft_block_miss
from paperful.store import Manifest, STATUS_ATTACHED
from tests.conftest import make_item


def test_missing_from_run_outcomes_keeps_soft_blocks():
    from paperful.handoff import HINT_OPENABLE, missing_from_run_outcomes

    item = make_item(
        key="SOFT0001",
        has_pdf=False,
        url="https://journals.ametsoc.org/downloadpdf/x.pdf",
    )
    rows = missing_from_run_outcomes(
        {item.key: item},
        [
            {
                "itemKey": "SOFT0001",
                "status": "retryable",
                "reason": "soft block",
                "attempts": [
                    "unpaywall:found",
                    "unpaywall:download-failed(too small (0 bytes))",
                ],
            },
            {
                "itemKey": "OTHER",
                "status": "not_found",
                "reason": "closed",
                "attempts": ["scihub:skipped(not applicable)"],
            },
        ],
    )
    assert len(rows) == 1 and rows[0].key == "SOFT0001"
    assert rows[0].hint == HINT_OPENABLE


def test_parse_handoff_rejects_unknown():
    assert parse_handoff(None) == "list"
    assert parse_handoff("TABS") == "tabs"
    with pytest.raises(ValueError, match="walk"):
        parse_handoff("explode")


def test_classify_openable_pdf_url_and_soft_block():
    assert (
        classify_missing_hint(
            doi="10.1/x",
            url="https://journals.ametsoc.org/downloadpdf/journals/wcas/15/2/x.pdf",
        )
        == HINT_OPENABLE
    )
    assert (
        classify_missing_hint(
            doi="10.1/x",
            url="https://example.org/article",
            attempts=[
                "unpaywall:found",
                "unpaywall:download-failed(too small (0 bytes))",
            ],
        )
        == HINT_OPENABLE
    )
    assert classify_missing_hint(doi="10.1/x", url="") == HINT_DOI


def test_soft_block_miss_enables_browser_lane_failed():
    attempts = [
        "unpaywall:found",
        "unpaywall:download-failed(too small (0 bytes))",
        "scihub:skipped(not applicable)",
    ]
    assert soft_block_miss(attempts)
    assert soft_attempts(attempts)
    assert browser_lane_failed(attempts)


def test_ametsoc_is_publisher_host():
    from paperful.routing import is_publisher_url, publisher_host

    url = "https://journals.ametsoc.org/downloadpdf/journals/wcas/15/2/x.pdf"
    assert publisher_host(url) == "ametsoc.org"
    assert is_publisher_url(url)


def test_list_missing_pdfs_orders_openable_first(cfg):
    items = [
        make_item(key="HARD0001", has_pdf=False, url="", doi="10.1/hard"),
        make_item(
            key="OPEN0001",
            has_pdf=False,
            url="https://example.org/a.pdf",
            doi="10.1/open",
            title="Openable first",
        ),
        make_item(key="HAVEPDF1", has_pdf=True, url="https://example.org/b.pdf"),
    ]
    rows = list_missing_pdfs(items)
    assert [r.key for r in rows] == ["OPEN0001", "HARD0001"]
    assert rows[0].hint == HINT_OPENABLE


def test_open_tabs_confirms_when_many():
    rows = [
        MissingPdf(
            key=f"K{i}",
            title=f"T{i}",
            doi="",
            url=f"https://example.org/{i}.pdf",
            hint=HINT_OPENABLE,
            attempts=[],
        )
        for i in range(25)
    ]
    opened: list[str] = []
    assert open_tabs(rows, confirm=lambda n: False, opener=lambda u: opened.append(u) or True) == 0
    assert opened == []
    n = open_tabs(rows, confirm=lambda n: True, opener=lambda u: opened.append(u) or True)
    assert n == 25 and len(opened) == 25


def test_newest_pdf_in_dir(tmp_path: Path):
    older = tmp_path / "a.pdf"
    newer = tmp_path / "b.pdf"
    older.write_bytes(b"%PDF-1.4 older")
    newer.write_bytes(b"%PDF-1.4 newer")
    older_mtime = older.stat().st_mtime
    import time

    time.sleep(0.05)
    newer.write_bytes(b"%PDF-1.4 newer2")
    assert newest_pdf_in_dir(tmp_path).name == "b.pdf"
    assert newest_pdf_in_dir(tmp_path, after_ts=older_mtime + 1000) is None


def test_write_missing_export_tsv_and_md(tmp_path: Path):
    rows = [
        MissingPdf("K1", "Title", "10.1/x", "https://x/a.pdf", HINT_OPENABLE, []),
    ]
    tsv = write_missing_export(rows, tmp_path / "m.tsv")
    assert "K1" in tsv.read_text()
    md = write_missing_export(rows, tmp_path / "m.md")
    assert "| K1 |" in md.read_text()


def test_attach_pdf_file_writes_manifest(cfg, tmp_path: Path):
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir = tmp_path / "state"
    cfg.state_dir.mkdir(parents=True)
    pdf = tmp_path / "hand.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"x" * 12_000)
    item = make_item(key="HAND0001", has_pdf=False, collection_paths=["Col"])
    attached: list[tuple] = []

    class Backend:
        def supports_write(self):
            return True

        def attach(self, key, path, title=None, note=None):
            attached.append((key, path, note))

            class R:
                ok = True
                reason = "uploaded"

            return R()

    rec = attach_pdf_file(
        cfg, Backend(), Manifest(cfg.manifest_path), item, pdf
    )
    assert rec.status == STATUS_ATTACHED and rec.itemKey == "HAND0001"
    assert attached and attached[0][0] == "HAND0001"
    assert (cfg.out_dir / "Col").exists()
    assert Manifest(cfg.manifest_path).records["HAND0001"].status == STATUS_ATTACHED


def test_attach_pdf_file_rejects_non_pdf(cfg, tmp_path: Path):
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir = tmp_path / "state"
    cfg.state_dir.mkdir(parents=True)
    bad = tmp_path / "x.txt"
    bad.write_text("nope")

    class Backend:
        def supports_write(self):
            return True

    with pytest.raises(ValueError, match="not a PDF"):
        attach_pdf_file(
            cfg,
            Backend(),
            Manifest(cfg.manifest_path),
            make_item(key="BAD00001"),
            bad,
        )


def test_walk_missing_attaches_from_prompt(cfg, tmp_path: Path):
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir = tmp_path / "state"
    cfg.state_dir.mkdir(parents=True)
    pdf = tmp_path / "dl" / "paper.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4 " + b"y" * 12_000)
    item = make_item(
        key="WALK0001",
        has_pdf=False,
        url="https://example.org/a.pdf",
        collection_paths=["Col"],
    )
    rows = list_missing_pdfs([item])
    replies = iter([str(pdf)])

    class Backend:
        def supports_write(self):
            return True

        def attach(self, key, path, title=None, note=None):
            class R:
                ok = True
                reason = "ok"

            return R()

    result = walk_missing(
        cfg,
        Backend(),
        Manifest(cfg.manifest_path),
        {item.key: item},
        rows,
        downloads_dir=pdf.parent,
        prompt=lambda _msg: next(replies),
        opener=lambda _url: True,
    )
    assert result.attached == 1 and result.skipped == 0


def test_is_soft_block_error():
    from paperful.download import DownloadError
    from paperful.pipeline import _is_soft_block_error

    assert _is_soft_block_error(DownloadError("too small (0 bytes)"))
    assert _is_soft_block_error(DownloadError("not a PDF (content-type text/html)"))
    assert not _is_soft_block_error(DownloadError("HTTP 403"))
