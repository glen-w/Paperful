"""Hop-0 search sort. Neighbour overlap ranking stays in rank.py.

``popular`` is citation count (today's hop-0 score). It is not OpenAlex
topical relevance. ``recency`` / ``historical`` are publication year.
Watch ``from_created_date`` is a different axis (index cursor).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PRIORITIZE = frozenset({"popular", "recency", "historical"})
DEFAULT_PRIORITIZE = "popular"

_ALIASES = {
    "popular": "popular",
    "cited": "popular",
    "most-cited": "popular",
    "recency": "recency",
    "recent": "recency",
    "newest": "recency",
    "historical": "historical",
    "oldest": "historical",
    "historic": "historical",
}

_SORT = {
    "popular": "cited_by_count:desc",
    "recency": "publication_date:desc",
    "historical": "publication_date:asc",
}

_MISSING_HISTORICAL = -100_000.0


@dataclass(frozen=True)
class DiscoverQuery:
    """Search-side knobs shared by CLI, MCP, profiles, and Discover GUI."""

    year_from: int | None = None
    year_to: int | None = None
    prioritize: str = DEFAULT_PRIORITIZE


def parse_prioritize(value: Any) -> str:
    """``popular`` (default), ``recency``, or ``historical``."""
    text = str(value or "").strip().lower().replace("_", "-")
    if not text:
        return DEFAULT_PRIORITIZE
    if text == "overlap":
        raise ValueError(
            "prioritize overlap is grow-only (neighbour hops). "
            "Use recency, popular, or historical on search."
        )
    mapped = _ALIASES.get(text)
    if mapped in PRIORITIZE:
        return mapped
    raise ValueError("prioritize must be recency, popular, or historical")


def openalex_sort(prioritize: str) -> str:
    """OpenAlex ``sort=`` for hop-0 search."""
    return _SORT[parse_prioritize(prioritize)]


def hop0_score(
    year: Any,
    cited_by_count: Any,
    prioritize: str,
) -> float:
    """Score so ``truncate`` (sort by ``-score``) keeps the hop-0 policy."""
    policy = parse_prioritize(prioritize)
    cited = float(cited_by_count or 0)
    if policy == "popular":
        return cited
    try:
        yr = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        yr = None
    if policy == "recency":
        return float(yr) if yr is not None else -1.0
    if yr is None:
        return _MISSING_HISTORICAL
    return float(-yr)


def hop0_formula(prioritize: str) -> str:
    policy = parse_prioritize(prioritize)
    if policy == "recency":
        return "publication_year (newest first)"
    if policy == "historical":
        return "publication_year (oldest first)"
    return "cited_by_count"


def prioritize_for(cfg: Any, request: Any) -> str:
    """Flag, then config, then popular."""
    raw = getattr(request, "prioritize", None)
    if raw:
        return parse_prioritize(raw)
    return parse_prioritize(getattr(cfg, "snowball_prioritize", DEFAULT_PRIORITIZE))


def discover_query_from_request(request: Any, *, default: str = DEFAULT_PRIORITIZE) -> DiscoverQuery:
    raw = getattr(request, "prioritize", None)
    return DiscoverQuery(
        year_from=getattr(request, "year_from", None),
        year_to=getattr(request, "year_to", None),
        prioritize=parse_prioritize(raw if raw is not None else default),
    )
