"""PDF text grounding for LLM verbs (disk-first)."""

from __future__ import annotations

import re
from pathlib import Path

from .config import Config
from .library import LibraryBackend
from .lint import resolve_pdf_path
from .pdfid import text_from_pdf
from .store import Manifest
from .zot import Item

_HEADING = re.compile(r"^(?:\d+\.?\s+|[A-Z][A-Z0-9 \-]{3,60})$", re.M)


def pdf_text_for(
    cfg: Config,
    item: Item,
    manifest: Manifest | None,
    backend: LibraryBackend | None,
    *,
    max_pages: int | None = 2,
) -> str:
    path = resolve_pdf_path(cfg, item, manifest)
    if path is None and item.has_pdf and backend is not None:
        dest = cfg.pdf_cache_dir / f"{item.key}.pdf"
        path = backend.export_pdf(item, dest)
        if path:
            item.pdf_path = str(path)
    if not path or not path.is_file():
        return ""
    return text_from_pdf(path, max_pages=max_pages)


def budget_slice(text: str, max_chars: int) -> str:
    """Head + detected headings + tail within a character budget."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head_len = max_chars // 3
    tail_len = max_chars // 3
    mid_budget = max_chars - head_len - tail_len
    head = text[:head_len]
    tail = text[-tail_len:]
    headings: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line and _HEADING.match(line) and line not in headings:
            headings.append(line)
        if sum(len(h) for h in headings) > mid_budget:
            break
    mid = "\n".join(headings[:20])
    return f"{head}\n\n[…]\n\n{mid}\n\n[…]\n\n{tail}"


def metadata_block(item: Item) -> str:
    lines = [f"Title: {item.title}"]
    if item.creator_surnames:
        lines.append(f"Authors: {', '.join(item.creator_surnames[:12])}")
    if item.year:
        lines.append(f"Year: {item.year}")
    if item.doi:
        lines.append(f"DOI: {item.doi}")
    if item.abstract:
        lines.append(f"Abstract: {item.abstract[:2000]}")
    return "\n".join(lines)
