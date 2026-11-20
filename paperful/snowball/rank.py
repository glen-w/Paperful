"""Overlap rank. Hop-0 search hits follow DiscoverQuery.prioritize."""

from __future__ import annotations

from .candidate import Candidate
from .discover import DEFAULT_PRIORITIZE, hop0_score

FORMULA = "overlap * 1000 + cited_by_count"


def apply_overlap(
    rows: list[Candidate], *, prioritize: str = DEFAULT_PRIORITIZE
) -> None:
    """Neighbours score by how many distinct seeds point at them."""
    for row in rows:
        cited = float(row.biblio.get("cited_by_count") or 0)
        if row.hop < 1:
            row.score = hop0_score(row.biblio.get("year"), cited, prioritize)
            continue
        seeds = list(row.biblio.get("seed_keys") or [])
        seed_overlap = len(seeds) if seeds else 1
        keyword_overlap = int(row.biblio.get("keyword_overlap") or 0)
        ref_overlap = int(row.biblio.get("ref_overlap") or 0)
        overlap = max(seed_overlap, keyword_overlap, ref_overlap)
        row.biblio["overlap"] = overlap
        row.score = overlap * 1000 + cited
