"""Direct: the item's own URL, if it serves a PDF or links to one (reports, grey literature)."""

from __future__ import annotations

import httpx

from ..zot import Item
from .base import Candidate, Context, Outcome
from .landing import extract_pdf_urls, grey_target, looks_like_pdf_url

NAME = "direct"
_SKIP_HOSTS = (
    "doi.org",
    "scholar.google",
    "zotero.org",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "facebook.com",
    "consensus.app",
    "semanticscholar.org",
    "researchgate.net",
)


def find(item: Item, ctx: Context) -> Candidate:
    target = grey_target(item)
    if not target or not target.lower().startswith(("http://", "https://")):
        return Candidate.miss(NAME, Outcome.SKIPPED, "no URL")
    original = (item.url or "").strip()
    check = original.lower() if original.startswith(("http://", "https://")) else target.lower()
    if any(h in check for h in _SKIP_HOSTS):
        return Candidate.miss(NAME, Outcome.SKIPPED, "resolver/aggregator URL")
    note = "url rewrite" if target != original else "url ends in .pdf"
    if looks_like_pdf_url(target) or target.lower().split("?")[0].endswith(".pdf"):
        return Candidate(
            url=target,
            source=NAME,
            note=note if target != original else "url ends in .pdf",
        )
    try:
        with ctx.client.stream("GET", target, timeout=30) as resp:
            ctype = resp.headers.get("content-type", "").lower()
            if resp.status_code < 400 and "application/pdf" in ctype:
                return Candidate(
                    url=str(resp.url), source=NAME, note="content-type pdf"
                )
            if resp.status_code < 400 and "octet-stream" in ctype:
                head = b""
                for chunk in resp.iter_bytes(chunk_size=1024):
                    head = chunk
                    break
                if head.lstrip().startswith(b"%PDF"):
                    return Candidate(
                        url=str(resp.url), source=NAME, note="octet-stream pdf"
                    )
            if resp.status_code < 400 and "html" in ctype:
                text = b"".join(resp.iter_bytes()).decode("utf-8", "replace")
                pdfs = extract_pdf_urls(text, str(resp.url))
                if pdfs:
                    return Candidate(
                        url=pdfs[0],
                        source=NAME,
                        note="html link",
                        referer=str(resp.url),
                        alternates=pdfs[1:5],
                    )
    except httpx.HTTPError:
        return Candidate.miss(NAME, Outcome.ERROR, "url unreachable")
    return Candidate.miss(NAME, Outcome.NOT_FOUND, "url is not a PDF")
