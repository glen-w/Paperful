"""Inbox match ladder and gated create/attach proposals."""

from __future__ import annotations

import json
import re
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .dedupe import normalize_dedupe_title
from .handoff import MissingPdf
from .pdfid import doi_from_pdf, text_from_pdf
from .resolve import normalize_doi
from .identity import publication_year
from .zot import Item

SCHEMA = "paperful.inbox.proposal.v1"
TAG_CREATED = "inbox-created"
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_JUNK_STEMS = frozenset(
    {
        "download",
        "fulltext",
        "full-text",
        "untitled",
        "document",
        "paper",
        "file",
        "scan",
        "image",
        "img",
        "microsoft",
        "unknown",
    }
)
MATCH_PRESETS = {
    "doi_only": ("doi", "fifo"),
    "doi+title": ("doi", "title_fingerprint", "fifo"),
    "doi+title+ocr": ("doi", "ocr", "title_fingerprint", "fifo"),
    "full": ("doi", "ocr", "title_fingerprint", "title_resolve", "llm", "fifo"),
}


@dataclass
class MatchResult:
    item: Item | None
    how: str  # doi | fifo | title_fingerprint | title_resolve | ocr | llm | none
    doi: str | None = None
    reason: str = ""
    title: str = ""
    year: int | None = None
    confidence: float | None = None
    text: str = ""


def stages_for(cfg: Config) -> tuple[str, ...]:
    return MATCH_PRESETS.get(cfg.inbox_match, MATCH_PRESETS["doi_only"])


def build_doi_index(items: list[Item]) -> dict[str, Item]:
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


def build_title_year_index(items: list[Item]) -> dict[tuple[str, int], Item | None]:
    """Unique missing-PDF title+year. Ambiguous keys map to None."""
    counts: dict[tuple[str, int], list[Item]] = {}
    for item in items:
        if item.has_pdf:
            continue
        title = normalize_dedupe_title(item.title)
        year = publication_year(item.year)
        if not title or year is None:
            continue
        counts.setdefault((title, year), []).append(item)
    return {
        key: (rows[0] if len(rows) == 1 else None) for key, rows in counts.items()
    }


def pdf_title_year(path: Path, text: str = "") -> tuple[str, int | None]:
    from .pdfid import _pypdf_title

    meta = (_pypdf_title(path) or "").strip()
    body = text or text_from_pdf(path, max_pages=2)
    year = None
    for match in _YEAR_RE.finditer(f"{meta}\n{body}\n{path.stem}"):
        year = int(match.group(1))
        break
    title = meta
    if not title or _looks_like_doi(title) or _junk_stem(title):
        title = _first_title_line(body) or ""
    if not title or _junk_stem(title):
        stem = path.stem.replace("_", " ").replace("-", " ").strip()
        title = "" if _junk_stem(stem) else stem
    return title, year


def match_ladder(
    path: Path,
    *,
    cfg: Config,
    doi_index: dict[str, Item],
    title_index: dict[tuple[str, int], Item | None],
    fifo_queue: deque[MissingPdf] | None = None,
    items_by_key: dict[str, Item] | None = None,
    missing_items: list[Item] | None = None,
    llm_match: Callable | None = None,
    title_resolve: Callable | None = None,
    ocr_text: Callable | None = None,
) -> MatchResult:
    stages = stages_for(cfg)
    text = text_from_pdf(path, max_pages=2)
    doi = doi_from_pdf(path)
    title, year = pdf_title_year(path, text)

    if "doi" in stages and doi:
        item = doi_index.get(doi)
        if item is not None:
            return MatchResult(item=item, how="doi", doi=doi, title=title, year=year, text=text)
        doi_miss = f"no missing-PDF item for DOI {doi}"
    else:
        doi_miss = "no DOI in PDF"

    if "ocr" in stages and (cfg.inbox_ocr_for_match or cfg.inbox_match in {"doi+title+ocr", "full"}):
        if _thin(text) and ocr_text is not None:
            extra = ocr_text(path) or ""
            if extra.strip():
                text = extra
                if not doi:
                    from .resolve import DOI_RE

                    m = DOI_RE.search(text)
                    if m:
                        doi = normalize_doi(m.group(1))
                        item = doi_index.get(doi) if doi else None
                        if item is not None:
                            return MatchResult(
                                item=item, how="ocr", doi=doi, title=title, year=year, text=text
                            )
                title, year = pdf_title_year(path, text)

    if "title_fingerprint" in stages and title and year is not None:
        key = (normalize_dedupe_title(title), year)
        item = title_index.get(key)
        if item is None and key in title_index:
            return MatchResult(
                item=None,
                how="none",
                doi=doi,
                title=title,
                year=year,
                text=text,
                reason="ambiguous title+year",
            )
        if item is not None:
            return MatchResult(
                item=item,
                how="title_fingerprint",
                doi=doi or normalize_doi(item.doi),
                title=title,
                year=year,
                text=text,
            )

    if "title_resolve" in stages and cfg.inbox_title_resolve and title_resolve and title:
        resolved = title_resolve(title, year)
        doi_r = normalize_doi(getattr(resolved, "doi", None) if resolved else None)
        if doi_r:
            item = doi_index.get(doi_r)
            if item is not None:
                return MatchResult(
                    item=item,
                    how="title_resolve",
                    doi=doi_r,
                    title=title,
                    year=year,
                    text=text,
                )

    if _want_llm(cfg) and llm_match is not None and missing_items:
        hit = llm_match(path, text, missing_items)
        if hit is not None:
            return hit

    if "fifo" in stages and fifo_queue is not None and items_by_key is not None:
        while fifo_queue:
            row = fifo_queue.popleft()
            item = items_by_key.get(row.key)
            if item is None or item.has_pdf:
                continue
            return MatchResult(
                item=item,
                how="fifo",
                doi=normalize_doi(item.doi),
                title=title,
                year=year,
                text=text,
            )
    reason = doi_miss
    if title:
        reason = f"{doi_miss}; title {title!r}"
    return MatchResult(
        item=None, how="none", doi=doi, title=title, year=year, text=text, reason=reason
    )


def match_pdf(
    path: Path,
    *,
    doi_index: dict[str, Item],
    fifo_queue: deque[MissingPdf] | None = None,
    items_by_key: dict[str, Item] | None = None,
    cfg: Config | None = None,
    title_index: dict[tuple[str, int], Item | None] | None = None,
    missing_items: list[Item] | None = None,
    llm_match: Callable | None = None,
    title_resolve: Callable | None = None,
    ocr_text: Callable | None = None,
) -> MatchResult:
    """DOI from the PDF first; optional FIFO of openable misses as fallback."""
    if cfg is None:
        cfg = Config()
        cfg.inbox_match = "doi_only"
    return match_ladder(
        path,
        cfg=cfg,
        doi_index=doi_index,
        title_index=title_index or {},
        fifo_queue=fifo_queue,
        items_by_key=items_by_key,
        missing_items=missing_items,
        llm_match=llm_match,
        title_resolve=title_resolve,
        ocr_text=ocr_text,
    )


def write_proposal(cfg: Config, payload: dict) -> Path:
    folder = cfg.inbox_proposals_dir
    folder.mkdir(parents=True, exist_ok=True)
    pid = str(payload.get("id") or uuid.uuid4().hex[:12])
    payload.setdefault("schema", SCHEMA)
    payload["id"] = pid
    payload.setdefault("status", "pending")
    payload.setdefault("created_at", datetime.now(tz=timezone.utc).isoformat())
    dest = folder / f"{pid}.json"
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest


def list_proposals(cfg: Config, *, status: str | None = "pending") -> list[dict]:
    folder = cfg.inbox_proposals_dir
    if not folder.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if status and data.get("status") != status:
            continue
        data["_path"] = str(path)
        rows.append(data)
    return rows


def load_proposal(cfg: Config, proposal_id: str) -> dict:
    path = cfg.inbox_proposals_dir / f"{proposal_id}.json"
    if not path.is_file():
        raise FileNotFoundError(proposal_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_path"] = str(path)
    return data


def save_proposal(data: dict) -> None:
    path = Path(data["_path"])
    payload = {k: v for k, v in data.items() if k != "_path"}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class HoldLedger:
    """First-seen times so unmatched PDFs can wait before quarantine."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._rows: dict[str, dict] = {}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = {}
            if isinstance(raw, dict):
                self._rows = raw

    def first_seen(self, fingerprint: str, *, now: float) -> float:
        row = self._rows.get(fingerprint)
        if isinstance(row, dict) and "first_seen" in row:
            try:
                return float(row["first_seen"])
            except (TypeError, ValueError):
                pass
        self._rows[fingerprint] = {"first_seen": now}
        self._flush()
        return now

    def drop(self, fingerprint: str) -> None:
        if fingerprint in self._rows:
            del self._rows[fingerprint]
            self._flush()

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._rows, indent=2) + "\n", encoding="utf-8")


def _want_llm(cfg: Config) -> bool:
    if not cfg.llm_enabled:
        return False
    if cfg.inbox_llm_match == "always":
        return True
    if cfg.inbox_llm_match == "when_thin":
        return True
    return cfg.inbox_match == "full"


def _thin(text: str) -> bool:
    return sum(1 for ch in text if ch.isalnum()) < 40


def _looks_like_doi(text: str) -> bool:
    return bool(normalize_doi(text))


def _junk_stem(text: str) -> bool:
    token = re.sub(r"[^a-z0-9]+", "", text.lower())
    return token in _JUNK_STEMS or len(text.strip()) < 8


def _first_title_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 12 and not _looks_like_doi(line):
            return line[:200]
    return ""
