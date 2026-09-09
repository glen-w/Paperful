"""OpenAlex: OA locations by DOI."""

from __future__ import annotations

from ..zot import Item
from .base import Candidate, Context, Outcome, http_json

NAME = "openalex"


def find(item: Item, ctx: Context) -> Candidate:
    if not item.doi:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI")
    params = {"mailto": ctx.config.email} if ctx.config.email else None
    data = http_json(ctx, f"https://api.openalex.org/works/https://doi.org/{item.doi}", params=params)
    if data is None:
        return Candidate.miss(NAME, Outcome.NOT_FOUND)
    locations = []
    if data.get("best_oa_location"):
        locations.append(data["best_oa_location"])
    locations.extend(data.get("locations") or [])
    urls = [loc["pdf_url"] for loc in locations if loc.get("pdf_url")]
    if not urls:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no pdf_url")
    landing = next((loc.get("landing_page_url") for loc in locations if loc.get("pdf_url")), None)
    return Candidate(url=urls[0], source=NAME, referer=landing, alternates=urls[1:])
