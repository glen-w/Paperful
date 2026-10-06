"""Save a fetched PDF, write the manifest, and attach when allowed."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.markup import escape

from .download import Download
from .pdfid import doi_from_pdf as _pdfid_doi_from_pdf
from .store import (
    REASON_SHORT_PDF,
    REASON_STRICT_PDF_DOI,
    STATUS_OK,
    Record,
    relpaths,
    save_pdf,
    write_fetch_records,
)

if TYPE_CHECKING:
    from .pipeline import Pipeline
    from .sources import Candidate
    from .zot import Item


def _doi_from_pdf(path: Path) -> str | None:
    """Use ``pipeline.doi_from_pdf`` so tests can monkeypatch the pipeline module."""
    from . import pipeline as pipeline_mod

    fn = getattr(pipeline_mod, "doi_from_pdf", _pdfid_doi_from_pdf)
    return fn(path)


def commit_download(
    pipe: Pipeline,
    item: Item,
    cand: Candidate,
    dl: Download,
    attempts: list[str],
    *,
    oa_stamp: dict[str, str],
    short_verdict: str,
) -> bool:
    primary, extras = save_pdf(pipe.cfg.out_dir, item, dl.content, dl.md5)
    pdf_doi = _doi_from_pdf(primary)
    write_fetch_records(
        [primary, *extras],
        item,
        md5=dl.md5,
        source=cand.source,
        fetched_url=dl.final_url,
        pdf_doi=pdf_doi,
        oa_stamp=oa_stamp or None,
    )
    mismatch = bool(pdf_doi and item.doi and pdf_doi != item.doi)
    if mismatch:
        pipe._log_item(
            item,
            f"[yellow]pdf DOI {escape(pdf_doi)} differs from {escape(item.doi)}[/]",
        )
    defer_mismatch = mismatch and pipe.strict_pdf_doi
    defer_short = short_verdict == "dense_short"
    hold_reason = ""
    if defer_mismatch:
        hold_reason = REASON_STRICT_PDF_DOI
    elif defer_short:
        hold_reason = REASON_SHORT_PDF
    rec = Record(
        itemKey=item.key,
        status=STATUS_OK,
        title=item.title,
        doi=item.doi,
        doi_source=item.doi_source,
        library_doi=item.library_doi,
        doi_verified=item.doi_verified,
        pdf_doi=pdf_doi,
        source=cand.source,
        playbook=cand.playbook,
        url=dl.final_url,
        path=str(primary),
        extra_paths=relpaths(pipe.cfg.out_dir, extras),
        md5=dl.md5,
        attempts=attempts,
        reason=hold_reason,
        oa_license=oa_stamp.get("license", ""),
        oa_status=oa_stamp.get("oa_status", ""),
        oa_version=oa_stamp.get("version", ""),
    )
    pipe.manifest.write(rec)
    if (
        cand.source == "author_site"
        and cand.referer
        and getattr(pipe.cfg, "twenty_writeback_listings", False)
        and not hold_reason
    ):
        try:
            from .twenty import writeback_item_listing

            writeback_item_listing(pipe.cfg, item, cand.referer, source="author_site")
        except Exception as exc:
            pipe._log_item(item, f"[dim]twenty writeback skipped[/] {exc}")
    with pipe._stats_lock:
        pipe.stats.bump(STATUS_OK, cand.source)
    pipe._log_item(
        item,
        f"[green]ok[/] {escape('[' + cand.source + ']')} -> {escape(str(primary.relative_to(pipe.cfg.out_dir)))}",
    )
    if defer_mismatch:
        pipe._log_item(
            item,
            "[yellow]saved, not attached (--strict-pdf-doi)[/]",
        )
        pipe._add_outcome(rec)
    elif defer_short:
        pipe._log_item(
            item,
            "[yellow]saved, not attached (short PDF — "
            "admit with attach --allow-short-pdf)[/]",
        )
        pipe._add_outcome(rec)
    elif pipe.attacher:
        pipe.attach_record(rec)
    else:
        pipe._add_outcome(rec)
    return True
