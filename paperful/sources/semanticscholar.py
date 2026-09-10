"""Semantic Scholar Graph API: openAccessPdf by DOI or arXiv id."""

from __future__ import annotations

from ..zot import Item
from .base import Candidate, Context, Outcome, http_json
from .landing import looks_like_pdf_url, resolve_landings

NAME = "semanticscholar"


def find(item: Item, ctx: Context) -> Candidate:
    if item.doi:
        ident = f"DOI:{item.doi}"
    elif item.arxiv_id:
        ident = f"ARXIV:{item.arxiv_id}"
    else:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI/arXiv id")
    data = http_json(
        ctx,
        f"https://api.semanticscholar.org/graph/v1/paper/{ident}",
        params={"fields": "openAccessPdf"},
    )
    if not data:
        return Candidate.miss(NAME, Outcome.NOT_FOUND)
    oa = data.get("openAccessPdf") or {}
    url = oa.get("url")
    if not url:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no openAccessPdf")
    note = oa.get("status") or ""
    if looks_like_pdf_url(url):
        return Candidate(url=url, source=NAME, note=note)
    resolved = resolve_landings(ctx, [url], item.title)
    if resolved:
        return Candidate(
            url=resolved[0],
            source=NAME,
            note=note or "landing",
            referer=url,
            alternates=resolved[1:],
        )
    return Candidate(url=url, source=NAME, note=note)
