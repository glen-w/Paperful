"""Unpaywall: OA locations by DOI. Requires a contact email."""

from __future__ import annotations

from ..oa_locations import rank_unpaywall_locations, stamp_from_unpaywall
from ..zot import Item
from .base import Candidate, Context, Outcome, http_json
from .landing import looks_like_pdf_url, resolve_landings

NAME = "unpaywall"


def find(item: Item, ctx: Context) -> Candidate:
    if not item.doi:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI")
    if not ctx.config.email:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no email configured")
    data = http_json(
        ctx,
        f"https://api.unpaywall.org/v2/{item.doi}",
        params={"email": ctx.config.email},
    )
    if data is None:
        return Candidate.miss(NAME, Outcome.NOT_FOUND)
    locations = rank_unpaywall_locations(data)
    pdfs: list[str] = []
    landings: list[str] = []

    def add_pdf(url: str | None) -> None:
        if url and url not in pdfs:
            pdfs.append(url)

    def add_land(url: str | None) -> None:
        if url and url not in landings:
            landings.append(url)

    for loc in locations:
        if loc.get("url_for_pdf"):
            add_pdf(loc["url_for_pdf"])
        for field in ("url", "url_for_landing_page"):
            u = loc.get(field)
            if not u:
                continue
            if looks_like_pdf_url(u):
                add_pdf(u)
            add_land(u)

    via_landing = False
    if not pdfs:
        for url in resolve_landings(ctx, landings, item.title):
            add_pdf(url)
        via_landing = bool(pdfs)

    if not pdfs:
        if not locations:
            return Candidate.miss(NAME, Outcome.NOT_FOUND, "no OA location")
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "OA landing, no PDF")
    landing = next(
        (loc.get("url_for_landing_page") or loc.get("url") for loc in locations), None
    )
    chosen: dict = {}
    if pdfs:
        for loc in locations:
            if loc.get("url_for_pdf") == pdfs[0]:
                chosen = loc
                break
    if not chosen and locations:
        chosen = locations[0]
    stamp = stamp_from_unpaywall(data, chosen) if chosen else {}
    return Candidate(
        url=pdfs[0],
        source=NAME,
        referer=landing,
        alternates=pdfs[1:],
        note="landing" if via_landing else "",
        oa_stamp=stamp,
    )
