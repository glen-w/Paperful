"""arXiv: direct PDF by identifier, else a strict title search."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from ..resolve import ARXIV_NEW_RE, ARXIV_OLD_RE, title_similarity
from ..zot import Item
from .base import Candidate, Context, Outcome

NAME = "arxiv"
_NS = {"a": "http://www.w3.org/2005/Atom"}
_TITLE_MIN_SCORE = 0.93


def pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def find(item: Item, ctx: Context) -> Candidate:
    if item.arxiv_id:
        return Candidate(
            url=pdf_url(item.arxiv_id), source=NAME, note=f"arXiv:{item.arxiv_id}"
        )
    if item.doi and item.doi.startswith("10.48550/arxiv."):
        aid = item.doi.split("arxiv.", 1)[1]
        return Candidate(url=pdf_url(aid), source=NAME, note=f"arXiv:{aid}")
    if item.item_type not in {
        "preprint",
        "journalArticle",
        "conferencePaper",
        "report",
        "manuscript",
    }:
        return Candidate.miss(NAME, Outcome.SKIPPED, "type not searched")
    return _title_search(item, ctx)


def _title_search(item: Item, ctx: Context) -> Candidate:
    if len(item.title) < 20:
        return Candidate.miss(NAME, Outcome.SKIPPED, "title too short")
    query = re.sub(r"[^\w\s]", " ", item.title)
    try:
        resp = ctx.client.get(
            "https://export.arxiv.org/api/query",
            params={"search_query": f'ti:"{query}"', "max_results": 3},
            timeout=30,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except (httpx.HTTPError, ET.ParseError):
        return Candidate.miss(NAME, Outcome.ERROR, "query failed")
    for entry in root.findall("a:entry", _NS):
        title = (entry.findtext("a:title", default="", namespaces=_NS) or "").strip()
        if title_similarity(title, item.title) < _TITLE_MIN_SCORE:
            continue
        ident = entry.findtext("a:id", default="", namespaces=_NS) or ""
        m = ARXIV_NEW_RE.search(ident) or ARXIV_OLD_RE.search(ident)
        if m:
            return Candidate(
                url=pdf_url(m.group(1)),
                source=NAME,
                note=f"title match arXiv:{m.group(1)}",
            )
    return Candidate.miss(NAME, Outcome.NOT_FOUND)
