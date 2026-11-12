"""Outline plan-review suggested lane. No scores.

One JSON turn over a section-packed excerpt. The document is a plan, not a
finished manuscript. Comments are grounded the same way as reviewers.
Suggested lane only.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from hashlib import sha256
from typing import Any

from .config import Config
from .critique import Finding, make_finding
from .critique_extract import ExtractedDoc, loc_of_span
from .critique_llm import findings_from_comments, grounded, parse_llm_json
from .grounding import budget_slice
from .zot import Item

THIN_WORDS = 12
THIN_CAP = 8
_SKIP_CHECKED = frozenset({"missing_section", "missing_mention"})

_SYSTEM = """You review an OUTLINE (a plan for a paper), not a finished manuscript.
Use ONLY the title, section skeleton, excerpt, and checked findings. Do not invent citations, data, or methods.
Do not penalize missing prose, unwritten results, or absent ethics/funding/COI sentences — those are expected in a plan.
Return JSON only:
{
  "summary": "one paragraph of the planned move, as sharply as the outline allows, and what would have to be true for it to hold",
  "comments": [
    {"code": "outline_claim|outline_warrant|outline_gap|outline_scope|outline_balance|outline_evidence|outline_audience|outline_sequence", "quote": "span from the excerpt", "detail": "pressure on that span"}
  ]
}
Cover, as far as the excerpt allows:
- outline_claim: core claim or research question underspecified or incompatible with another
- outline_warrant: missing theoretical, legal, or policy warrant
- outline_gap: the argument needs a section that is not in the plan
- outline_scope: too many questions or too broad for the stated length
- outline_balance: length allocation vs how much work that section must do
- outline_evidence: planned sources, tables, or figures do not actually carry the point
- outline_audience: audience or register mismatch with the section plan
- outline_sequence: section order does not build the argument
Rules:
- Quotes MUST be substrings of the excerpt.
- At most 8 comments. Prefer fewer sharp questions over a laundry list.
- No score, grade, or accept/reject.
- Do not claim plagiarism or misconduct.
- Do not treat unwritten sections as defects.
- Label opinion as opinion when you go beyond the checkers.
"""


def outline_slices(text: str, cfg: Config | None = None) -> list[tuple[str, str]]:
    """``(heading, body)`` spans, including short outline subsections."""
    from .rag.chunk import section_spans
    from .sections.headings import named_headings_set

    named = named_headings_set(cfg) if cfg is not None else None
    out: list[tuple[str, str]] = []
    for heading, start, end in section_spans(text, named):
        body = text[start:end].strip()
        if not heading and not body:
            continue
        out.append(((heading or "").strip(), body))
    return merge_duplicate_headings(out)


def merge_duplicate_headings(
    slices: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Join repeated headings (TOC blurb + later full section) in first-seen order."""
    order: list[str] = []
    bodies: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for heading, body in slices:
        key = heading or "Preamble"
        if key not in bodies:
            order.append(key)
            labels[key] = heading
            bodies[key] = []
        chunk = (body or "").strip()
        if chunk:
            bodies[key].append(chunk)
    return [(labels[key], "\n\n".join(bodies[key])) for key in order]


def outline_ledger(
    slices: list[tuple[str, str]], cfg: Config | None = None
) -> list[dict[str, Any]]:
    """Heading / word-count rows for pack.json."""
    from .sections.headings import canonical_for_heading

    rows: list[dict[str, Any]] = []
    for heading, body in slices:
        words = len(body.split())
        label = heading or "Preamble"
        row: dict[str, Any] = {"heading": label, "words": words}
        canon = canonical_for_heading(heading, cfg) if heading else None
        if canon:
            row["canonical"] = canon
        rows.append(row)
    return rows


def pack_outline_excerpt(
    text: str,
    slices: list[tuple[str, str]],
    max_chars: int,
) -> str:
    """Keep every section in budget instead of head-plus-tail."""
    blob = (text or "").strip()
    cap = max(500, int(max_chars or 24_000))
    if not slices:
        return budget_slice(blob, cap)
    if len(blob) <= cap:
        return blob
    titles = [h or "Preamble" for h, _ in slices]
    header = "Outline sections:\n" + "\n".join(f"- {t}" for t in titles)
    leftover = cap - len(header) - 4
    if leftover < 400:
        return (header + "\n\n" + blob)[:cap]
    n = len(slices)
    parts = [header]
    for i, (heading, body) in enumerate(slices):
        remain_n = n - i
        budget = max(80, leftover // remain_n) if remain_n else leftover
        chunk = body.strip()
        if len(chunk) > budget:
            chunk = chunk[: max(0, budget - 1)].rstrip() + "…"
        block = f"## {heading}\n{chunk}" if heading else chunk
        parts.append(block)
        leftover -= len(block) + 2
        if leftover <= 0:
            break
    packed = "\n\n".join(parts)
    return packed if len(packed) <= cap else packed[:cap]


def _thin_findings(doc: ExtractedDoc, slices: list[tuple[str, str]]) -> list[Finding]:
    extra: list[Finding] = []
    for heading, body in slices:
        if not heading:
            continue
        words = len(body.split())
        if words >= THIN_WORDS:
            continue
        extra.append(
            make_finding(
                code="outline_thin",
                severity="info",
                lane="suggested",
                loc=loc_of_span(doc, heading),
                quote=heading,
                detail=(
                    f"Section {heading!r} is named but barely planned "
                    f"({words} word(s) of body)."
                ),
                source="rule",
                extra={"reviewer": "outline", "words": words},
            )
        )
        if len(extra) >= THIN_CAP:
            break
    return extra


def suggested_from_outline(
    cfg: Config,
    doc: ExtractedDoc,
    findings: list[Finding],
    *,
    item: Item | None,
    client: Any,
    hay: str,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[Finding], dict[str, Any]]:
    """One JSON plan-review turn plus a deterministic section skeleton."""
    say = on_status or (lambda _msg: None)
    model = cfg.llm_model
    slices = outline_slices(doc.text, cfg)
    ledger = outline_ledger(slices, cfg)
    thin = _thin_findings(doc, slices)
    excerpt = pack_outline_excerpt(
        doc.text, slices, int(cfg.critique_max_context_chars or 24_000)
    )
    packed_hay = excerpt.lower() or (hay or "")
    cap = max(1, int(getattr(cfg, "critique_outline_max_comments", 12) or 12))
    timeout_s = float(cfg.llm_timeout_s or 120)
    meta: dict[str, Any] = {
        "id": "outline",
        "model": model,
        "calls": 0,
        "ledger": ledger,
    }
    if not excerpt.strip():
        meta["skipped"] = "empty_extract"
        meta["reviewers"] = [
            {"id": "outline", "model": model, "skipped": "empty_extract"}
        ]
        return thin, meta

    title = (item.title if item is not None else "") or ""
    checked = [
        {
            "code": f.code,
            "severity": f.severity,
            "loc": f.loc,
            "quote": f.quote,
            "detail": f.detail,
        }
        for f in findings
        if f.lane == "checked" and not f.dismissed and f.code not in _SKIP_CHECKED
    ][:40]
    skeleton_md = "\n".join(
        f"- {row['heading']} ({row['words']} words)"
        + (f" [{row['canonical']}]" if row.get("canonical") else "")
        for row in ledger
    )
    user = (
        f"Title: {title}\n\n"
        "This document is an OUTLINE (a plan), not a finished manuscript.\n\n"
        f"Section skeleton:\n{skeleton_md or '(no headings detected)'}\n\n"
        f"Excerpt:\n{excerpt}\n\nChecked findings:\n"
        + json.dumps(checked, ensure_ascii=False)
    )
    prompt_sha = sha256((_SYSTEM + user[:2000]).encode("utf-8")).hexdigest()[:12]
    meta["prompt_sha"] = prompt_sha
    say("Outline lane…")
    from .critique_llm import chat_with_json_retry, critique_chat_request

    request = critique_chat_request(
        model=model,
        messages=(
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ),
        timeout_seconds=timeout_s,
        temperature=0.2,
        json_mode=True,
    )
    t0 = time.perf_counter()
    try:
        raw = chat_with_json_retry(client, request, on_status=say, label="Outline")
    except Exception as exc:
        meta["skipped"] = "llm_error"
        meta["error"] = str(exc)
        meta["reviewers"] = [
            {
                "id": "outline",
                "model": model,
                "prompt_sha": prompt_sha,
                "skipped": "llm_error",
                "error": str(exc),
            }
        ]
        failed = [
            make_finding(
                code="llm_failed",
                severity="info",
                lane="suggested",
                detail=f"Outline lane failed: {exc}",
                source="llm",
                extra={"reviewer": "outline"},
            )
        ]
        return thin + failed, meta
    meta["calls"] = 1
    data = parse_llm_json(raw) or {}
    extra = findings_from_comments(
        data.get("comments"),
        hay=packed_hay,
        reviewer_id="outline",
        source="llm",
        limit=cap,
    )
    summary = str(data.get("summary") or "").strip()
    narrative = ""
    if summary and grounded(summary, packed_hay):
        narrative = summary[:4000]
        extra.insert(
            0,
            make_finding(
                code="llm_summary",
                severity="info",
                lane="suggested",
                detail=summary[:500],
                quote=summary[:200],
                source="llm",
                extra={"reviewer": "outline"},
            ),
        )
        extra = extra[:cap]
    dt = time.perf_counter() - t0
    bits = [f"{dt:.0f}s"]
    if extra:
        bits.append(f"{len(extra)} comment(s)")
    if thin:
        bits.append(f"{len(thin)} thin section(s)")
    if narrative:
        bits.append("note")
    say(f"Outline lane done ({', '.join(bits)})")
    reviewer_row: dict[str, Any] = {
        "id": "outline",
        "model": model,
        "prompt_sha": prompt_sha,
    }
    if narrative:
        meta["narrative"] = narrative
        reviewer_row["narrative"] = narrative
    if not extra and not narrative and not thin:
        meta["skipped"] = "empty_reply"
        reviewer_row["skipped"] = "empty_reply"
    meta["reviewers"] = [reviewer_row]
    return thin + extra, meta
