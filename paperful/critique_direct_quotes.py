"""Heuristic direct-quotation spans in extracted manuscript text.

Prose linters, Vale, AI-tell heuristics, and suggested LLM comments should not
treat quoted speech or block quotations as the author's own prose to edit.
"""

from __future__ import annotations

import re
from functools import lru_cache

_SMART_OPEN = "\u201c"
_SMART_CLOSE = "\u201d"
_SMART_SQ_OPEN = "\u2018"
_SMART_SQ_CLOSE = "\u2019"
_GUIL_OPEN = "\u00ab"
_GUIL_CLOSE = "\u00bb"
_ASCII_DQ = '"'
_BLOCK_LINE = re.compile(r"^[ \t]*(>+\s*)(.*)$", re.MULTILINE)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged: list[tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _smart_pair_ranges(text: str, open_ch: str, close_ch: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != open_ch:
            i += 1
            continue
        j = text.find(close_ch, i + 1)
        if j == -1:
            break
        ranges.append((i, j + 1))
        i = j + 1
    return ranges


def _ascii_double_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != _ASCII_DQ:
            i += 1
            continue
        j = i + 1
        while j < n:
            if text[j] == _ASCII_DQ:
                ranges.append((i, j + 1))
                i = j + 1
                break
            j += 1
        else:
            i += 1
    return ranges


def _block_quote_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for m in _BLOCK_LINE.finditer(text):
        content_start = m.start(2)
        line_end = m.end()
        if content_start < line_end:
            ranges.append((content_start, line_end))
    return ranges


@lru_cache(maxsize=32)
def direct_quote_ranges(text: str) -> tuple[tuple[int, int], ...]:
    """Inclusive-start, exclusive-end offsets of direct-quotation regions."""
    if not text:
        return ()
    parts: list[tuple[int, int]] = []
    parts.extend(_smart_pair_ranges(text, _SMART_OPEN, _SMART_CLOSE))
    parts.extend(_smart_pair_ranges(text, _SMART_SQ_OPEN, _SMART_SQ_CLOSE))
    parts.extend(_smart_pair_ranges(text, _GUIL_OPEN, _GUIL_CLOSE))
    parts.extend(_ascii_double_ranges(text))
    parts.extend(_block_quote_ranges(text))
    return tuple(_merge_ranges(parts))


def span_in_direct_quote(text: str, start: int, end: int) -> bool:
    """True when ``[start, end)`` lies entirely inside one quotation region."""
    if start < 0 or end <= start:
        return False
    for qs, qe in direct_quote_ranges(text):
        if start >= qs and end <= qe:
            return True
    return False


def offset_in_direct_quote(text: str, offset: int) -> bool:
    if offset < 0:
        return False
    for qs, qe in direct_quote_ranges(text):
        if qs <= offset < qe:
            return True
    return False


def snippet_in_direct_quote(text: str, snippet: str) -> bool:
    """True when ``snippet`` occurs in ``text`` only inside quotation regions.

    If it appears both inside and outside quotes, returns False so we do not
    drop a legitimate comment on the author's paraphrase.
    """
    snippet = (snippet or "").strip()
    if not snippet or not text:
        return False
    in_quote = False
    outside = False
    pos = 0
    while True:
        idx = text.find(snippet, pos)
        if idx == -1:
            break
        end = idx + len(snippet)
        if span_in_direct_quote(text, idx, end):
            in_quote = True
        else:
            outside = True
        pos = idx + 1
    if in_quote and not outside:
        return True
    if in_quote and outside:
        return False
    return False


def elide_direct_quotes(text: str) -> str:
    """Replace quoted regions with spaces (preserve newlines) for stylometry."""
    ranges = direct_quote_ranges(text)
    if not ranges:
        return text
    chars = list(text)
    for start, end in ranges:
        for i in range(start, min(end, len(chars))):
            if chars[i] not in "\n":
                chars[i] = " "
    return "".join(chars)


def line_column_span_in_direct_quote(
    text: str, line: int, start_col: int, end_col: int
) -> bool:
    """Vale-style 1-based line and 1-based inclusive column span."""
    if line < 1 or start_col < 1 or end_col < start_col:
        return False
    lines = text.splitlines(keepends=True)
    if line > len(lines):
        return False
    offset = sum(len(lines[i]) for i in range(line - 1))
    row = lines[line - 1]
    row_body = row.rstrip("\r\n")
    start = offset + start_col - 1
    end = offset + min(end_col, len(row_body))
    return span_in_direct_quote(text, start, end)
