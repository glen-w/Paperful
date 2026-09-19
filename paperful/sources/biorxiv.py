"""bioRxiv / medRxiv: PDF by Cold Spring Harbor DOI (10.1101/…)."""

from __future__ import annotations

from ..resolve import normalize_doi
from ..routing import doi_from_biorxiv_url, is_cshl_doi
from ..zot import Item
from .base import Candidate, Context, Outcome, http_json

NAME = "biorxiv"
_SERVERS = ("biorxiv", "medrxiv")


def find(item: Item, ctx: Context) -> Candidate:
    doi = item.doi or doi_from_biorxiv_url(item.url)
    if not doi:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI")
    if not is_cshl_doi(doi):
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
