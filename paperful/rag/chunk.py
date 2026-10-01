"""Split page text into passages that keep their section and page range."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass

CHUNKER_VERSION = 1
MIN_CHUNK_CHARS = 100
_PAGE_BREAK = "\n\n"
# Coarsest first: paragraphs, lines, sentences, words.
_SEPARATORS = ("\n\n", "\n", ". ", " ")
_MARKDOWN_HEADING = re.compile(r"^#{1,4}\s+(\S.*)$")
_NUMBERED_HEADING = re.compile(
    r"^\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+[A-Z][A-Za-z]{2,}[^\n]{0,90}$"
)
_CAPS_HEADING = re.compile(r"^[A-Z][A-Z0-9 ,&:\-]{3,70}$")
_NAMED_HEADINGS = frozenset(
    {
        "abstract",
        "summary",
        "introduction",
        "background",
        "methods",
        "methodology",
        "materials and methods",
        "results",
        "discussion",
        "results and discussion",
        "conclusion",
        "conclusions",
        "acknowledgements",
        "acknowledgments",
        "references",
        "bibliography",
        "appendix",
    }
)
_HYPHEN_BREAK = re.compile(r"(?<=[a-z])-\n(?=[a-z])")
_BLANK_RUN = re.compile(r"\n{3,}")
# A heading-like line seen this often is a running page header, not a section.
_RUNNING_HEADER_REPEATS = 3
_SENTENCE_START = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    section: str | None
    page_start: int
    page_end: int


def _clean_page(page: str) -> str:
    lines = [line.rstrip() for line in page.replace("\r", "").split("\n")]
    text = "\n".join(lines).strip("\n")
    text = _HYPHEN_BREAK.sub("", text)
    return _BLANK_RUN.sub("\n\n", text)


def _heading(line: str, prev_blank: bool) -> str | None:
    """The heading text if ``line`` reads as a section heading."""
    stripped = line.strip()
    markdown = _MARKDOWN_HEADING.match(stripped)
    if markdown:
        return markdown.group(1).strip().strip("#").strip()
    if not prev_blank or not stripped or len(stripped) > 100:
        return None
    if stripped.lower().rstrip(":") in _NAMED_HEADINGS:
        return stripped.rstrip(":")
    if stripped.endswith((".", ",", ";")) or len(stripped.split()) > 12:
        return None
    if _NUMBERED_HEADING.match(stripped):
        return stripped
    if _CAPS_HEADING.match(stripped):
        letters = sum(c.isalpha() for c in stripped)
        if letters >= 4 and letters >= 0.6 * len(stripped.replace(" ", "")):
            return stripped
    return None


def _sections(text: str) -> list[tuple[str | None, int, int]]:
    """``(heading, body_start, body_end)`` spans covering the text in order."""
    lines = text.split("\n")
    titles: list[str | None] = []
    prev_blank = True
    for line in lines:
        titles.append(_heading(line, prev_blank))
        prev_blank = not line.strip()
    seen = Counter(title for title in titles if title is not None)
    spans: list[tuple[str | None, int, int]] = []
    current: str | None = None
    body_start = 0
    offset = 0
    for line, title in zip(lines, titles):
        if title is not None and seen[title] >= _RUNNING_HEADER_REPEATS:
            title = None
        if title is not None:
            if text[body_start:offset].strip():
                spans.append((current, body_start, offset))
            current = title
            body_start = offset + len(line) + 1
        offset += len(line) + 1
    end = len(text)
    if text[min(body_start, end) : end].strip():
        spans.append((current, min(body_start, end), end))
    return spans


def _split(text: str, start: int, end: int, limit: int, depth: int = 0) -> list[tuple[int, int]]:
    """Contiguous spans of at most ``limit`` chars, cut at the coarsest separator that fits."""
    if end - start <= limit:
        return [(start, end)]
    if depth >= len(_SEPARATORS):
        return [(s, min(s + limit, end)) for s in range(start, end, limit)]
    sep = _SEPARATORS[depth]
    parts: list[tuple[int, int]] = []
    cursor = start
    while True:
        hit = text.find(sep, cursor, end)
        if hit == -1:
            break
        parts.append((cursor, hit + len(sep)))
        cursor = hit + len(sep)
    if cursor < end:
        parts.append((cursor, end))
    if len(parts) <= 1:
        return _split(text, start, end, limit, depth + 1)
    spans: list[tuple[int, int]] = []
    open_start: int | None = None
    open_end = start
    for part_start, part_end in parts:
        if open_start is not None and part_end - open_start <= limit:
            open_end = part_end
            continue
        if open_start is not None:
            spans.append((open_start, open_end))
            open_start = None
        if part_end - part_start <= limit:
            open_start, open_end = part_start, part_end
        else:
            spans.extend(_split(text, part_start, part_end, limit, depth + 1))
    if open_start is not None:
        spans.append((open_start, open_end))
    return spans


def _overlap_start(text: str, prev_start: int, prev_end: int, overlap: int) -> int:
    """Where the tail of the previous span begins, moved forward to a sentence or word."""
    if overlap <= 0:
        return prev_end
    begin = max(prev_start, prev_end - overlap)
    if begin == prev_start:
        return begin
    sentence = _SENTENCE_START.search(text, begin, prev_end)
    if sentence:
        return sentence.end()
    space = text.find(" ", begin, prev_end)
    return space + 1 if space != -1 else begin


def chunk_pages(
    pages: list[str],
    *,
    chunk_chars: int = 2048,
    overlap: int = 256,
    min_chars: int = MIN_CHUNK_CHARS,
) -> list[Chunk]:
    """Split a document into passages of at most ``chunk_chars`` characters.

    Passages never cross a section heading. Each one after the first in its
    section starts with the closing sentences of the one before. Page numbers
    are 1-based and cover the overlap too.
    """
    cleaned = [_clean_page(page) for page in pages]
    starts: list[int] = []
    offset = 0
    for page in cleaned:
        starts.append(offset)
        offset += len(page) + len(_PAGE_BREAK)
    text = _PAGE_BREAK.join(cleaned)
    overlap = max(0, min(overlap, chunk_chars // 2))
    limit = max(1, chunk_chars - overlap)

    def page_of(position: int) -> int:
        return max(1, bisect_right(starts, position))

    chunks: list[Chunk] = []
    for heading, body_start, body_end in _sections(text):
        spans = _split(text, body_start, body_end, limit)
        for i, (span_start, span_end) in enumerate(spans):
            begin = span_start
            if i > 0:
                prev_start, prev_end = spans[i - 1]
                begin = _overlap_start(text, prev_start, prev_end, overlap)
            raw = text[begin:span_end]
            body = raw.strip()
            if len(body) < min_chars:
                continue
            first = begin + (len(raw) - len(raw.lstrip()))
            last = begin + len(raw.rstrip()) - 1
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=body,
                    section=heading,
                    page_start=page_of(first),
                    page_end=page_of(last),
                )
            )
    return chunks


def embed_text(chunk: Chunk, title: str) -> str:
    """What the embedding model sees: the passage under its paper and section titles."""
    parts = [part for part in (title.strip(), (chunk.section or "").strip()) if part]
    parts.append(chunk.text)
    return "\n\n".join(parts)
