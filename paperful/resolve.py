"""Identifier extraction / normalisation and title→DOI enrichment."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

# Parentheses are legal inside DOIs (old Elsevier: 10.1016/0031-9384(69)90073-0); brackets/braces are not.
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>\[\]\{\}]+)", re.IGNORECASE)
ARXIV_NEW_RE = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(v\d+)?(?!\d)")
ARXIV_OLD_RE = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b")
PMID_RE = re.compile(r"(?im)^\s*(?:PMID|PubMed PMID|PubMed ID):\s*(\d+)\b")
_TRAILING_PUNCT_NO_PAREN = ".,;:>\"'"


def normalize_doi(raw: str | None) -> str | None:
    """Lower-case a DOI and strip resolver prefixes and trailing punctuation."""
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^doi:\s*", "", s, flags=re.IGNORECASE)
    m = DOI_RE.search(s)
    if not m:
        return None
    doi = m.group(1).rstrip(_TRAILING_PUNCT_NO_PAREN)
    # A trailing ')' belongs to the DOI only if it closes a '(' inside it: "(doi:10.1/x)" vs "10.1016/...(69)90073-0"
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(_TRAILING_PUNCT_NO_PAREN)
    doi = doi.rstrip("/")
    # Common URL suffixes glued to DOIs in URL fields
    doi = re.sub(
        r"/(?:full|abstract|pdf|epdf|meta|summary)$", "", doi, flags=re.IGNORECASE
    )
    return doi.lower()


def extract_doi(text: str | None) -> str | None:
    """Find the first DOI in free text (Zotero `extra`, URL, ...)."""
    if not text:
        return None
    m = re.search(r"(?im)^\s*DOI:\s*(\S+)", text)
    if m:
        d = normalize_doi(m.group(1))
        if d:
            return d
    return normalize_doi(text)


def extract_pmid(text: str | None) -> str | None:
    """Find a PubMed ID in Zotero `extra` (or similar free text)."""
    if not text:
        return None
    m = PMID_RE.search(text)
    return m.group(1) if m else None


def extract_arxiv_id(text: str | None) -> str | None:
    """Find an arXiv identifier in a URL or `extra` field."""
    if not text:
        return None
    if "arxiv" not in text.lower():
        return None
    m = re.search(r"(?im)^\s*arXiv:\s*(\S+)", text)
    if m:
        cand = m.group(1)
    else:
        cand = text
    m2 = ARXIV_NEW_RE.search(cand)
    if m2:
        return m2.group(1)
    m3 = ARXIV_OLD_RE.search(cand)
    if m3:
        return m3.group(1)
    return None


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def title_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


@dataclass
class CrossrefMatch:
    doi: str
    score: float
    title: str
    year: int | None


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


def short_title(title: str) -> str | None:
    """Leading segment before '. ', ': ', ' | ' or ' - ' if it is still a meaningful title."""
    m = re.split(r"(?<=[a-z0-9\)])\.\s+|:\s+|\s+\|\s+|\s+[-–—]\s+", title, maxsplit=1)
    head = m[0].strip() if m else ""
    return head if len(head.split()) >= 4 else None


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


def _issued_year(work: dict[str, Any]) -> int | None:
    parts = _best_date_parts(work)
    if parts and parts[0]:
        try:
            return int(parts[0])
        except (TypeError, ValueError):
            return None
    return None


def _best_date_parts(work: dict[str, Any]) -> list[Any] | None:
    """Prefer issued, then published-print, then published-online date-parts."""
    for key in ("issued", "published-print", "published-online"):
        parts = (work.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            return list(parts[0])
    return None


def format_date_parts(parts: list[Any] | None) -> str | None:
    """Format Crossref-style date-parts as YYYY, YYYY-MM, or YYYY-MM-DD."""
    if not parts or parts[0] is None:
        return None
    try:
        year = int(parts[0])
    except (TypeError, ValueError):
        return None
    if len(parts) >= 3 and parts[1] is not None and parts[2] is not None:
        try:
            return f"{year:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except (TypeError, ValueError):
            pass
    if len(parts) >= 2 and parts[1] is not None:
        try:
            return f"{year:04d}-{int(parts[1]):02d}"
        except (TypeError, ValueError):
            pass
    return str(year)


def date_precision(date: str | None) -> int:
    """0 = empty/junk, 1 = year, 2 = year-month, 3 = year-month-day."""
    if not date or not date.strip():
        return 0
    s = date.strip()
    m = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$", s)
    if m:
        if m.group(3):
            return 3
        if m.group(2):
            return 2
        return 1
    if not re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", s):
        return 0
    if re.search(r"[A-Za-z]", s) and re.search(r"\b\d{1,2}\b", s):
        return 2
    return 1


def strip_title_markup(title: str) -> str:
    """Unescape entities and strip HTML tags; collapse whitespace."""
    import html

    t = html.unescape(title or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(t.split()).strip()


# ---- enrichment (URL rewrite + Crossref + OpenAlex + Semantic Scholar) ------

_SKIP_ENRICH_TYPES = frozenset({"webpage", "blogPost", "forumPost"})
_AGGREGATOR_HOSTS = (
    "consensus.app",
    "semanticscholar.org",
    "www.semanticscholar.org",
    "researchgate.net",
    "www.researchgate.net",
)
_DOI_META_NAMES = re.compile(
    r"^(?:citation_doi|dc\.identifier|dc\.identifier\.doi|bepress_citation_doi)$",
    re.I,
)


class Enrichable(Protocol):
    """Minimal item surface for title→DOI enrichment (avoids importing zot.Item)."""

    doi: str | None
    doi_source: str
    item_type: str
    title: str
    url: str | None
    first_author: str | None
    year: int | None
    library_doi: str | None
    pmid: str | None
    doi_verified: str


@dataclass
class EnrichMatch:
    doi: str
    source: str  # url | meta | crossref | openalex | semanticscholar | pubmed
    score: float = 1.0
    title: str = ""
    year: int | None = None


@dataclass
class WorkMeta:
    doi: str
    title: str = ""
    year: int | None = None
    date: str | None = None  # richest available: YYYY / YYYY-MM / YYYY-MM-DD
    first_author: str | None = None
    venue: str | None = None
    source: str = ""  # crossref | openalex | semanticscholar | pubmed


@dataclass
class VerifyResult:
    status: str  # ok | suspect | unknown | missing
    score: float = 0.0
    work: WorkMeta | None = None
    note: str = ""


class IdentifierCache:
    """Per-run cache so verify + lint + sources do not triple-hit Crossref."""

    def __init__(self) -> None:
        self.works: dict[str, WorkMeta | None] = {}
        self.pmids: dict[str, str | None] = {}


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
            f"https://api.crossref.org/works/{doi}", params=params or None, timeout=30
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        msg = resp.json().get("message") or {}
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    titles = msg.get("title") or []
    title = titles[0] if titles else ""
    authors = msg.get("author") or []
    first = None
    if authors:
        first = authors[0].get("family") or authors[0].get("name")
    venue_list = msg.get("container-title") or []
    parts = _best_date_parts(msg)
    year = None
    if parts and parts[0] is not None:
        try:
            year = int(parts[0])
        except (TypeError, ValueError):
            year = None
    return WorkMeta(
        doi=normalize_doi(msg.get("DOI") or doi) or doi.lower(),
        title=title,
        year=year,
        date=format_date_parts(parts),
        first_author=first,
        venue=venue_list[0] if venue_list else None,
        source="crossref",
    )


def _openalex_work(client: httpx.Client, doi: str, email: str) -> WorkMeta | None:
    params: dict[str, Any] = {}
    if email:
        params["mailto"] = email
    try:
        resp = client.get(
            f"https://api.openalex.org/works/https://doi.org/{doi}",
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
    )


def doi_from_url(url: str | None) -> EnrichMatch | None:
    if not url:
        return None
    doi = normalize_doi(url)
    if doi:
        return EnrichMatch(doi=doi, source="url")
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.")
    qs = parse_qs(parsed.query)
    for key in ("doi", "DOI"):
        if key in qs and qs[key]:
            d = normalize_doi(qs[key][0])
            if d:
                return EnrichMatch(doi=d, source="url")
    if host in {"doi.org", "dx.doi.org"}:
        d = normalize_doi(parsed.path.lstrip("/"))
        if d:
            return EnrichMatch(doi=d, source="url")
    # consensus.app/.../10.1234/... or path segments that look like DOIs
    if "consensus.app" in host:
        d = normalize_doi(parsed.path) or normalize_doi(url)
        if d:
            return EnrichMatch(doi=d, source="url")
    return None


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


def _is_aggregator_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in _AGGREGATOR_HOSTS)


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


def _author_hint_ok(author: str, authorships: list | None) -> bool:
    if not authorships:
        return True
    needle = author.strip().lower().split()[-1]
    if len(needle) < 2:
        return True
    for a in authorships[:8]:
        display = ((a.get("author") or {}).get("display_name") or "").lower()
        if needle in display:
            return True
    return False


def _ss_author_ok(author: str, authors: list | None) -> bool:
    if not authors:
        return True
    needle = author.strip().lower().split()[-1]
    if len(needle) < 2:
        return True
    for a in authors[:8]:
        if needle in (a.get("name") or "").lower():
            return True
    return False
