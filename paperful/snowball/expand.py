"""Stop rules. No network."""

from __future__ import annotations

from .candidate import Candidate


def clamp_depth(depth: int) -> tuple[int, str | None]:
    """Depth above 1 is not honored yet. Returns the depth to use and a warning."""
    if depth > 1:
        return 1, "depth clamped to 1"
    if depth < 0:
        return 0, None
    return depth, None


def keyword_depth(explicit: int | None) -> int:
    """Keyword runs stay at the hit list unless this command sets depth."""
    if explicit is None:
        return 0
    used, _warning = clamp_depth(explicit)
    return used


def truncate(rows: list[Candidate], max_candidates: int) -> list[Candidate]:
    """Keep the highest-scoring rows. DOI, then OpenAlex id, breaks ties."""
    ranked = sorted(
        rows,
        key=lambda row: (
            -row.score,
            (row.ids.get("doi") or row.ids.get("openalex") or ""),
        ),
    )
    if max_candidates < 0:
        return []
    return ranked[:max_candidates]


def cap_ids(ids: list[str], per_hop_limit: int) -> list[str]:
    """Fan-out per seed, stable order."""
    seen: list[str] = []
    limit = max(0, per_hop_limit)
    for raw in ids:
        if raw and raw not in seen:
            seen.append(raw)
        if len(seen) >= limit:
            break
    return seen
