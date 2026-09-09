"""bioRxiv / medRxiv: PDF by Cold Spring Harbor DOI (10.1101/…)."""

from __future__ import annotations

import re

from ..resolve import normalize_doi
from ..zot import Item
from .base import Candidate, Context, Outcome, http_json

NAME = "biorxiv"
_SERVERS = ("biorxiv", "medrxiv")
# Cold Spring Harbor Laboratory Press (bioRxiv, medRxiv, and a few journals).
_CSHL_DOI = re.compile(r"^10\.1101/", re.IGNORECASE)
_CONTENT_DOI = re.compile(
    r"(?:bio|med)rxiv\.org/content/(?:[^/\s]+/)*(10\.1101/[0-9./]+?)(?:v\d+)?(?:[./?]|$)",
    re.IGNORECASE,
)


def find(item: Item, ctx: Context) -> Candidate:
    doi = item.doi or _doi_from_url(item.url)
    if not doi:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI")
    if not _CSHL_DOI.match(doi):
        return Candidate.miss(NAME, Outcome.SKIPPED, "not a 10.1101 DOI")

    for server in _SERVERS:
        data = http_json(ctx, f"https://api.biorxiv.org/details/{server}/{doi}")
        if not data:
            continue
        collection = data.get("collection") or []
        if not collection:
            continue
        # API returns version history newest-last; take the latest entry.
        record = collection[-1]
        version = str(record.get("version") or "1").lstrip("v")
        record_doi = normalize_doi(record.get("doi")) or doi
        pdf = f"https://www.{server}.org/content/{record_doi}v{version}.full.pdf"
        alt = f"https://www.{server}.org/content/{record_doi}.full.pdf"
        landing = f"https://www.{server}.org/content/{record_doi}v{version}"
        return Candidate(
            url=pdf,
            source=NAME,
            referer=landing,
            note=f"{server} v{version}",
            alternates=[alt] if alt != pdf else [],
        )
    return Candidate.miss(NAME, Outcome.NOT_FOUND)


def _doi_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = _CONTENT_DOI.search(url)
    return normalize_doi(m.group(1)) if m else None
