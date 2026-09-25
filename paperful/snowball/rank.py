"""Overlap rank. Search hits keep cited_by_count."""

from __future__ import annotations

from .candidate import Candidate

FORMULA = "overlap * 1000 + cited_by_count"


def apply_overlap(rows: list[Candidate]) -> None:
    """Neighbours score by how many distinct seeds point at them."""
    for row in rows:
        cited = float(row.biblio.get("cited_by_count") or 0)
        if row.hop < 1:
            row.score = cited
            continue
        seeds = list(row.biblio.get("seed_keys") or [])
        overlap = len(seeds) if seeds else 1
        row.biblio["overlap"] = overlap
        row.score = overlap * 1000 + cited
