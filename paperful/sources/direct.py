"""Direct: the item's own URL, if it serves a PDF or links to one (reports, grey literature)."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from ..playbooks import scrape_playbooks_for_host, url_is_direct_skip
from ..zot import Item
from .base import Candidate, Context, Outcome
from .landing import (
    extract_pdf_urls,
    grey_playbook_name,
    grey_target,
    looks_like_pdf_url,
)

NAME = "direct"


def _stamp_playbook(item: Item, books, target: str, cand: Candidate) -> Candidate:
    name = grey_playbook_name(item, books)
    if not name and cand.note == "html link":
        host = urlparse(target).hostname or ""
        scrape = scrape_playbooks_for_host(host, books)
        if scrape:
            name = scrape[0].name
    cand.playbook = name
    return cand


def find(item: Item, ctx: Context) -> Candidate:
    books = ctx.config.grey_playbooks
    target = grey_target(item, books)
    if not target or not target.lower().startswith(("http://", "https://")):
        return Candidate.miss(NAME, Outcome.SKIPPED, "no URL")
    original = (item.url or "").strip()
    # After synthesize, target may be undocs while original was YouTube — do not skip.
    if target == original and url_is_direct_skip(original):
        return Candidate.miss(NAME, Outcome.SKIPPED, "resolver/aggregator URL")
    if url_is_direct_skip(target):
        return Candidate.miss(NAME, Outcome.SKIPPED, "resolver/aggregator URL")
    note = "url rewrite" if target != original else "url ends in .pdf"
    if looks_like_pdf_url(target) or target.lower().split("?")[0].endswith(".pdf"):
        return _stamp_playbook(
            item,
            books,
            target,
            Candidate(
                url=target,
                source=NAME,
                note=note if target != original else "url ends in .pdf",
            ),
        )
    try:
        with ctx.client.stream("GET", target, timeout=30) as resp:
            ctype = resp.headers.get("content-type", "").lower()
            if resp.status_code < 400 and "application/pdf" in ctype:
                return _stamp_playbook(
                    item,
                    books,
                    str(resp.url),
                    Candidate(
                        url=str(resp.url), source=NAME, note="content-type pdf"
                    ),
                )
            if resp.status_code < 400 and "octet-stream" in ctype:
                head = b""
                for chunk in resp.iter_bytes(chunk_size=1024):
                    head = chunk
                    break
                if head.lstrip().startswith(b"%PDF"):
                    return _stamp_playbook(
                        item,
                        books,
                        str(resp.url),
                        Candidate(
                            url=str(resp.url), source=NAME, note="octet-stream pdf"
                        ),
                    )
            if resp.status_code < 400 and "html" in ctype:
                text = b"".join(resp.iter_bytes()).decode("utf-8", "replace")
                pdfs = extract_pdf_urls(text, str(resp.url), books)
                if pdfs:
                    return _stamp_playbook(
                        item,
                        books,
                        str(resp.url),
                        Candidate(
                            url=pdfs[0],
                            source=NAME,
                            note="html link",
                            referer=str(resp.url),
                            alternates=pdfs[1:5],
                        ),
                    )
    except httpx.HTTPError:
        return Candidate.miss(NAME, Outcome.ERROR, "url unreachable")
    return Candidate.miss(NAME, Outcome.NOT_FOUND, "url is not a PDF")
