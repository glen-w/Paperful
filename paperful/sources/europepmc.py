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
    for url in pmc_pdf_urls(str(record.get("pmcid") or "")):
        if url not in seen:
            seen.append(url)
    return seen


def pmc_pdf_urls(pmcid: str) -> list[str]:
    """Canonical Europe PMC PDF URLs for a PMCID.

    The article render endpoint is the reliable one. The backend render URL
    and the OA zip are fallbacks when ``fullTextUrlList`` is empty or stale.
    """
    acc = _pmc_accession(pmcid)
    if not acc:
        return []
    number = acc[3:]
    folder = f"{number[:-2]}/{number[-2:]}" if len(number) >= 2 else number
    return [
        f"https://europepmc.org/articles/{acc}?pdf=render",
        f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={acc}&blobtype=pdf",
        f"https://europepmc.org/pub/databases/pmc/pdf/OA/{folder}/{acc}.zip",
    ]


def _pmc_accession(pmcid: str) -> str:
    token = (pmcid or "").strip().upper()
    if token.startswith("PMC"):
        digits = "".join(ch for ch in token[3:] if ch.isdigit())
    else:
        digits = "".join(ch for ch in token if ch.isdigit())
    if not digits:
        return ""
    return f"PMC{digits}"
