"""Library n-gram overlap checker."""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..peer_review import Finding, make_finding
from ..peer_review_extract import ExtractedDoc, loc_of_span
from ..peer_review_overlap import (
    OverlapHit,
    group_overlap_action,
    overlap_findings,
    unquoted_span_for_phrase,
)
from ..zot import Item


def _hit_row(h: OverlapHit, *, action: str) -> dict[str, Any]:
    return {
        "other_key": h.other_key,
        "ngram": h.ngram,
        "n_words": h.n_words,
        "source": h.source,
        "other_loc": h.other_loc,
        "source_quote": h.source_quote,
        "action": action,
    }


def _detail(
    *,
    other: str,
    title: str,
    loc: str,
    action: str,
    n_spans: int,
) -> str:
    who = f"library item {other}"
    if title:
        who += f" ({title[:70]})"
    loc_bit = f" {loc}" if loc else ""
    if action == "quote":
        verb = "Quote this passage or cite that item"
    elif action == "cite":
        verb = "Cite that item"
    else:
        verb = "Review whether to quote or cite that item"
    return (
        f"{n_spans} distinctive span(s) also in {who}{loc_bit}. "
        f"{verb} (flags to review)."
    )


def _overlap(
    cfg: Config,
    doc: ExtractedDoc,
    item: Item | None,
    scope_items: list[Item],
    overlap_rows: list[dict[str, Any]],
) -> list[Finding]:
    exclude = item.key if item is not None else ""
    keys = [it.key for it in scope_items] if scope_items else None
    titles = {it.key: (it.title or "").strip() for it in scope_items}
    hits, skip = overlap_findings(cfg, doc, exclude_key=exclude, scope_keys=keys)
    if skip:
        return [
            make_finding(
                code=skip,
                severity="info",
                detail="No extracted library text on disk (state/rag/text/). Overlap checker skipped.",
                source="phrase",
            )
        ]
    hay = doc.text or ""
    kept: list[OverlapHit] = []
    for h in hits:
        if unquoted_span_for_phrase(hay, h.ngram) is None:
            continue
        kept.append(h)
    by_other: dict[str, list[OverlapHit]] = {}
    for h in kept:
        by_other.setdefault(h.other_key, []).append(h)
    out: list[Finding] = []
    for other, group in by_other.items():
        action = group_overlap_action(group)
        for h in group:
            overlap_rows.append(_hit_row(h, action=action))
        long = any(h.n_words >= 20 for h in group)
        sev = "warn" if long or len(group) >= 3 else "info"
        sample = max(group, key=lambda row: (row.n_words, row.ngram))
        span = unquoted_span_for_phrase(hay, sample.ngram)
        quote = hay[span[0] : span[1]] if span else sample.ngram
        loc = sample.other_loc
        out.append(
            make_finding(
                code="text_overlap",
                severity=sev,
                loc=loc_of_span(doc, quote),
                quote=quote,
                detail=_detail(
                    other=other,
                    title=titles.get(other, ""),
                    loc=loc,
                    action=action,
                    n_spans=len(group),
                ),
                source=sample.source,
                extra={
                    "other_key": other,
                    "other_loc": loc,
                    "action": action,
                    "source_quote": sample.source_quote,
                },
            )
        )
    return out
