"""What the index holds for each item, and what the next ingest should do about it.

The ledger is an append-only JSONL beside the index (latest line per item
wins, like the fetch manifest). It carries the display metadata too, so
``ask`` and ``search`` never have to walk the mirror.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..store import MirrorEntry
from .extract import file_sha256

STATUS_OK = "ok"  # PDF text is indexed
STATUS_STUB = "stub"  # only the abstract is indexed
STATUS_FAILED = "failed"  # nothing is indexed
_STATUS_REMOVED = "removed"  # tombstone: the item left the mirror or lost its text

ACTION_SKIP = "skip"
ACTION_PDF = "pdf"  # (re)index from the PDF
ACTION_STUB = "stub"  # (re)index from the abstract
ACTION_META = "meta"  # content is current; refresh title / authors / folders
ACTION_REMOVE = "remove"


@dataclass
class LedgerRow:
    key: str
    status: str = STATUS_OK
    source: str = ""  # pdf | ocr | abstract
    chunks: int = 0
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    item_type: str = ""
    dirs: list[str] = field(default_factory=list)  # item folders, relative to out_dir
    pdf: str = ""  # indexed file, relative to out_dir
    pdf_size: int = 0
    pdf_mtime_ns: int = 0
    pdf_sha256: str = ""
    pdf_count: int = 0  # distinct PDFs the item has; only the newest is indexed
    abstract_sha: str = ""
    ocr_pending: bool = False  # the PDF has no usable text and OCR has not run on it
    error: str = ""  # why the last PDF attempt failed
    params: str = ""  # parser + chunker settings the chunks were built with
    ts: float = 0.0


@dataclass(frozen=True)
class PdfStat:
    path: Path
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class Plan:
    action: str
    reason: str


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self._rows: dict[str, LedgerRow] = {}
        if not path.is_file():
            return
        known = set(LedgerRow.__dataclass_fields__)
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if not isinstance(data, dict) or not data.get("key"):
                continue
            row = LedgerRow(**{k: v for k, v in data.items() if k in known})
            if row.status == _STATUS_REMOVED:
                self._rows.pop(row.key, None)
            else:
                self._rows[row.key] = row

    def get(self, key: str) -> LedgerRow | None:
        return self._rows.get(key)

    def rows(self) -> list[LedgerRow]:
        return list(self._rows.values())

    def keys(self) -> set[str]:
        return set(self._rows)

    def write(self, row: LedgerRow) -> None:
        row.ts = time.time()
        self._append(row)
        self._rows[row.key] = row

    def remove(self, key: str) -> None:
        if key not in self._rows:
            return
        self._append(LedgerRow(key=key, status=_STATUS_REMOVED, ts=time.time()))
        del self._rows[key]

    def _append(self, row: LedgerRow) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")


def pick_pdf(entry: MirrorEntry) -> PdfStat | None:
    """The one PDF to index: newest, then largest.

    OCR replaces the file in one folder and leaves the old scan hardlinked in
    the others, and a re-download lands beside an older copy. Newest wins both.
    """
    best: PdfStat | None = None
    for path in entry.pdfs:
        try:
            st = path.stat()
        except OSError:
            continue
        stat = PdfStat(path=path, size=st.st_size, mtime_ns=st.st_mtime_ns)
        if best is None or (stat.mtime_ns, stat.size, str(path)) > (
            best.mtime_ns,
            best.size,
            str(best.path),
        ):
            best = stat
    return best


def abstract_of(entry: MirrorEntry) -> str:
    return str(entry.record.get("abstract") or "").strip()


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def describe(entry: MirrorEntry) -> dict[str, object]:
    """The display metadata a ledger row keeps for an entry."""
    item = entry.item()
    return {
        "title": item.title,
        "authors": list(item.creator_surnames),
        "year": item.year,
        "item_type": item.item_type,
        "dirs": list(entry.dirs),
    }


def _pdf_unchanged(
    row: LedgerRow, pdf: PdfStat, hasher: Callable[[Path], str]
) -> bool:
    if not row.pdf_sha256:
        return False
    if row.pdf_size == pdf.size and row.pdf_mtime_ns == pdf.mtime_ns:
        return True
    # Touched or copied: the bytes decide.
    return row.pdf_size == pdf.size and hasher(pdf.path) == row.pdf_sha256


def plan_item(
    entry: MirrorEntry,
    row: LedgerRow | None,
    *,
    pdf: PdfStat | None,
    params: str,
    ocr_available: bool,
    abstracts: bool = True,
    force: bool = False,
    retry_failed: bool = False,
    hasher: Callable[[Path], str] = file_sha256,
) -> Plan:
    """Decide what ingest does with one item. Reads the PDF only to settle a stat mismatch."""
    abstract = abstract_of(entry) if abstracts else ""

    def from_scratch(reason: str) -> Plan:
        if pdf is not None:
            return Plan(ACTION_PDF, reason)
        if abstract:
            return Plan(ACTION_STUB, reason)
        if row is not None:
            return Plan(ACTION_REMOVE, "no PDF or abstract left")
        return Plan(ACTION_SKIP, "no PDF or abstract")

    if row is None:
        return from_scratch("new")
    if force:
        return from_scratch("forced")
    if row.params != params:
        return from_scratch("settings changed")

    if pdf is None:
        if row.pdf_sha256:
            return from_scratch("PDF removed")
        if not abstract:
            return Plan(ACTION_REMOVE, "no PDF or abstract left")
        if text_sha(abstract) != row.abstract_sha:
            return Plan(ACTION_STUB, "abstract changed")
    else:
        if not _pdf_unchanged(row, pdf, hasher):
            return Plan(ACTION_PDF, "PDF changed" if row.pdf_sha256 else "PDF added")
        if row.error:
            if retry_failed:
                return Plan(ACTION_PDF, "retry")
            return Plan(ACTION_SKIP, f"failed earlier: {row.error}")
        if row.ocr_pending and ocr_available:
            return Plan(ACTION_PDF, "OCR now available")
        if row.status == STATUS_STUB and text_sha(abstract) != row.abstract_sha:
            # Still no readable PDF; keep the stub in step with the record.
            if abstract:
                return Plan(ACTION_STUB, "abstract changed")
            return Plan(ACTION_REMOVE, "no PDF text or abstract left")

    current = describe(entry)
    if any(getattr(row, name) != value for name, value in current.items()):
        return Plan(ACTION_META, "metadata changed")
    return Plan(ACTION_SKIP, "unchanged")
