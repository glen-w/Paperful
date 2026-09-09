"""Direct: the item's own URL, if it serves a PDF (reports, webpages, grey literature)."""

from __future__ import annotations

import httpx

from ..zot import Item
from .base import Candidate, Context, Outcome

NAME = "direct"
_SKIP_HOSTS = ("doi.org", "scholar.google", "zotero.org", "twitter.com", "x.com", "youtube.com")


def find(item: Item, ctx: Context) -> Candidate:
    url = item.url
    if not url or not url.lower().startswith(("http://", "https://")):
        return Candidate.miss(NAME, Outcome.SKIPPED, "no URL")
    if any(h in url.lower() for h in _SKIP_HOSTS):
        return Candidate.miss(NAME, Outcome.SKIPPED, "resolver/aggregator URL")
    if url.lower().split("?")[0].endswith(".pdf"):
        return Candidate(url=url, source=NAME, note="url ends in .pdf")
    try:
        with ctx.client.stream("GET", url, timeout=30) as resp:
            ctype = resp.headers.get("content-type", "").lower()
            if resp.status_code < 400 and "application/pdf" in ctype:
                return Candidate(url=str(resp.url), source=NAME, note="content-type pdf")
            if resp.status_code < 400 and "octet-stream" in ctype:
                head = b""
                for chunk in resp.iter_bytes(chunk_size=1024):
                    head = chunk
                    break
                if head.lstrip().startswith(b"%PDF"):
                    return Candidate(url=str(resp.url), source=NAME, note="octet-stream pdf")
    except httpx.HTTPError:
        return Candidate.miss(NAME, Outcome.ERROR, "url unreachable")
    return Candidate.miss(NAME, Outcome.NOT_FOUND, "url is not a PDF")
