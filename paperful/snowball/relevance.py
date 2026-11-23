"""Relevance gates so neighbourhood hops do not flood a collection with top-cited noise."""

from __future__ import annotations

from .candidate import Candidate


def hop_overlap(row: Candidate) -> int:
    seeds = list(row.biblio.get("seed_keys") or [])
    seed_overlap = len(seeds) if seeds else 0
    keyword_overlap = int(row.biblio.get("keyword_overlap") or 0)
    ref_overlap = int(row.biblio.get("ref_overlap") or 0)
    return max(seed_overlap, keyword_overlap, ref_overlap)


def filter_hop_neighbors(
    rows: list[Candidate],
    *,
    min_overlap: int,
    keyword_seed: bool = True,
    cites_query: str = "",
) -> list[Candidate]:
    """Drop hop ≥ 1 neighbours with no measurable link back to the seed set."""
    if min_overlap < 1:
        return rows
    if (cites_query or "").strip():
        return rows
    for row in rows:
        if row.status != "new" or row.hop < 1:
            continue
        if keyword_seed and str(row.seed.get("type") or "") != "keyword":
            continue
        if hop_overlap(row) >= min_overlap:
            continue
        row.status = "filtered"
        note = "hop_overlap"
        if note not in (row.why or ""):
            row.why = f"{(row.why or '').strip()} ({note})".strip()
    return rows
