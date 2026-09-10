"""OpenAlex: OA locations by DOI."""

from __future__ import annotations

from ..zot import Item
from .base import Candidate, Context, Outcome, http_json
from .landing import looks_like_pdf_url, resolve_landings

NAME = "openalex"


def find(item: Item, ctx: Context) -> Candidate:
    if not item.doi:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI")
    params = {"mailto": ctx.config.email} if ctx.config.email else None
    data = http_json(
        ctx, f"https://api.openalex.org/works/https://doi.org/{item.doi}", params=params
    )
    if data is None:
        return Candidate.miss(NAME, Outcome.NOT_FOUND)
    locations = []
    best = data.get("best_oa_location")
    if best:
        locations.append(best)
    locations.extend(data.get("locations") or [])
    pdfs: list[str] = []
    landings: list[str] = []

    def add_pdf(url: str | None) -> None:
        if url and url not in pdfs:
            pdfs.append(url)

    def add_land(url: str | None) -> None:
        if url and url not in landings:
            landings.append(url)

    for loc in locations:
        if loc.get("pdf_url"):
            add_pdf(loc["pdf_url"])
        land = loc.get("landing_page_url")
        if not land:
            continue
        if looks_like_pdf_url(land):
            add_pdf(land)
        if loc is best or loc.get("is_oa"):
            add_land(land)

    via_landing = False
    if not pdfs:
        for url in resolve_landings(ctx, landings, item.title):
            add_pdf(url)
        via_landing = bool(pdfs)

    if not pdfs:
        if not landings and not any(loc.get("pdf_url") for loc in locations):
            return Candidate.miss(NAME, Outcome.NOT_FOUND, "no pdf_url")
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "OA landing, no PDF")
    landing = next(
        (
            loc.get("landing_page_url")
            for loc in locations
            if loc.get("pdf_url") or loc.get("is_oa")
        ),
        None,
    )
    return Candidate(
        url=pdfs[0],
        source=NAME,
        referer=landing,
        alternates=pdfs[1:],
        note="landing" if via_landing else "",
    )
