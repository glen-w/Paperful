"""Europe PMC: OA PDF by DOI (PubMed Central and publisher deposits)."""

from __future__ import annotations

from ..zot import Item
from .base import Candidate, Context, Outcome, http_json

NAME = "europepmc"
_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
# Prefer free/OA PDFs; Europe_PMC host first (stable ?pdf=render links).
_AVAIL = {"OA": 0, "F": 1}
_SITE_PREF = {"Europe_PMC": 0, "PMC": 1}


def find(item: Item, ctx: Context) -> Candidate:
    if not item.doi:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI")
    data = http_json(
        ctx,
        _API,
        params={
            "query": f"DOI:{item.doi}",
            "resultType": "core",
            "format": "json",
            "pageSize": "1",
        },
    )
    if not data:
        return Candidate.miss(NAME, Outcome.NOT_FOUND)
    results = ((data.get("resultList") or {}).get("result")) or []
    if not results:
        return Candidate.miss(NAME, Outcome.NOT_FOUND)
    urls = _pdf_urls(results[0])
    if not urls:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no OA PDF")
    pmcid = results[0].get("pmcid") or ""
    return Candidate(url=urls[0], source=NAME, note=pmcid, alternates=urls[1:])


def _pdf_urls(record: dict) -> list[str]:
    raw = ((record.get("fullTextUrlList") or {}).get("fullTextUrl")) or []
    scored: list[tuple[tuple[int, int, int], str]] = []
    for entry in raw:
        if (entry.get("documentStyle") or "").lower() != "pdf":
            continue
        code = (entry.get("availabilityCode") or "").upper()
        if code not in _AVAIL:
            continue
        url = entry.get("url")
        if not url:
            continue
        site = entry.get("site") or ""
        scored.append(((_AVAIL[code], _SITE_PREF.get(site, 9), len(scored)), url))
    scored.sort(key=lambda x: x[0])
    seen: list[str] = []
    for _, url in scored:
        if url not in seen:
            seen.append(url)
    return seen
