"""Library n-gram overlap checker."""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..critique import Finding, make_finding
from ..critique_extract import ExtractedDoc, loc_of_span
from ..critique_overlap import OverlapHit, overlap_findings
from ..zot import Item


def _overlap(
    cfg: Config,
    doc: ExtractedDoc,
    item: Item | None,
    scope_items: list[Item],
    overlap_rows: list[dict[str, Any]],
) -> list[Finding]:
    exclude = item.key if item is not None else ""
    keys = [it.key for it in scope_items] if scope_items else None
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
    for h in hits:
        overlap_rows.append(
            {
                "other_key": h.other_key,
                "ngram": h.ngram,
                "n_words": h.n_words,
                "source": h.source,
                "other_loc": h.other_loc,
            }
        )
    by_other: dict[str, list[OverlapHit]] = {}
    for h in hits:
        by_other.setdefault(h.other_key, []).append(h)
    out: list[Finding] = []
    for other, group in by_other.items():
        long = any(h.n_words >= 20 for h in group)
        sev = "warn" if long or len(group) >= 3 else "info"
        sample = group[0]
        out.append(
            make_finding(
                code="text_overlap",
                severity=sev,
                loc=loc_of_span(doc, sample.ngram),
                quote=sample.ngram,
                detail=(
                    f"{len(group)} distinctive span(s) also in library item {other} "
                    f"(flags to review)."
                ),
                source=sample.source,
                extra={"other_key": other},
            )
        )
    return out
