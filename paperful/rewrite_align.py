"""Bind a critique finding to a unique span in the current manuscript."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Alignment:
    """A unique location in the manuscript for one finding."""

    quote: str
    loc: str
    start: int
    end: int
    paragraph: str
    paragraph_index: int


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _find_unique(hay: str, needle: str) -> tuple[int, int] | None:
    """Return (start, end) when ``needle`` occurs exactly once, else None."""
    token = _norm(needle)
    if not token or len(token) < 3:
        return None
    # Prefer exact, then case-insensitive on the original haystack.
    count = hay.count(needle)
    if count == 1:
        start = hay.index(needle)
        return start, start + len(needle)
    if count == 0:
        lower = hay.lower()
        raw = needle.lower()
        n = lower.count(raw)
        if n == 1:
            start = lower.index(raw)
            return start, start + len(needle)
    return None


def _paragraph_for(paragraphs: list[str], quote: str) -> tuple[int, str]:
    hits = [i for i, p in enumerate(paragraphs) if quote and quote in p]
    if len(hits) == 1:
        i = hits[0]
        return i, paragraphs[i]
    if not hits and quote:
        q = quote.lower()
        hits = [i for i, p in enumerate(paragraphs) if q in p.lower()]
        if len(hits) == 1:
            i = hits[0]
            return i, paragraphs[i]
    return -1, ""


def _heading_like(paragraphs: list[str], loc: str) -> tuple[int, str]:
    token = _norm(loc)
    if not token:
        return -1, ""
    # loc is often "paragraph 3" or "page 2".
    m = re.search(r"paragraph\s+(\d+)", token, re.I)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(paragraphs):
            return idx, paragraphs[idx]
    lowered = token.lower()
    hits = [
        i
        for i, p in enumerate(paragraphs)
        if p.strip().lower() == lowered or p.strip().lower().startswith(lowered)
    ]
    if len(hits) == 1:
        i = hits[0]
        return i, paragraphs[i]
    return -1, ""


def align_finding(
    finding: dict[str, Any],
    *,
    text: str,
    paragraphs: list[str] | None = None,
) -> Alignment | str:
    """Return an Alignment, or a skip reason string."""
    paras = [p for p in (paragraphs or []) if p]
    quote = str(finding.get("quote") or "").strip()
    loc = str(finding.get("loc") or "").strip()
    span = _find_unique(text, quote) if quote else None
    p_idx, para = _paragraph_for(paras, quote) if quote else (-1, "")
    if span is None and quote:
        exact = text.count(quote)
        folded = 0 if exact else text.lower().count(quote.lower())
        if exact > 1 or folded > 1:
            return "no_unique_span"
    if span is None and loc:
        p_idx, para = _heading_like(paras, loc)
        if para:
            # Bind the whole paragraph when the quote is missing.
            start = text.find(para)
            if start >= 0 and text.count(para) == 1:
                span = (start, start + len(para))
                quote = quote or para[:200]
    if span is None:
        return "no_unique_span"
    start, end = span
    if p_idx < 0 and paras:
        p_idx, para = _paragraph_for(paras, text[start:end])
    return Alignment(
        quote=quote or text[start:end],
        loc=loc or (f"paragraph {p_idx + 1}" if p_idx >= 0 else ""),
        start=start,
        end=end,
        paragraph=para or text[start:end],
        paragraph_index=p_idx,
    )
