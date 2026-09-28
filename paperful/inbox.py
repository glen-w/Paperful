"""PDF drop-folder watch: match hand downloads to library items and attach.

Distinct from snowball's ``state/snowball/watches/*/inbox.jsonl`` proposal queue.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .handoff import MissingPdf, attach_pdf_file, openable_rows
from .library import LibraryBackend, LibraryError
from .pdfid import doi_from_pdf
from .resolve import normalize_doi
from .store import Manifest
from .zot import Item

PARTIAL_SUFFIXES = (".crdownload", ".tmp", ".part", ".download")
UNMATCHED_DIRNAME = "unmatched"
SOURCE = "inbox"


@dataclass
class MatchResult:
    item: Item | None
    how: str  # doi | fifo | none
    doi: str | None = None
    reason: str = ""


@dataclass
class IngestEvent:
    path: str
    status: str  # attached | unmatched | error | skipped
    item_key: str = ""
    how: str = ""
    doi: str = ""
    detail: str = ""


@dataclass
class WatchStats:
    attached: int = 0
    unmatched: int = 0
    errors: int = 0
    skipped: int = 0
    events: list[IngestEvent] = field(default_factory=list)
    quit_reason: str = ""


def inbox_dir(cfg: Config) -> Path | None:
    return cfg.inbox_path


def ensure_inbox_dirs(cfg: Config) -> Path:
    """Create the drop folder and ``unmatched/``. Raises if ``[inbox].dir`` is empty."""
    root = cfg.inbox_path
    if root is None:
        raise ValueError(
            "[inbox].dir is empty. Set it in config.toml (e.g. ~/Documents/paperful_inbox)."
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / UNMATCHED_DIRNAME).mkdir(parents=True, exist_ok=True)
    return root


def wait_stable(
    path: Path,
    settle_seconds: float,
    *,
    poll: float = 0.25,
    timeout: float = 120.0,
) -> bool:
    """True when size stays unchanged for ``settle_seconds`` (or settle is 0)."""
    if settle_seconds <= 0:
        return path.is_file()
    deadline = time.monotonic() + timeout
    last_size = -1
    stable_since: float | None = None
    while time.monotonic() < deadline:
        if not path.is_file():
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        now = time.monotonic()
        if size == last_size and size > 0:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= settle_seconds:
                return True
        else:
            last_size = size
            stable_since = None
        time.sleep(poll)
    return False


def build_doi_index(items: Iterable[Item]) -> dict[str, Item]:
    """Normalized DOI → item among those still missing a stored PDF.

    Ambiguous DOIs (two missing items) are omitted so matching falls through.
    """
    counts: dict[str, list[Item]] = {}
    for item in items:
        if item.has_pdf:
            continue
        doi = normalize_doi(item.doi)
        if not doi:
            continue
        counts.setdefault(doi, []).append(item)
    return {doi: rows[0] for doi, rows in counts.items() if len(rows) == 1}


def match_pdf(
    path: Path,
    *,
    doi_index: dict[str, Item],
    fifo_queue: deque[MissingPdf] | None = None,
    items_by_key: dict[str, Item] | None = None,
) -> MatchResult:
    """DOI from the PDF first; optional FIFO of openable misses as fallback."""
    doi = doi_from_pdf(path)
    if doi:
        item = doi_index.get(doi)
        if item is not None:
            return MatchResult(item=item, how="doi", doi=doi)
        return MatchResult(
            item=None,
            how="none",
            doi=doi,
            reason=f"no missing-PDF item for DOI {doi}",
        )
    if fifo_queue is not None and items_by_key is not None:
        while fifo_queue:
            row = fifo_queue.popleft()
            item = items_by_key.get(row.key)
            if item is None or item.has_pdf:
                continue
            return MatchResult(item=item, how="fifo", doi=normalize_doi(item.doi))
    return MatchResult(item=None, how="none", reason="no DOI in PDF and no FIFO match")


def _is_partial_name(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(suf) for suf in PARTIAL_SUFFIXES)


def list_candidate_pdfs(root: Path) -> list[Path]:
    """Non-recursive ``*.pdf`` in the inbox root (not under ``unmatched/``)."""
    if not root.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(root.glob("*.pdf")):
        if not path.is_file():
            continue
        if _is_partial_name(path.name):
            continue
        out.append(path)
    return out


def _fingerprint(path: Path) -> str:
    try:
        st = path.stat()
        size = st.st_size
        mtime = int(st.st_mtime)
    except OSError:
        return f"{path.resolve()}|missing"
    digest = ""
    try:
        h = hashlib.md5()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        digest = h.hexdigest()
    except OSError:
        digest = "unreadable"
    return f"{path.resolve()}|{size}|{mtime}|{digest}"


class SeenLedger:
    """Append-only skip list so the same file is not ingested twice."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen: set[str] = set()
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    self._seen.add(line)
                    continue
                fp = row.get("fingerprint") or row.get("fp")
                if isinstance(fp, str) and fp:
                    self._seen.add(fp)

    def has(self, fingerprint: str) -> bool:
        return fingerprint in self._seen

    def add(self, fingerprint: str, *, path: str, status: str) -> None:
        if fingerprint in self._seen:
            return
        self._seen.add(fingerprint)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "fingerprint": fingerprint,
            "path": path,
            "status": status,
            "at": datetime.now(tz=timezone.utc).isoformat(),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def move_unmatched(root: Path, pdf: Path) -> Path:
    dest_dir = root / UNMATCHED_DIRNAME
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / pdf.name
    if dest.exists():
        stem, suf = pdf.stem, pdf.suffix
        n = 1
        while True:
            candidate = dest_dir / f"{stem}-{n}{suf}"
            if not candidate.exists():
                dest = candidate
                break
            n += 1
    pdf.replace(dest)
    return dest


def ingest_one(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    pdf: Path,
    *,
    doi_index: dict[str, Item],
    fifo_queue: deque[MissingPdf] | None = None,
    items_by_key: dict[str, Item] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> IngestEvent:
    """Match one stable PDF, attach or quarantine, remove original on attach."""
    say = on_status or (lambda _msg: None)
    root = ensure_inbox_dirs(cfg)
    matched = match_pdf(
        pdf,
        doi_index=doi_index,
        fifo_queue=fifo_queue,
        items_by_key=items_by_key,
    )
    if matched.item is None:
        dest = move_unmatched(root, pdf)
        detail = matched.reason or "unmatched"
        say(f"unmatched {pdf.name} → {dest} ({detail})")
        return IngestEvent(
            path=str(pdf),
            status="unmatched",
            how=matched.how,
            doi=matched.doi or "",
            detail=detail,
        )
    item = matched.item
    try:
        attach_pdf_file(cfg, backend, manifest, item, pdf, source=SOURCE)
    except (OSError, ValueError, LibraryError) as exc:
        say(f"error {pdf.name}: {exc}")
        return IngestEvent(
            path=str(pdf),
            status="error",
            item_key=item.key,
            how=matched.how,
            doi=matched.doi or "",
            detail=str(exc),
        )
    try:
        pdf.unlink(missing_ok=True)
    except OSError as exc:
        say(f"attached {item.key} ← {pdf.name} (could not remove drop file: {exc})")
    else:
        say(f"attached {item.key} ← {pdf.name} ({matched.how})")
    # Refresh index so a second file with the same DOI is unmatched.
    doi = normalize_doi(item.doi)
    if doi and doi_index.get(doi) is item:
        del doi_index[doi]
    item.has_pdf = True
    return IngestEvent(
        path=str(pdf),
        status="attached",
        item_key=item.key,
        how=matched.how,
        doi=matched.doi or "",
        detail=SOURCE,
    )


def process_candidates(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    items: list[Item],
    *,
    fifo_queue: deque[MissingPdf] | None = None,
    once: bool = False,
    idle_seconds: float | None = None,
    poll_seconds: float | None = None,
    settle_seconds: float | None = None,
    on_status: Callable[[str], None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> WatchStats:
    """Drain current PDFs (``once``) or poll until idle / interrupt."""
    say = on_status or (lambda _msg: None)
    sleeper = sleep_fn or time.sleep
    root = ensure_inbox_dirs(cfg)
    poll = cfg.inbox_poll_seconds if poll_seconds is None else poll_seconds
    settle = cfg.inbox_settle_seconds if settle_seconds is None else settle_seconds
    idle = cfg.inbox_idle_seconds if idle_seconds is None else idle_seconds
    doi_index = build_doi_index(items)
    items_by_key = {it.key: it for it in items}
    ledger = SeenLedger(cfg.inbox_seen_path)
    stats = WatchStats()
    last_activity = time.monotonic()

    def _handle(path: Path) -> None:
        nonlocal last_activity
        fp = _fingerprint(path)
        if ledger.has(fp):
            stats.skipped += 1
            stats.events.append(
                IngestEvent(path=str(path), status="skipped", detail="seen")
            )
            return
        if not wait_stable(path, settle):
            say(f"skip unstable {path.name}")
            stats.skipped += 1
            stats.events.append(
                IngestEvent(path=str(path), status="skipped", detail="unstable")
            )
            return
        fp = _fingerprint(path)
        if ledger.has(fp):
            stats.skipped += 1
            return
        event = ingest_one(
            cfg,
            backend,
            manifest,
            path,
            doi_index=doi_index,
            fifo_queue=fifo_queue,
            items_by_key=items_by_key,
            on_status=say,
        )
        stats.events.append(event)
        if event.status == "attached":
            stats.attached += 1
            last_activity = time.monotonic()
        elif event.status == "unmatched":
            stats.unmatched += 1
            last_activity = time.monotonic()
        elif event.status == "error":
            stats.errors += 1
            last_activity = time.monotonic()
        ledger.add(fp, path=str(path), status=event.status)

    try:
        while True:
            candidates = list_candidate_pdfs(root)
            for path in candidates:
                _handle(path)
            if once:
                stats.quit_reason = "drain"
                break
            if idle > 0 and (time.monotonic() - last_activity) >= idle:
                stats.quit_reason = "idle"
                say(f"idle for {idle:g}s — stopping")
                break
            sleeper(poll)
    except KeyboardInterrupt:
        stats.quit_reason = "interrupt"
        say("interrupted")
    return stats


def fifo_from_missing(rows: list[MissingPdf]) -> deque[MissingPdf]:
    return deque(openable_rows(rows))


def events_as_report_items(events: list[IngestEvent]) -> list[dict]:
    return [
        {
            "path": e.path,
            "status": e.status,
            "itemKey": e.item_key,
            "how": e.how,
            "doi": e.doi,
            "detail": e.detail,
        }
        for e in events
    ]


def summary_from_stats(stats: WatchStats) -> dict:
    return {
        "attached": stats.attached,
        "unmatched": stats.unmatched,
        "errors": stats.errors,
        "skipped": stats.skipped,
        "quit_reason": stats.quit_reason,
    }
