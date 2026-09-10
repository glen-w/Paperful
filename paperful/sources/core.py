"""CORE OA PDF lookup by DOI. Requires a CORE API key (https://core.ac.uk/services/api)."""

from __future__ import annotations

from ..zot import Item
from .base import Candidate, Context, Outcome, http_json
from .landing import looks_like_pdf_url, resolve_landings

NAME = "core"
_API = "https://api.core.ac.uk/v3/search/works"


def find(item: Item, ctx: Context) -> Candidate:
    if not item.doi:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI")
    key = ctx.config.core_api_key
    if not key:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no CORE API key")
    data = http_json(
        ctx,
        _API,
        params={"q": f'doi:"{item.doi}"', "limit": 5},
        headers={"Authorization": f"Bearer {key}"},
    )
    if data is None:
        return Candidate.miss(NAME, Outcome.NOT_FOUND)
    results = data.get("results") or []
    if not results:
        return Candidate.miss(NAME, Outcome.NOT_FOUND)
    pdfs: list[str] = []
    landings: list[str] = []

    def add_pdf(url: str | None) -> None:
        if url and url not in pdfs:
            pdfs.append(url)

    def add_land(url: str | None) -> None:
        if url and url not in landings:
            landings.append(url)

    for rec in results:
        add_pdf(rec.get("downloadUrl"))
        for link in rec.get("links") or []:
            if not isinstance(link, dict):
                continue
            url = link.get("url") or link.get("href")
            kind = (link.get("type") or link.get("title") or "").lower()
            if not url:
                continue
            if "pdf" in kind or looks_like_pdf_url(url):
                add_pdf(url)
            else:
                add_land(url)

    via_landing = False
    if not pdfs:
        for url in resolve_landings(ctx, landings, item.title):
            add_pdf(url)
        via_landing = bool(pdfs)
    if not pdfs:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no OA PDF")
    return Candidate(
        url=pdfs[0],
        source=NAME,
        alternates=pdfs[1:],
        note="landing" if via_landing else "",
    )
