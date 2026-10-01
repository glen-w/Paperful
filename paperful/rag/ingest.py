"""Build the index from the mirror: text → passages → vectors.

Reads ``out_dir`` only. The one thing it changes there is a scanned PDF,
which OCRmyPDF rewrites with a text layer when ``[rag].ocr = "auto"``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config
from ..llm.embed import Embedder, get_embedder
from ..ocr import ocr_items, ocrmypdf_available
from ..progress import Track
from ..store import Manifest, MirrorEntry, mirror_entries
from ..zot import filter_items_by_type, filter_items_by_year
from .chunk import CHUNKER_VERSION, Chunk, chunk_pages, embed_text
from .extract import ParseError, Parser, cached_pages, file_sha256, get_parser, needs_ocr
from .index import Index, ledger_path, load_meta
from .ledger import (
    ACTION_META,
    ACTION_PDF,
    ACTION_REMOVE,
    ACTION_SKIP,
    ACTION_STUB,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_STUB,
    Ledger,
    LedgerRow,
    PdfStat,
    Plan,
    abstract_of,
    describe,
    pick_pdf,
    plan_item,
    text_sha,
)

# Row outcomes. A dry run reports the same words for what it would do.
DONE_PDF = "pdf"  # indexed from the PDF's text layer
DONE_OCR = "ocr"  # indexed after OCR added a text layer
DONE_ABSTRACT = "abstract"  # no readable PDF; the abstract is indexed
DONE_META = "meta"  # title / authors / folders refreshed
DONE_REMOVED = "removed"
DONE_UNCHANGED = "unchanged"
DONE_NOTHING = "nothing"  # no PDF and no abstract
DONE_FAILED = "failed"


@dataclass
class IngestRow:
    key: str
    title: str
    status: str
    reason: str = ""
    chunks: int = 0

    @property
    def label(self) -> str:
        return self.title[:70] or self.key


@dataclass
class IngestBatch:
    rows: list[IngestRow] = field(default_factory=list)
    dry_run: bool = False

    def count(self, *statuses: str) -> int:
        return sum(1 for row in self.rows if row.status in statuses)

    @property
    def chunks(self) -> int:
        return sum(row.chunks for row in self.rows)

    def summary(self) -> dict[str, int]:
        return {
            "pdf": self.count(DONE_PDF),
            "ocr": self.count(DONE_OCR),
            "abstract": self.count(DONE_ABSTRACT),
            "meta": self.count(DONE_META),
            "removed": self.count(DONE_REMOVED),
            "unchanged": self.count(DONE_UNCHANGED),
            "empty": self.count(DONE_NOTHING),
            "failed": self.count(DONE_FAILED),
            "chunks": self.chunks,
        }


def select_entries(
    cfg: Config,
    *,
    collections: list[str] | None = None,
    item_keys: Iterable[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    item_types: frozenset[str] | None = None,
) -> list[MirrorEntry]:
    """Mirror entries in scope. A collection is a folder path prefix under ``out_dir``."""
    keys = list(item_keys or [])
    entries = mirror_entries(cfg.out_dir, collections or None, keys or None)
    if year_from is None and year_to is None and item_types is None:
        return entries
    items = [entry.item() for entry in entries]
    items = filter_items_by_type(filter_items_by_year(items, year_from, year_to), item_types)
    keep = {item.key for item in items}
    return [entry for entry in entries if entry.key in keep]


def chunk_params(cfg: Config, parser: Parser) -> str:
    """Settings that decide what the passages look like. A change re-ingests."""
    return (
        f"{parser.name}{parser.version}/c{CHUNKER_VERSION}"
        f"/{cfg.rag_chunk_chars}/{cfg.rag_chunk_overlap}"
    )


@dataclass
class _Deferred:
    entry: MirrorEntry
    pdf: PdfStat
    why: str


class _Run:
    """One ingest run. The embedder and the index are opened on first use."""

    def __init__(
        self,
        cfg: Config,
        *,
        parser: Parser,
        ledger: Ledger,
        embedder: Embedder | None,
        index: Index | None,
    ):
        self.cfg = cfg
        self.parser = parser
        self.params = chunk_params(cfg, parser)
        self.ledger = ledger
        self._embedder = embedder
        self._index = index
        self.wrote = False

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = get_embedder(self.cfg)
        return self._embedder

    @property
    def index(self) -> Index:
        if self._index is None:
            dim = None
            if load_meta(self.cfg) is None:
                # One call to learn the vector width before the table exists.
                dim = len(self.embedder.embed_query("paperful"))
            self._index = Index.open(self.cfg, dim=dim, create=True)
        return self._index

    def _row(self, entry: MirrorEntry, pdf: PdfStat | None, sha: str) -> LedgerRow:
        row = LedgerRow(key=entry.key, params=self.params, **describe(entry))
        row.pdf_count = len(entry.pdfs)
        row.abstract_sha = text_sha(abstract_of(entry))
        if pdf is not None:
            try:
                row.pdf = pdf.path.relative_to(self.cfg.out_dir).as_posix()
            except ValueError:
                row.pdf = str(pdf.path)
            row.pdf_size = pdf.size
            row.pdf_mtime_ns = pdf.mtime_ns
            row.pdf_sha256 = sha
        return row

    def _store(self, entry: MirrorEntry, chunks: list[Chunk], source: str) -> None:
        title = str(entry.record.get("title") or "")
        vectors = self.embedder.embed_documents(
            [embed_text(chunk, title) for chunk in chunks]
        )
        paged = source != "abstract"
        rows: list[dict[str, Any]] = [
            {
                "chunk_id": f"{entry.key}:{chunk.index}",
                "item_key": entry.key,
                "chunk_index": chunk.index,
                "source": source,
                "section": chunk.section,
                "page_start": chunk.page_start if paged else None,
                "page_end": chunk.page_end if paged else None,
                "text": chunk.text,
                "vector": vector,
            }
            for chunk, vector in zip(chunks, vectors)
        ]
        self.index.replace_item(entry.key, rows)
        self.wrote = True

    def index_pdf(
        self,
        entry: MirrorEntry,
        pdf: PdfStat,
        sha: str,
        pages: list[str],
        *,
        source: str,
        reason: str = "",
        ocr_pending: bool = False,
        error: str = "",
    ) -> IngestRow:
        """Index the PDF's passages, or fall back to the abstract when it has none."""
        chunks = chunk_pages(
            pages, chunk_chars=self.cfg.rag_chunk_chars, overlap=self.cfg.rag_chunk_overlap
        )
        row = self._row(entry, pdf, sha)
        row.ocr_pending = ocr_pending
        row.error = error
        if chunks:
            self._store(entry, chunks, source)
            row.status, row.source, row.chunks = STATUS_OK, source, len(chunks)
            self.ledger.write(row)
            return IngestRow(entry.key, row.title, source, error or reason, len(chunks))
        why = error or ("waiting for OCR" if ocr_pending else "PDF has no readable text")
        return self._fallback(entry, row, why)

    def index_stub(self, entry: MirrorEntry, pdf: PdfStat | None, reason: str) -> IngestRow:
        """Index the abstract. A PDF that is still unreadable keeps its ledger facts."""
        row = self._row(entry, None, "")
        old = self.ledger.get(entry.key)
        if pdf is not None and old is not None:
            row.pdf, row.pdf_sha256 = old.pdf, old.pdf_sha256
            row.pdf_size, row.pdf_mtime_ns = old.pdf_size, old.pdf_mtime_ns
            row.ocr_pending, row.error = old.ocr_pending, old.error
        return self._fallback(entry, row, reason)

    def unreadable(self, entry: MirrorEntry, pdf: PdfStat, sha: str, error: str) -> IngestRow:
        row = self._row(entry, pdf, sha)
        row.error = error
        return self._fallback(entry, row, error)

    def _fallback(self, entry: MirrorEntry, row: LedgerRow, reason: str) -> IngestRow:
        """Index the abstract, or record that the item has nothing to index."""
        abstract = abstract_of(entry) if self.cfg.rag_abstracts else ""
        chunks = chunk_pages(
            [abstract],
            chunk_chars=self.cfg.rag_chunk_chars,
            overlap=self.cfg.rag_chunk_overlap,
            min_chars=1,
        )
        if chunks:
            self._store(entry, chunks, "abstract")
            row.status, row.source, row.chunks = STATUS_STUB, "abstract", len(chunks)
            self.ledger.write(row)
            return IngestRow(entry.key, row.title, DONE_ABSTRACT, reason, len(chunks))
        if self.ledger.get(entry.key) is not None and self._index_exists():
            self.index.replace_item(entry.key, [])
            self.wrote = True
        row.status, row.source, row.chunks = STATUS_FAILED, "", 0
        if not row.ocr_pending:
            # An error parks the item until its PDF changes. A scan that only
            # waits for OCR stays open for the next run that can do it.
            row.error = row.error or reason
        self.ledger.write(row)
        return IngestRow(entry.key, row.title, DONE_FAILED, row.error or reason)

    def _index_exists(self) -> bool:
        return self._index is not None or load_meta(self.cfg) is not None

    def remove(self, key: str) -> None:
        if self._index_exists():
            self.index.delete_items({key})
            self.wrote = True
        self.ledger.remove(key)

    def refresh_meta(self, entry: MirrorEntry) -> None:
        row = self.ledger.get(entry.key)
        if row is None:
            return
        for name, value in describe(entry).items():
            setattr(row, name, value)
        row.pdf_count = len(entry.pdfs)
        self.ledger.write(row)

    def finish(self) -> None:
        if self.wrote and self._index is not None:
            self._index.finish()


def _dry_row(entry: MirrorEntry, plan: Plan) -> IngestRow:
    status = {
        ACTION_PDF: DONE_PDF,
        ACTION_STUB: DONE_ABSTRACT,
        ACTION_META: DONE_META,
        ACTION_REMOVE: DONE_REMOVED,
    }.get(plan.action)
    if status is None:
        status = DONE_UNCHANGED if plan.reason != "no PDF or abstract" else DONE_NOTHING
    return IngestRow(entry.key, str(entry.record.get("title") or ""), status, plan.reason)


def ingest_entries(
    cfg: Config,
    entries: list[MirrorEntry],
    *,
    force: bool = False,
    retry_failed: bool = False,
    ocr: bool = True,
    dry_run: bool = False,
    prune: bool = False,
    limit: int | None = None,
    track: Track | None = None,
    ocr_track: Track | None = None,
    embedder: Embedder | None = None,
    index: Index | None = None,
    parser: Parser | None = None,
    ocr_available: Callable[[], bool] = ocrmypdf_available,
) -> IngestBatch:
    """Bring the index in line with ``entries``. Unchanged items cost one ``stat``.

    Born-digital PDFs are indexed first; scans are OCR'd together afterwards so
    they never hold up the rest. ``prune`` also drops indexed items that are
    not in ``entries``, so pass it only with the whole mirror. ``limit`` caps
    how many items are worked on, so a long first build can be done in parts.
    A ``dry_run`` reports the plan and touches nothing.
    """
    parser = parser or get_parser(cfg)
    ledger = Ledger(ledger_path(cfg))
    run = _Run(cfg, parser=parser, ledger=ledger, embedder=embedder, index=index)
    can_ocr = ocr and cfg.rag_ocr == "auto" and ocr_available()
    batch = IngestBatch(dry_run=dry_run)
    deferred: list[_Deferred] = []

    planned: list[tuple[MirrorEntry, PdfStat | None, Plan]] = []
    for entry in entries:
        pdf = pick_pdf(entry)
        plan = plan_item(
            entry,
            ledger.get(entry.key),
            pdf=pdf,
            params=run.params,
            ocr_available=can_ocr,
            abstracts=cfg.rag_abstracts,
            force=force,
            retry_failed=retry_failed,
        )
        planned.append((entry, pdf, plan))
    if limit is not None:
        kept, todo = [], 0
        for row in planned:
            if row[2].action != ACTION_SKIP:
                todo += 1
                if todo > limit:
                    continue
            kept.append(row)
        planned = kept
    gone = sorted(ledger.keys() - {entry.key for entry in entries}) if prune else []

    if dry_run:
        batch.rows = [_dry_row(entry, plan) for entry, _pdf, plan in planned]
        for key in gone:
            row = ledger.get(key)
            batch.rows.append(
                IngestRow(key, row.title if row else "", DONE_REMOVED, "not in the mirror")
            )
        return batch

    try:
        work = [p for p in planned if p[2].action != ACTION_SKIP]
        for entry, _pdf, plan in planned:
            if plan.action == ACTION_SKIP:
                batch.rows.append(_dry_row(entry, plan))
        for entry, pdf, plan in track(work) if track else work:
            title = str(entry.record.get("title") or "")
            if plan.action == ACTION_META:
                run.refresh_meta(entry)
                batch.rows.append(IngestRow(entry.key, title, DONE_META, plan.reason))
            elif plan.action == ACTION_REMOVE:
                run.remove(entry.key)
                batch.rows.append(IngestRow(entry.key, title, DONE_REMOVED, plan.reason))
            elif plan.action == ACTION_STUB or pdf is None:
                batch.rows.append(run.index_stub(entry, pdf, plan.reason))
            else:
                sha = ""
                try:
                    sha = file_sha256(pdf.path)
                    pages = cached_pages(cfg, entry.key, pdf.path, sha, parser)
                except (ParseError, OSError) as exc:
                    batch.rows.append(
                        run.unreadable(entry, pdf, sha, f"unreadable PDF: {exc}")
                    )
                    continue
                why = needs_ocr(pages)
                if why is not None and can_ocr:
                    deferred.append(_Deferred(entry, pdf, why))
                    continue
                batch.rows.append(
                    run.index_pdf(
                        entry,
                        pdf,
                        sha,
                        pages,
                        source="pdf",
                        reason=plan.reason,
                        ocr_pending=why is not None,
                    )
                )
        if deferred:
            batch.rows.extend(_ocr_then_index(cfg, run, deferred, ocr_track))
        for key in gone:
            row = ledger.get(key)
            run.remove(key)
            batch.rows.append(
                IngestRow(key, row.title if row else "", DONE_REMOVED, "not in the mirror")
            )
    finally:
        run.finish()
    return batch


def _ocr_then_index(
    cfg: Config, run: _Run, deferred: list[_Deferred], track: Track | None
) -> list[IngestRow]:
    by_key = {job.entry.key: job for job in deferred}
    reasons = {str(job.pdf.path): job.why for job in deferred}
    items = []
    for job in deferred:
        item = job.entry.item()
        item.pdf_path, item.has_pdf = str(job.pdf.path), True
        items.append(item)
    ocr_batch = ocr_items(
        cfg,
        items,
        Manifest(cfg.manifest_path),
        None,
        apply=True,
        track=track,
        classify=lambda path: reasons.get(str(path)),
    )
    rows: list[IngestRow] = []
    for ocr_row in ocr_batch.rows:
        job = by_key[ocr_row.key]
        error = "" if ocr_row.status == "ocr" else f"OCR failed: {ocr_row.reason}"
        path = Path(ocr_row.path) if ocr_row.path else job.pdf.path
        pdf, sha = job.pdf, ""
        try:
            st = path.stat()
            pdf = PdfStat(path=path, size=st.st_size, mtime_ns=st.st_mtime_ns)
            sha = file_sha256(path)
            pages = cached_pages(cfg, job.entry.key, path, sha, run.parser)
        except (ParseError, OSError) as exc:
            rows.append(
                run.unreadable(job.entry, pdf, sha, error or f"unreadable PDF: {exc}")
            )
            continue
        rows.append(
            run.index_pdf(
                job.entry,
                pdf,
                sha,
                pages,
                source="ocr" if not error else "pdf",
                reason=job.why,
                error=error,
            )
        )
    return rows
