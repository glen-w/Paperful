"""Stop rules. No network."""

from __future__ import annotations

from .candidate import Candidate

# Soft ceiling so a typo does not walk the whole graph. Caps still bind first.
MAX_DEPTH = 5


def clamp_depth(depth: int) -> tuple[int, str | None]:
    """Normalize depth. Returns the depth to use and an optional warning."""
    if depth < 0:
        return 0, None
    if depth > MAX_DEPTH:
        return MAX_DEPTH, f"depth clamped to {MAX_DEPTH}"
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


def normalize_direction(raw: str) -> str:
    """Return refs, cites, or both. Raises ValueError for anything else."""
    value = (raw or "refs").strip().lower()
    if value in {"refs", "references", "ref"}:
        return "refs"
    if value in {"cites", "cited-by", "cited_by", "citations"}:
        return "cites"
    if value in {"both", "refs+cites", "all"}:
        return "both"
    raise ValueError(f"direction must be refs, cites, or both (got {raw!r})")
