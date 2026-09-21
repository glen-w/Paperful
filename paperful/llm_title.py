"""Grounded LLM title proposals."""

from __future__ import annotations

import re

from .config import Config
from .grounding import metadata_block, pdf_text_for
from .library import LibraryBackend
from .llm import CompletionRequest, get_client
from .metadata import Patch
from .store import Manifest
from .zot import Item

_TITLE_CODES = frozenset({"title_all_caps", "title_html", "title_filename"})


def propose_llm_title(
    cfg: Config,
    item: Item,
    codes: set[str],
    manifest: Manifest | None,
    backend: LibraryBackend | None,
) -> Patch | None:
    if not cfg.llm_enabled or not cfg.fix_metadata_llm_title:
        return None
    if not _TITLE_CODES.intersection(codes):
        return None
    body = pdf_text_for(cfg, item, manifest, backend, max_pages=2)
    if not body.strip() and not item.abstract:
        return None
    client = get_client(cfg)
    prompt = (
        "Propose a cleaned bibliographic title for this work. "
        'Reply with JSON only: {"title": "..."}. '
        "Use the metadata and PDF excerpt; do not invent authors or DOI.\n\n"
        f"{metadata_block(item)}\n\nPDF excerpt:\n{body[:8000]}"
    )
    try:
        data = client.complete_json(
            CompletionRequest(
                model=cfg.llm_model,
                prompt=prompt,
                timeout_seconds=cfg.llm_timeout_s,
                json_mode=True,
            )
        )
    except Exception:
        return None
    title = str(data.get("title") or "").strip()
    if not title or title == item.title:
        return None
    if not _grounded(title, item.title, body):
        return None
    return Patch(
        itemKey=item.key,
        title=item.title,
        before={"title": item.title},
        after={"title": title},
        source="llm_title",
    )


def _grounded(proposed: str, old: str, pdf_text: str) -> bool:
    words = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", proposed)}
    if not words:
        return False
    hay = f"{old}\n{pdf_text}".lower()
    hits = sum(1 for w in words if w in hay)
    return hits >= min(2, len(words))
