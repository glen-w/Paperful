"""Deterministic IMRaD field extract from page text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..rag.chunk import _PAGE_BREAK, section_spans
from ..rag.questions import ExtractedQuestion, _qid, extract_rules
from .headings import MVP_CANONICALS, canonical_for_heading, named_headings_set

MIN_SECTION_BODY_CHARS = 80
_TOC_LINE = re.compile(r"^\.{3,}\s*\d+\s*$|^\d+\s*\.{3,}")


@dataclass
class SectionSlice:
    heading: str
    canonical: str | None
    body: str
    page_start: int
    page_end: int


@dataclass
class FieldValue:
    text: str
    provenance: str  # rule | llm
    heading: str | None = None
    pages: str = ""


@dataclass
class ExtractResult:
    sections: list[dict[str, Any]] = field(default_factory=list)
    fields: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    source: str = "none"  # pdf | abstract | none


def _page_offsets(pages: list[str]) -> tuple[str, list[int]]:
    cleaned = [p.replace("\r", "") for p in pages]
    starts: list[int] = []
    offset = 0
    for page in cleaned:
        starts.append(offset)
        offset += len(page) + len(_PAGE_BREAK)
    return _PAGE_BREAK.join(cleaned), starts


def _page_range(starts: list[int], body_start: int, body_end: int) -> str:
    if not starts:
        return ""
    from bisect import bisect_right

    def page_of(pos: int) -> int:
        return max(1, bisect_right(starts, pos))

    p0 = page_of(body_start)
    p1 = page_of(max(body_start, body_end - 1))
    return str(p0) if p0 == p1 else f"{p0}-{p1}"


def _body_usable(body: str) -> bool:
    text = re.sub(r"\s+", " ", body).strip()
    if len(text) < MIN_SECTION_BODY_CHARS:
        return False
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if not lines:
        return False
    tocish = sum(1 for ln in lines if _TOC_LINE.match(ln))
    if tocish >= max(3, len(lines) // 2):
        return False
    return True


def split_sections(pages: list[str], cfg: Config) -> list[SectionSlice]:
    text, starts = _page_offsets(pages)
    if not text.strip():
        return []
    out: list[SectionSlice] = []
    named = named_headings_set(cfg)
    for heading, body_start, body_end in section_spans(text, named):
        if heading is None:
            continue
        body = text[body_start:body_end].strip()
        if not _body_usable(body):
            continue
        out.append(
            SectionSlice(
                heading=heading,
                canonical=canonical_for_heading(heading, cfg),
                body=body,
                page_start=body_start,
                page_end=body_end,
            )
        )
    return out


def _pick_section_text(
    slices: list[SectionSlice], canonicals: tuple[str, ...]
) -> SectionSlice | None:
    for want in canonicals:
        for sl in slices:
            if sl.canonical == want:
                return sl
    return None


def extract_fields(
    cfg: Config,
    pages: list[str],
    *,
    record_abstract: str = "",
    mvp_fields: tuple[str, ...],
    raw_map: bool,
    max_field_chars: int,
) -> ExtractResult:
    slices = split_sections(pages, cfg)
    _, starts = _page_offsets(pages)

    result = ExtractResult()
    if pages:
        result.source = "pdf"
    elif record_abstract.strip():
        result.source = "abstract"

    if raw_map:
        for sl in slices:
            result.sections.append(
                {
                    "heading": sl.heading,
                    "canonical": sl.canonical,
                    "pages": _page_range(starts, sl.page_start, sl.page_end),
                }
            )

    fields: dict[str, Any] = {}
    missing: list[str] = []

    for name in mvp_fields:
        if name == "research_questions":
            rqs = extract_rules(pages, record_abstract)
            rq_section = _pick_section_text(slices, MVP_CANONICALS.get(name, ()))
            seen = {q.text for q in rqs}
            if rq_section and _body_usable(rq_section.body):
                for match in re.finditer(
                    r"(?m)^\s*(?:\(?[RQrq]\s*\d+\)?|\d+[\).]|[-*•])\s+(.+\?)\s*$",
                    rq_section.body,
                ):
                    text = match.group(1).strip()
                    if len(text) < 12 or text in seen:
                        continue
                    if not text.endswith("?"):
                        text = text.rstrip(".!;:") + "?"
                    seen.add(text)
                    rqs.append(
                        ExtractedQuestion(
                            id=_qid(text),
                            text=text,
                            provenance="rule",
                            pages=_page_range(
                                starts, rq_section.page_start, rq_section.page_end
                            ),
                        )
                    )
            if rqs:
                fields[name] = [
                    {
                        "id": q.id,
                        "text": q.text,
                        "provenance": q.provenance,
                        "pages": q.pages,
                    }
                    for q in rqs
                ]
            else:
                fields[name] = None
                missing.append(name)
            continue

        canonicals = MVP_CANONICALS.get(name, (name,))
        sl = _pick_section_text(slices, canonicals)
        if name == "abstract" and sl is None and record_abstract.strip():
            ab = record_abstract.strip()
            if len(ab) >= MIN_SECTION_BODY_CHARS:
                fields[name] = FieldValue(
                    text=ab[:max_field_chars],
                    provenance="rule",
                    heading=None,
                    pages="",
                )
                continue
        if sl is None or not _body_usable(sl.body):
            fields[name] = None
            missing.append(name)
            continue
        text = sl.body.strip()
        if len(text) > max_field_chars:
            text = text[:max_field_chars].rstrip() + "…"
        fields[name] = FieldValue(
            text=text,
            provenance="rule",
            heading=sl.heading,
            pages=_page_range(starts, sl.page_start, sl.page_end),
        )

    result.fields = _serialize_fields(fields)
    result.missing = missing
    return result


def _serialize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in fields.items():
        if val is None:
            out[key] = None
        elif isinstance(val, FieldValue):
            out[key] = {
                "text": val.text,
                "provenance": val.provenance,
                "heading": val.heading,
                "pages": val.pages,
            }
        else:
            out[key] = val
    return out


def stamp_provenance(result: ExtractResult, provenance: str) -> None:
    """Rewrite field provenance after a GROBID pass (leave empty slots alone)."""
    for name, val in list(result.fields.items()):
        if name == "research_questions" and isinstance(val, list):
            for row in val:
                if isinstance(row, dict) and row.get("text"):
                    row["provenance"] = provenance
            continue
        if isinstance(val, dict) and val.get("text"):
            val["provenance"] = provenance


def merge_llm_fields(
    result: ExtractResult,
    llm_fields: dict[str, Any],
    mvp_fields: tuple[str, ...],
) -> None:
    """Fill only empty MVP slots from LLM output."""
    for name in mvp_fields:
        current = result.fields.get(name)
        if name == "research_questions":
            if current:
                continue
            new = llm_fields.get(name)
            if isinstance(new, list) and new:
                result.fields[name] = new
                if name in result.missing:
                    result.missing.remove(name)
            continue
        if current is not None:
            continue
        new = llm_fields.get(name)
        if isinstance(new, dict) and new.get("text"):
            result.fields[name] = new
            if name in result.missing:
                result.missing.remove(name)
