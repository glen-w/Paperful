"""Semantic Scholar Graph API: openAccessPdf by DOI or arXiv id."""

from __future__ import annotations

from ..zot import Item
from .base import Candidate, Context, Outcome, http_json

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
    if oa.get("url"):
        return Candidate(url=oa["url"], source=NAME, note=oa.get("status") or "")
    return Candidate.miss(NAME, Outcome.NOT_FOUND, "no openAccessPdf")
