"""Crossref / OpenAlex / S2 enrichment and version links."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from .ids import (
    CrossrefMatch,
    EnrichMatch,
    Enrichable,
    IdentifierCache,
    VerifyResult,
    VersionLink,
    WorkMeta,
    _DOI_META_NAMES,
    _SKIP_ENRICH_TYPES,
    _author_hint_ok,
    _is_aggregator_url,
    _issued_year,
    _ss_author_ok,
    _work_from_crossref_message,
    _zotero_type,
    arxiv_id_from_doi,
    doi_from_url,
    normalize_doi,
    normalize_title,
    short_title,
    title_similarity,
    version_from_arxiv_xml,
    version_from_biorxiv,
    version_from_crossref,
)


def crossref_lookup(
    client: httpx.Client,
    title: str,
    author: str | None = None,
    year: int | None = None,
    email: str = "",
    min_score: float = 0.90,
) -> CrossrefMatch | None:
    """Find a DOI for a title via Crossref; accept only confident matches.

    Zotero titles often carry a glued-on subtitle ("Main title. Subtitle...") that Crossref
    does not index as part of the title, so a second query uses the leading segment only.
    """
    if not title or len(normalize_title(title)) < 12:
        return None
    variants = [title]
    short = short_title(title)
    if short and short != title:
        variants.append(short)
    for variant in variants:
        match = _crossref_query(
            client, variant, variants, author, year, email, min_score
        )
        if match:
            return match
    return None


def _crossref_query(
    client: httpx.Client,
    query: str,
    accept_titles: list[str],
    author: str | None,
    year: int | None,
    email: str,
    min_score: float,
) -> CrossrefMatch | None:
    params: dict[str, Any] = {
        "query.bibliographic": query,
        "rows": 5,
        "select": "DOI,title,issued,author",
    }
    if author:
        params["query.author"] = author
    if email:
        params["mailto"] = email
    try:
        resp = client.get("https://api.crossref.org/works", params=params, timeout=30)
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
    except (httpx.HTTPError, ValueError):
        return None
    best: CrossrefMatch | None = None
    for it in items:
        titles = it.get("title") or []
        if not titles:
            continue
        score = max(title_similarity(mine, t) for t in titles for mine in accept_titles)
        cr_year = _issued_year(it)
        if year and cr_year and abs(cr_year - year) > 1:
            score -= 0.1
        if best is None or score > best.score:
            best = CrossrefMatch(
                doi=it["DOI"].lower(), score=score, title=titles[0], year=cr_year
            )
    if best and best.score >= min_score:
        return best
    return None


def enrich_identifiers(
    client: httpx.Client,
    item: Enrichable,
    email: str = "",
    min_score: float = 0.90,
) -> list[str]:
    """Fill `item.doi` when missing. Mutates item in place. Returns attempt strings.

    Order: URL/path DOI → page meta DOI → Crossref → OpenAlex → Semantic Scholar.
    Skips web/blog/forum types (those are HTML→PDF territory).
    """
    attempts: list[str] = []
    if item.doi or item.item_type in _SKIP_ENRICH_TYPES:
        return attempts
    if not item.title or len(normalize_title(item.title)) < 12:
        # Still try URL-only DOI extraction.
        match = doi_from_url(item.url)
        if match:
            item.doi, item.doi_source = match.doi, match.source
            attempts.append(f"{match.source}:matched")
        return attempts

    match = doi_from_url(item.url)
    if match:
        item.doi, item.doi_source = match.doi, match.source
        attempts.append(f"{match.source}:matched")
        return attempts

    if item.url and _is_aggregator_url(item.url):
        meta = doi_from_page_meta(client, item.url)
        if meta:
            item.doi, item.doi_source = meta.doi, meta.source
            attempts.append(f"{meta.source}:matched")
            return attempts
        attempts.append("meta:no-doi")

    cr = crossref_lookup(
        client, item.title, item.first_author, item.year, email, min_score
    )
    if cr:
        item.doi, item.doi_source = cr.doi, "crossref"
        attempts.append(f"crossref:matched({cr.score:.2f})")
        return attempts
    attempts.append("crossref:no-match")

    oa = openalex_title_lookup(
        client, item.title, item.first_author, item.year, email, min_score
    )
    if oa:
        item.doi, item.doi_source = oa.doi, oa.source
        attempts.append(f"openalex:matched({oa.score:.2f})")
        return attempts
    attempts.append("openalex:no-match")

    ss = semanticscholar_title_lookup(
        client, item.title, item.first_author, item.year, min_score
    )
    if ss:
        item.doi, item.doi_source = ss.doi, ss.source
        attempts.append(f"semanticscholar:matched({ss.score:.2f})")
        return attempts
    attempts.append("semanticscholar:no-match")
    return attempts


def work_by_doi(
    client: httpx.Client,
    doi: str,
    email: str = "",
    cache: IdentifierCache | None = None,
) -> WorkMeta | None:
    """Resolve a DOI to WorkMeta. Crossref first, then OpenAlex. None = unknown (API miss or empty)."""
    key = doi.lower()
    if cache is not None and key in cache.works:
        return cache.works[key]
    work = _crossref_work(client, doi, email) or _openalex_work(client, doi, email)
    if cache is not None:
        cache.works[key] = work
    return work


def verify_doi(
    client: httpx.Client,
    item: Enrichable,
    email: str = "",
    min_score: float = 0.90,
    suspect_score: float = 0.70,
    cache: IdentifierCache | None = None,
) -> VerifyResult:
    """Check the library DOI against Crossref/OpenAlex title similarity."""
    if not item.doi:
        return VerifyResult(status="missing", note="no DOI")
    work = work_by_doi(client, item.doi, email, cache)
    if work is None:
        return VerifyResult(status="unknown", note="no work record")
    score = title_similarity(item.title, work.title)
    if item.year and work.year and abs(work.year - item.year) > 1:
        score -= 0.1
    if score >= min_score:
        return VerifyResult(status="ok", score=score, work=work)
    if score < suspect_score:
        return VerifyResult(
            status="suspect", score=score, work=work, note="title mismatch"
        )
    return VerifyResult(status="unknown", score=score, work=work, note="weak match")


def pmid_to_doi(
    client: httpx.Client,
    pmid: str,
    email: str = "",
    cache: IdentifierCache | None = None,
) -> str | None:
    if cache is not None and pmid in cache.pmids:
        return cache.pmids[pmid]
    doi: str | None = None
    params: dict[str, Any] = {"ids": pmid, "format": "json", "tool": "paperful"}
    if email:
        params["email"] = email
    try:
        resp = client.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            params=params,
            timeout=30,
        )
        if resp.status_code < 400:
            records = resp.json().get("records") or []
            if records:
                doi = normalize_doi(records[0].get("doi"))
    except (httpx.HTTPError, ValueError, TypeError):
        doi = None
    if cache is not None:
        cache.pmids[pmid] = doi
    return doi


def prepare_identifiers(
    client: httpx.Client,
    item: Enrichable,
    email: str = "",
    min_score: float = 0.90,
    suspect_score: float = 0.70,
    verify: bool = True,
    cache: IdentifierCache | None = None,
) -> list[str]:
    """Fill/verify DOI in memory. Never writes to a reference manager.

    Swap the working DOI only when the library DOI is suspect and a replacement
    scores at or above min_score. API failure (`unknown`) keeps the original DOI.
    """
    notes: list[str] = []
    if item.library_doi is None and item.doi:
        item.library_doi = item.doi
    if item.item_type in _SKIP_ENRICH_TYPES:
        item.doi_verified = "unknown" if item.doi else "missing"
        return notes

    if item.doi and verify:
        result = verify_doi(client, item, email, min_score, suspect_score, cache)
        notes.append(
            f"verify:{result.status}({result.score:.2f})"
            if result.score
            else f"verify:{result.status}"
        )
        if result.status == "ok":
            item.doi_verified = "ok"
            return notes
        if result.status == "unknown":
            item.doi_verified = "unknown"
            return notes
        # A blank or citation-string title cannot identify a replacement work.
        # Keep the library DOI so fix-metadata can fill the title from it.
        from ..lint import usable_work_title

        if not usable_work_title(item.title):
            item.doi_verified = "suspect"
            notes.append("verify:kept-doi(unusable title)")
            return notes
        original = item.doi
        original_source = item.doi_source
        item.doi = None
        notes.extend(enrich_identifiers(client, item, email, min_score))
        if not item.doi and getattr(item, "pmid", None):
            doi = pmid_to_doi(client, item.pmid, email, cache)
            if doi:
                item.doi, item.doi_source = doi, "pubmed"
                notes.append("pubmed:matched")
            else:
                notes.append("pubmed:no-doi")
        if item.doi and item.doi != original:
            item.doi_verified = "swapped"
            notes.append(f"swap:{original}->{item.doi}")
        else:
            item.doi = original
            item.doi_source = original_source
            item.doi_verified = "suspect"
        return notes

    if not item.doi and getattr(item, "pmid", None):
        doi = pmid_to_doi(client, item.pmid, email, cache)
        if doi:
            item.doi, item.doi_source = doi, "pubmed"
            item.doi_verified = "ok"
            notes.append("pubmed:matched")
            return notes
        notes.append("pubmed:no-doi")

    notes.extend(enrich_identifiers(client, item, email, min_score))
    if item.doi:
        item.doi_verified = "unknown" if (item.library_doi and not verify) else "ok"
    else:
        item.doi_verified = "missing"
    return notes


def _crossref_work(client: httpx.Client, doi: str, email: str) -> WorkMeta | None:
    params: dict[str, Any] = {}
    if email:
        params["mailto"] = email
    try:
        resp = client.get(
            "https://api.crossref.org/works/" + quote(doi, safe="/()"),
            params=params or None,
            timeout=30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        msg = resp.json().get("message") or {}
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    return _work_from_crossref_message(msg, doi)


def _openalex_work(client: httpx.Client, doi: str, email: str) -> WorkMeta | None:
    params: dict[str, Any] = {}
    if email:
        params["mailto"] = email
    try:
        resp = client.get(
            "https://api.openalex.org/works/https://doi.org/" + quote(doi, safe="/()"),
            params=params or None,
            timeout=30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    doi_raw = data.get("doi") or ""
    resolved = normalize_doi(doi_raw.replace("https://doi.org/", "")) or doi.lower()
    authorships = data.get("authorships") or []
    first = None
    if authorships:
        first = ((authorships[0].get("author") or {}).get("display_name")) or None
    loc = data.get("primary_location") or {}
    source = loc.get("source") or {}
    venue = source.get("display_name") if isinstance(source, dict) else None
    work_type = str(data.get("type") or "")
    series_title = venue if work_type == "book-chapter" and venue else None
    # OpenAlex rarely separates book vs series; prefer raw_source_name only when
    # it differs from the series display name (otherwise leave book_title empty).
    raw_source = ""
    if isinstance(loc, dict):
        raw_source = str(loc.get("raw_source_name") or "").strip()
    book_title = None
    if work_type == "book-chapter" and raw_source and raw_source != (venue or ""):
        book_title = raw_source
        venue = book_title
    year = data.get("publication_year")
    try:
        year_i = int(year) if year else None
    except (TypeError, ValueError):
        year_i = None
    pub_date = data.get("publication_date")
    date_str: str | None = None
    if isinstance(pub_date, str) and re.match(
        r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$", pub_date.strip()
    ):
        date_str = pub_date.strip()
    elif year_i is not None:
        date_str = str(year_i)
    return WorkMeta(
        doi=resolved,
        title=data.get("display_name") or "",
        year=year_i,
        date=date_str,
        first_author=first,
        venue=venue,
        source="openalex",
        work_type=work_type,
        book_title=book_title,
        series_title=series_title,
    )


def doi_from_page_meta(client: httpx.Client, url: str) -> EnrichMatch | None:
    try:
        resp = client.get(url, timeout=20)
        if (
            resp.status_code >= 400
            or "html" not in resp.headers.get("content-type", "").lower()
        ):
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
    except (httpx.HTTPError, ValueError):
        return None
    for meta in soup.find_all("meta"):
        name = str(meta.get("name") or meta.get("property") or "")
        content = (meta.get("content") or "").strip()
        if not content:
            continue
        if _DOI_META_NAMES.match(name) or content.lower().startswith("doi:"):
            d = normalize_doi(content)
            if d:
                return EnrichMatch(doi=d, source="meta")
    return None


def openalex_title_lookup(
    client: httpx.Client,
    title: str,
    author: str | None,
    year: int | None,
    email: str,
    min_score: float,
) -> EnrichMatch | None:
    params: dict[str, Any] = {"search": title, "per_page": 5}
    if email:
        params["mailto"] = email
    try:
        resp = client.get("https://api.openalex.org/works", params=params, timeout=30)
        resp.raise_for_status()
        results = resp.json().get("results") or []
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    best: EnrichMatch | None = None
    for it in results:
        doi_raw = it.get("doi") or ""
        doi = normalize_doi(doi_raw.replace("https://doi.org/", ""))
        if not doi:
            continue
        titles = [it.get("display_name") or ""]
        score = max((title_similarity(title, t) for t in titles), default=0.0)
        pub_year = it.get("publication_year")
        if year and pub_year and abs(int(pub_year) - year) > 1:
            score -= 0.1
        if author and not _author_hint_ok(author, it.get("authorships")):
            score -= 0.05
        if best is None or score > best.score:
            best = EnrichMatch(
                doi=doi, source="openalex", score=score, title=titles[0], year=pub_year
            )
    if best and best.score >= min_score:
        return best
    return None


def semanticscholar_title_lookup(
    client: httpx.Client,
    title: str,
    author: str | None,
    year: int | None,
    min_score: float,
) -> EnrichMatch | None:
    params = {
        "query": title,
        "limit": 5,
        "fields": "title,year,externalIds,authors",
    }
    try:
        resp = client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params,
            timeout=30,
        )
        if resp.status_code >= 400:
            return None
        results = resp.json().get("data") or []
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    best: EnrichMatch | None = None
    for it in results:
        ext = it.get("externalIds") or {}
        doi = normalize_doi(ext.get("DOI"))
        if not doi:
            continue
        score = title_similarity(title, it.get("title"))
        pub_year = it.get("year")
        if year and pub_year and abs(int(pub_year) - year) > 1:
            score -= 0.1
        if author and not _ss_author_ok(author, it.get("authors")):
            score -= 0.05
        if best is None or score > best.score:
            best = EnrichMatch(
                doi=doi,
                source="semanticscholar",
                score=score,
                title=it.get("title") or "",
                year=pub_year,
            )
    if best and best.score >= min_score:
        return best
    return None


def version_link(
    client: httpx.Client,
    doi: str,
    email: str = "",
    cache: IdentifierCache | None = None,
) -> VersionLink | None:
    """High-confidence preprint ↔ published DOI. None when no Crossref, arXiv, or bioRxiv edge."""
    key = normalize_doi(doi)
    if not key:
        return None
    if cache is not None and key in cache.versions:
        return cache.versions[key]
    link = _version_link_uncached(client, key, email)
    if link and link.published is None:
        link.published = work_by_doi(client, link.published_doi, email, cache)
        if link.item_type == "journalArticle" and link.published is None:
            link.item_type = "journalArticle"
    if cache is not None:
        cache.versions[key] = link
        if link is not None:
            cache.versions.setdefault(link.published_doi, link)
            if link.preprint_doi:
                cache.versions.setdefault(link.preprint_doi, link)
    return link


def _version_link_uncached(
    client: httpx.Client,
    doi: str,
    email: str,
) -> VersionLink | None:
    message = _crossref_message(client, doi, email)
    if message:
        link = version_from_crossref(message, doi)
        if link:
            if link.published is None:
                published_msg = _crossref_message(client, link.published_doi, email)
                if published_msg:
                    link.item_type = _zotero_type(published_msg.get("type"))
                    link.published = _work_from_crossref_message(
                        published_msg, link.published_doi
                    )
            return link
    arxiv_id = arxiv_id_from_doi(doi)
    if arxiv_id:
        xml_text = _arxiv_atom(client, arxiv_id)
        if xml_text:
            link = version_from_arxiv_xml(xml_text, doi)
            if link:
                return link
    if doi.startswith("10.1101/"):
        for server in ("biorxiv", "medrxiv"):
            payload = _get_json(
                client, f"https://api.biorxiv.org/details/{server}/{doi}"
            )
            if not payload:
                continue
            link = version_from_biorxiv(payload, doi)
            if link:
                return link
    return None


def _crossref_message(
    client: httpx.Client, doi: str, email: str
) -> dict[str, Any] | None:
    params: dict[str, Any] = {}
    if email:
        params["mailto"] = email
    payload = _get_json(
        client, f"https://api.crossref.org/works/{doi}", params=params or None
    )
    if not payload:
        return None
    msg = payload.get("message")
    return msg if isinstance(msg, dict) else None


def _arxiv_atom(client: httpx.Client, arxiv_id: str) -> str | None:
    try:
        resp = client.get(
            "https://export.arxiv.org/api/query",
            params={"id_list": arxiv_id},
            timeout=30,
        )
        if resp.status_code >= 400:
            return None
        text = resp.text or ""
    except (httpx.HTTPError, ValueError):
        return None
    if "doi" not in text.lower():
        return None
    return text


def _get_json(
    client: httpx.Client, url: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    try:
        resp = client.get(url, params=params, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None
