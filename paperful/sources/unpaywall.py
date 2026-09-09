"""Unpaywall: OA locations by DOI. Requires a contact email."""

from __future__ import annotations

from ..zot import Item
from .base import Candidate, Context, Outcome, http_json

NAME = "unpaywall"


def find(item: Item, ctx: Context) -> Candidate:
    if not item.doi:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI")
    if not ctx.config.email:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no email configured")
    data = http_json(ctx, f"https://api.unpaywall.org/v2/{item.doi}", params={"email": ctx.config.email})
    if data is None:
        return Candidate.miss(NAME, Outcome.NOT_FOUND)
    locations = []
    if data.get("best_oa_location"):
        locations.append(data["best_oa_location"])
    locations.extend(data.get("oa_locations") or [])
    urls = [loc["url_for_pdf"] for loc in locations if loc.get("url_for_pdf")]
    if not urls:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no url_for_pdf")
    landing = next((loc.get("url_for_landing_page") for loc in locations if loc.get("url_for_pdf")), None)
    return Candidate(url=urls[0], source=NAME, referer=landing, alternates=urls[1:])
