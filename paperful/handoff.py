"""Manual recovery for soft-blocked / missing PDFs.

Lists collection-scoped misses with openable URLs, opens the user's browser
(``list`` / ``tabs`` / ``walk``), and ingests hand-downloaded files.
"""

from __future__ import annotations

import csv
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .config import Config
from .download import looks_like_pdf
from .library import LibraryBackend, LibraryError
from .provenance import provenance_stamp
from .store import (
    STATUS_ATTACHED,
    Manifest,
    Record,
    relpaths,
    save_pdf,
)
from .zot import Item

HANDOFF_MODES = frozenset({"list", "tabs", "walk", "watch"})
TABS_CONFIRM_AFTER = 20
HINT_OPENABLE = "openable_url"
HINT_DOI = "doi_only"
HINT_HARD = "hard_miss"


@dataclass
class MissingPdf:
    key: str
    title: str
    doi: str
    url: str
    hint: str
    attempts: list[str]

    @property
    def open_url(self) -> str:
        if self.url:
            return self.url
        if self.doi:
            return f"https://doi.org/{self.doi}"
        return ""


def parse_handoff(raw: str | None, *, default: str = "list") -> str:
    text = (raw or default).strip().lower() or default
    if text not in HANDOFF_MODES:
        known = ", ".join(sorted(HANDOFF_MODES))
        raise ValueError(f"Unknown handoff mode {raw!r}. Known: {known}")
    return text


def classify_missing_hint(
    *,
    doi: str | None,
    url: str | None,
    attempts: list[str] | None = None,
) -> str:
    """``openable_url`` when a human browser can likely open a PDF URL."""
    attempts = attempts or []
    url = (url or "").strip()
    soft = any(
        "download-failed(too small" in a or "download-failed(not a PDF" in a
        for a in attempts
    )
    found = any(":found" in a for a in attempts)
    if url and (_url_looks_like_pdf(url) or (found and soft)):
        return HINT_OPENABLE
    if doi:
        return HINT_DOI
    return HINT_HARD


def _url_looks_like_pdf(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or "/downloadpdf/" in path or "/pdf/" in path


def list_missing_pdfs(
    items: list[Item],
    manifest: Manifest | None = None,
    *,
    openable_only: bool = False,
) -> list[MissingPdf]:
    """Items in scope with no stored PDF, enriched from the manifest when present."""
    rows: list[MissingPdf] = []
    for item in items:
        if item.has_pdf:
            continue
        rec = manifest.records.get(item.key) if manifest is not None else None
        attempts = list(rec.attempts) if rec is not None else []
        url = (item.url or "").strip() or ((rec.url or "").strip() if rec else "")
        hint = classify_missing_hint(doi=item.doi, url=url, attempts=attempts)
        if openable_only and hint != HINT_OPENABLE:
            continue
        rows.append(
            MissingPdf(
                key=item.key,
                title=item.title,
                doi=item.doi or "",
                url=url,
                hint=hint,
                attempts=attempts,
            )
        )
    rows.sort(key=lambda r: (0 if r.hint == HINT_OPENABLE else 1, r.title.lower()))
    return rows


def missing_from_run_outcomes(
    items_by_key: dict[str, Item],
    outcomes: list[dict],
) -> list[MissingPdf]:
    """Soft-blocked / openable misses from a just-finished run report."""
    rows: list[MissingPdf] = []
    for row in outcomes:
        status = str(row.get("status") or "")
        if status not in {"not_found", "retryable", "error", "captcha"}:
            continue
        key = str(row.get("itemKey") or "")
        item = items_by_key.get(key)
        if item is None or item.has_pdf:
            continue
        attempts = list(row.get("attempts") or [])
        url = (item.url or "").strip() or str(row.get("url") or "")
        reason = str(row.get("reason") or "")
        hint = classify_missing_hint(doi=item.doi, url=url, attempts=attempts)
        if reason == "soft block" or soft_attempts(attempts) or _url_looks_like_pdf(url):
            hint = HINT_OPENABLE
        if hint != HINT_OPENABLE:
            continue
        rows.append(
            MissingPdf(
                key=key,
                title=item.title,
                doi=item.doi or "",
                url=url,
                hint=hint,
                attempts=attempts,
            )
        )
    rows.sort(key=lambda r: r.title.lower())
    return rows

def soft_attempts(attempts: list[str]) -> bool:
    return any(
        "download-failed(too small" in a or "download-failed(not a PDF" in a
        for a in attempts
    )


def write_missing_export(rows: list[MissingPdf], path: Path) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        lines = [
            "# Missing PDFs",
            "",
            "| Key | Title | DOI | URL | Hint |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in rows:
            title = row.title.replace("|", "\\|")
            lines.append(
                f"| {row.key} | {title} | {row.doi or '-'} | {row.url or '-'} | {row.hint} |"
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["key", "title", "doi", "url", "hint"])
        for row in rows:
            writer.writerow([row.key, row.title, row.doi, row.url, row.hint])
    return path


def openable_rows(rows: list[MissingPdf]) -> list[MissingPdf]:
    return [r for r in rows if r.hint == HINT_OPENABLE and r.open_url]


def open_tabs(
    rows: list[MissingPdf],
    *,
    include_doi_tabs: bool = False,
    confirm: Callable[[int], bool] | None = None,
    opener: Callable[[str], bool] | None = None,
) -> int:
    """Open URLs in the user's default browser. Returns how many tabs were opened."""
    targets = openable_rows(rows)
    if include_doi_tabs:
        extra = [
            r
            for r in rows
            if r.hint == HINT_DOI and r.open_url and r not in targets
        ]
        targets = targets + extra
    if not targets:
        return 0
    if len(targets) > TABS_CONFIRM_AFTER:
        ok = True if confirm is None else confirm(len(targets))
        if not ok:
            return 0
    open_fn = opener or webbrowser.open
    opened = 0
    for row in targets:
        if open_fn(row.open_url):
            opened += 1
    return opened


def newest_pdf_in_dir(directory: Path, *, after_ts: float | None = None) -> Path | None:
    """Newest ``*.pdf`` under ``directory`` (non-recursive), optionally after ``after_ts``."""
    if not directory.is_dir():
        return None
    newest: Path | None = None
    newest_mtime = -1.0
    for path in directory.glob("*.pdf"):
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if after_ts is not None and mtime < after_ts:
            continue
        if mtime >= newest_mtime:
            newest = path
            newest_mtime = mtime
    return newest


def attach_pdf_file(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    item: Item,
    pdf_path: Path,
    *,
    source: str = "manual",
) -> Record:
    """Copy a user PDF into ``out/``, attach it, and update the manifest."""
    path = pdf_path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    content = path.read_bytes()
    if not looks_like_pdf(content):
        raise ValueError(f"not a PDF: {path}")
    if len(content) < cfg.min_pdf_bytes:
        raise ValueError(f"too small ({len(content)} bytes): {path}")
    if not backend.supports_write():
        raise LibraryError("This library has no write support.")
    import hashlib

    md5 = hashlib.md5(content).hexdigest()
    primary, extras = save_pdf(cfg.out_dir, item, content, md5)
    note = provenance_stamp(source)
    res = backend.attach(item.key, primary, note=note)
    if not res.ok:
        raise LibraryError(res.reason or "attach failed")
    rec = Record(
        itemKey=item.key,
        status=STATUS_ATTACHED,
        title=item.title,
        doi=item.doi,
        url=item.url,
        path=str(primary.relative_to(cfg.out_dir)),
        extra_paths=relpaths(cfg.out_dir, extras),
        md5=md5,
        source=source,
        reason=res.reason or "manual",
        attempts=[f"{source}:attached"],
    )
    manifest.write(rec)
    return rec


@dataclass
class WalkResult:
    attached: int
    skipped: int
    quit_early: bool = False


def walk_missing(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    items_by_key: dict[str, Item],
    rows: list[MissingPdf],
    *,
    downloads_dir: Path,
    prompt: Callable[[str], str],
    opener: Callable[[str], bool] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> WalkResult:
    """Interactive open → download → ingest loop for ``openable_url`` rows."""
    open_fn = opener or webbrowser.open
    say = on_status or (lambda _msg: None)
    attached = skipped = 0
    targets = openable_rows(rows)
    for idx, row in enumerate(targets, start=1):
        item = items_by_key.get(row.key)
        if item is None:
            skipped += 1
            continue
        say(f"[{idx}/{len(targets)}] {row.key} — {row.title}")
        say(f"  opening {row.open_url}")
        opened_at = datetime.now(tz=timezone.utc).timestamp()
        open_fn(row.open_url)
        reply = prompt(
            "PDF path, Enter=newest in downloads dir, s=skip, q=quit: "
        ).strip()
        if reply.lower() in {"q", "quit"}:
            return WalkResult(attached=attached, skipped=skipped, quit_early=True)
        if reply.lower() in {"s", "skip"}:
            skipped += 1
            continue
        if reply:
            pdf = Path(reply).expanduser()
        else:
            pdf = newest_pdf_in_dir(downloads_dir, after_ts=opened_at - 2)
            if pdf is None:
                say("  no new PDF found in downloads dir")
                skipped += 1
                continue
            say(f"  using {pdf}")
        try:
            attach_pdf_file(cfg, backend, manifest, item, pdf)
        except (OSError, ValueError, LibraryError) as exc:
            say(f"  attach failed: {exc}")
            skipped += 1
            continue
        attached += 1
        say(f"  attached {row.key}")
    return WalkResult(attached=attached, skipped=skipped)
