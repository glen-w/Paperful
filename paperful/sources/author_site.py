"""Grey author-site lane: listing pages from promoted field packs."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from ..resolve import title_similarity
from ..zot import Item
from .base import Candidate, Context, Outcome
from .landing import extract_pdf_urls, looks_like_pdf_url

NAME = "author_site"
_TITLE_MIN = 0.55


def find(item: Item, ctx: Context) -> Candidate:
    from ..snowball.authors import matching_author

    author = matching_author(item, ctx.config)
    if author is None:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no pack match")
    listing = (author.listing_url or "").strip()
    if not listing.lower().startswith(("http://", "https://")):
        if author.base_host:
            listing = f"https://{author.base_host}/"
        else:
            return Candidate.miss(NAME, Outcome.SKIPPED, "no listing URL")
    if looks_like_pdf_url(listing):
        return Candidate(
            url=listing,
            source=NAME,
            playbook="author_site",
            note=f"{author.name or author.fingerprint} listing pdf",
        )
    try:
        resp = ctx.client.get(listing, timeout=20, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError:
        return Candidate.miss(NAME, Outcome.ERROR, "listing fetch failed")
    html = resp.text or ""
    pdfs = extract_pdf_urls(html, str(resp.url))
    title = item.title or ""
    doi = (item.doi or "").lower()
    picked: list[str] = []
    for url in pdfs:
        blob = url.lower()
        if doi and doi in blob:
            picked.append(url)
            continue
        if title and title_similarity(title, url) >= _TITLE_MIN:
            picked.append(url)
            continue
        host = (urlparse(url).hostname or "").lower()
        last = (author.fingerprint.split("|", 1)[0] if author.fingerprint else "").lower()
        if last and last in blob and looks_like_pdf_url(url):
            picked.append(url)
    if not picked and pdfs:
        # One listing may still be the author's publications page; take .pdf links on-host.
        host = (urlparse(listing).hostname or "").lower()
        picked = [
            u
            for u in pdfs
            if looks_like_pdf_url(u) and (urlparse(u).hostname or "").lower() == host
        ][:3]
    if not picked:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no title/DOI pdf on listing")
    return Candidate(
        url=picked[0],
        source=NAME,
        playbook="author_site",
        note=f"{author.name or author.fingerprint} {author.base_host}",
        alternates=picked[1:],
    )
