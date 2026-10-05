"""Opt-in Google Scholar *link discovery* via SerpApi.

Not a default ``run`` source. Requires ``[serpapi].enabled`` and
``SERPAPI_API_KEY``. Downloads still go through the existing PDF path.
``[serpapi].max_calls`` (or ``--serpapi-max``) caps paid searches per run.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx

from ..routing import serpapi_api_key
from ..zot import Item
from . import scholar
from .base import Candidate, Context, Outcome

NAME = "serpapi"
_API = "https://serpapi.com/search.json"


def find(item: Item, ctx: Context) -> Candidate:
    key = serpapi_api_key()
    if not key:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no SERPAPI_API_KEY")
    url = scholar.search_url(item)
    if not url:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no query")
    q = (parse_qs(urlparse(url).query).get("q") or [""])[0]
    try:
        resp = ctx.client.get(
            _API,
            params={"engine": "google_scholar", "q": q, "api_key": key, "num": 10},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        return Candidate.miss(NAME, Outcome.ERROR, f"request failed ({type(exc).__name__})")
    if resp.status_code == 429:
        return Candidate.miss(NAME, Outcome.ERROR, "HTTP 429")
    if resp.status_code in {401, 403}:
        return Candidate.miss(NAME, Outcome.ERROR, "quota")
    if resp.status_code >= 400:
        return Candidate.miss(NAME, Outcome.ERROR, f"HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError:
        return Candidate.miss(NAME, Outcome.ERROR, "invalid JSON")
    err = str(data.get("error") or "")
    if err:
        low = err.lower()
        if "run out" in low or "quota" in low or "limit" in low:
            return Candidate.miss(NAME, Outcome.ERROR, "quota")
        return Candidate.miss(NAME, Outcome.NOT_FOUND, err[:120])
    pdfs = extract_pdf_links(data)
    if not pdfs:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no free PDF link")
    return Candidate(
        url=pdfs[0],
        source=NAME,
        note="google scholar (serpapi)",
        alternates=pdfs[1:4],
    )


def extract_pdf_links(data: dict) -> list[str]:
    found: list[str] = []

    def add(url: str | None) -> None:
        href = (url or "").strip()
        if not href.lower().startswith(("http://", "https://")):
            return
        if href not in found:
            found.append(href)

    for row in data.get("organic_results") or []:
        if not isinstance(row, dict):
            continue
        for res in row.get("resources") or []:
            if not isinstance(res, dict):
                continue
            fmt = str(res.get("file_format") or "").lower()
            link = str(res.get("link") or "")
            if "pdf" in fmt or link.lower().split("?")[0].endswith(".pdf"):
                add(link)
        link = str(row.get("link") or "")
        if link.lower().split("?")[0].endswith(".pdf"):
            add(link)
    return found
