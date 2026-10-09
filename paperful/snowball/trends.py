"""OpenAlex publication-year counts for a keyword query or snowball profile seed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import Config
from .command import SnowballError, _openalex_client
from .openalex import OpenAlexBudgetExceeded, OpenAlexClient
from .profile import composed_query_from_profile, load_profile


@dataclass(frozen=True)
class YearCount:
    year: int
    count: int


@dataclass(frozen=True)
class TrendsReport:
    query: str
    total: int
    years: tuple[YearCount, ...]
    profile: str | None = None


def resolve_trends_query(cfg: Config, *, query: str | None, profile: str | None) -> tuple[str, str | None]:
    """Return (openalex_search, profile_name)."""
    prof = (profile or "").strip()
    q = (query or "").strip()
    if prof:
        if q:
            raise SnowballError("Pass either a query or --profile, not both.")
        raw = load_profile(cfg, prof)
        mode = str(raw.get("mode") or "").strip().lower()
        if mode not in {"search", "hybrid"}:
            raise SnowballError("Trends need a search or hybrid profile with query terms.")
        return composed_query_from_profile(raw), prof
    if not q:
        raise SnowballError("Pass a search query or --profile.")
    return q, None


def publication_trends(
    cfg: Config,
    *,
    query: str,
    year_from: int | None = None,
    year_to: int | None = None,
    client: OpenAlexClient | None = None,
) -> TrendsReport:
    oa = client or _openalex_client(cfg, sleep_s=0.15)
    try:
        raw_years = oa.counts_by_year(
            query,
            year_from=year_from,
            year_to=year_to,
        )
        years = tuple(YearCount(year=y, count=c) for y, c in raw_years)
    except OpenAlexBudgetExceeded as exc:
        reset_at = getattr(exc, "reset_at", None)
        wait = f" Wait until {reset_at}." if reset_at else ""
        raise SnowballError(
            "OpenAlex daily budget is spent. "
            f"Set OPENALEX_API_KEY if this IP shares the no-key pool.{wait}"
        ) from exc
    total = sum(row.count for row in years)
    return TrendsReport(query=query, total=total, years=tuple(years))


def trends_for_scope(
    cfg: Config,
    *,
    query: str | None = None,
    profile: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    client: Any = None,
) -> TrendsReport:
    resolved, prof_name = resolve_trends_query(cfg, query=query, profile=profile)
    report = publication_trends(
        cfg,
        query=resolved,
        year_from=year_from,
        year_to=year_to,
        client=client,
    )
    if prof_name:
        return TrendsReport(
            query=report.query,
            total=report.total,
            years=report.years,
            profile=prof_name,
        )
    return report
