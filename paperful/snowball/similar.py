"""One ranked similar hop: shared references, plus Semantic Scholar recommendations.

Bibliographic coupling here means a work that cites several of the seed's own
references. Recommendations are a separate list from the Semantic Scholar
recommendations API. Neither walk is repeated on later hops.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import httpx

from .openalex import OpenAlexBudgetExceeded, OpenAlexClient, short_id

# How many of a seed's references to invert. Past this, the hop stops.
REF_SAMPLE = 8
# Citers requested per reference. The emit cap is still per_hop_limit.
CITERS_PER_REF = 25
_S2_RECS = "https://api.semanticscholar.org/recommendations/v1/papers"
Recommend = Callable[[list[str], int], list[dict[str, Any]]]


def reference_sample(seeds: list[dict[str, Any]], *, limit: int = REF_SAMPLE) -> list[str]:
    """OpenAlex ids the seeds cite, most-shared first."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for seed in seeds:
        for ref in seed.get("referenced_works") or []:
            sid = short_id(str(ref))
            if not sid:
                continue
            if sid not in counts:
                order.append(sid)
            counts[sid] = counts.get(sid, 0) + 1
    ranked = sorted(enumerate(order), key=lambda item: (-counts[item[1]], item[0]))
    picked = [sid for _, sid in ranked]
    return picked[: max(1, limit)] if limit else picked


def paper_ids(seeds: list[dict[str, Any]]) -> list[str]:
    """Semantic Scholar ids for the recommendation call. DOI only."""
    from ..resolve import normalize_doi

    found: list[str] = []
    for seed in seeds:
        doi = normalize_doi(str(seed.get("doi") or "")) or ""
        token = f"DOI:{doi}" if doi else ""
        if token and token not in found:
            found.append(token)
    return found[:20]


def fetch_recommendations(
    paper_ids_in: list[str],
    *,
    limit: int,
    getter: Recommend | None = None,
) -> list[dict[str, Any]]:
    """Recommended papers. A missing or failing API returns an empty list."""
    if not paper_ids_in:
        return []
    cap = max(1, min(int(limit or 50), 500))
    if getter is not None:
        return list(getter(paper_ids_in, cap) or [])
    headers = {}
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    if key:
        headers["x-api-key"] = key
    try:
        resp = httpx.post(
            _S2_RECS,
            params={
                "limit": cap,
                "fields": "title,year,externalIds,citationCount,paperId",
            },
            json={"positivePaperIds": paper_ids_in},
            headers=headers or None,
            timeout=30.0,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    papers = data.get("recommendedPapers") or []
    return list(papers) if isinstance(papers, list) else []


def recommendation_work(paper: dict[str, Any]) -> dict[str, Any] | None:
    """OpenAlex-shaped work for a recommendation that has a DOI."""
    ext = paper.get("externalIds") or {}
    doi = ""
    if isinstance(ext, dict):
        doi = str(ext.get("DOI") or "")
    if not doi:
        return None
    return {
        "id": "",
        "doi": doi if doi.lower().startswith("https://doi.org/") else f"https://doi.org/{doi}",
        "display_name": paper.get("title") or "",
        "publication_year": paper.get("year"),
        "type": "article",
        "cited_by_count": int(paper.get("citationCount") or 0),
        "referenced_works": [],
        "authorships": [],
        "primary_location": {},
        "open_access": {},
        "_ref_overlap": 0,
        "_why": "similar via Semantic Scholar",
    }


def collect_partners(
    client: OpenAlexClient,
    ref_ids: list[str],
    *,
    per_ref: int,
    year_from: int | None,
    year_to: int | None,
    counts: dict[str, int] | None = None,
    works: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[tuple[int, dict[str, Any]]], list[str]]:
    """Invert ``ref_ids``. Returns ranked partners and any ids not queried.

    ``OpenAlexBudgetExceeded`` is re-raised after the partial maps are stored
    on the exception as ``coupling_counts`` and ``coupling_works``.
    """
    tally = dict(counts or {})
    found = dict(works or {})
    for index, ref_id in enumerate(ref_ids):
        try:
            citing = client.works_citing(
                ref_id,
                limit=per_ref,
                year_from=year_from,
                year_to=year_to,
            )
        except OpenAlexBudgetExceeded as exc:
            exc.coupling_counts = tally  # type: ignore[attr-defined]
            exc.coupling_works = found  # type: ignore[attr-defined]
            exc.pending_ids = ref_ids[index:]
            raise
        seen: set[str] = set()
        for work in citing:
            oa = short_id(str(work.get("id") or ""))
            if not oa or oa in seen:
                continue
            seen.add(oa)
            tally[oa] = tally.get(oa, 0) + 1
            found.setdefault(oa, work)
    ranked = sorted(
        tally,
        key=lambda oa: (-tally[oa], -int(found[oa].get("cited_by_count") or 0), oa),
    )
    return [(tally[oa], found[oa]) for oa in ranked], []
