"""Pure identifier and title helpers. No network."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'\[\]\{\}]+)", re.IGNORECASE)

ARXIV_NEW_RE = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(v\d+)?(?!\d)")

ARXIV_OLD_RE = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b")

PMID_RE = re.compile(r"(?im)^\s*(?:PMID|PubMed PMID|PubMed ID):\s*(\d+)\b")

_TRAILING_PUNCT_NO_PAREN = ".,;:>\"'"

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

PREPRINT_DOI_PREFIXES = ("10.48550/arxiv.", "10.1101/")

_CROSSREF_ITEM_TYPE = {
    "journal-article": "journalArticle",
    "proceedings-article": "conferencePaper",
    "book-chapter": "bookSection",
    "book": "book",
    "posted-content": "preprint",
    "report": "report",
    "dissertation": "thesis",
}

_ARXIV_ATOM = "http://www.w3.org/2005/Atom"

_ARXIV_NS = "http://arxiv.org/schemas/atom"


def normalize_doi(raw: str | None) -> str | None:
    """Lower-case a DOI and strip resolver prefixes and trailing punctuation."""
    if not raw:
        return None
    s = raw.strip()
    s = s.translate(
        str.maketrans(
            {
                "\u2010": "-",  # hyphen
                "\u2011": "-",  # non-breaking hyphen
                "\u2012": "-",
                "\u2013": "-",  # en dash
                "\u2212": "-",  # minus
            }
        )
    )
    s = re.sub(r"-{2,}", "-", s)
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
    # Springer and similar links append /figures/5 or /metrics to a real DOI.
    while True:
        cleaned = re.sub(r"/(?:figures|tables)/\d+$", "", doi, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"/(?:full|abstract|pdf|epdf|meta|summary|metrics)$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = cleaned.rstrip("/")
        if cleaned == doi:
            break
        doi = cleaned
    # Old Wiley SICI DOIs use "<page::AID-...>". A stored single colon does not resolve.
    doi = re.sub(r"(<\d+):(?=aid-)", r"\1::", doi, flags=re.IGNORECASE)
    # Crossref sometimes appends ".pmid:123;pmcid:PMC1" to an otherwise real DOI.
    doi = re.split(r"(?i)[.;](?:pmid|pmcid):", doi, maxsplit=1)[0]
    doi = doi.rstrip(_TRAILING_PUNCT_NO_PAREN).rstrip("/")
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


def short_title(title: str) -> str | None:
    """Leading segment before '. ', ': ', ' | ' or ' - ' if it is still a meaningful title."""
    m = re.split(r"(?<=[a-z0-9\)])\.\s+|:\s+|\s+\|\s+|\s+[-–—]\s+", title, maxsplit=1)
    head = m[0].strip() if m else ""
    return head if len(head.split()) >= 4 else None


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
    work_type: str = ""  # Crossref/OpenAlex type, e.g. book-chapter
    book_title: str | None = None
    series_title: str | None = None
    pages: str | None = None


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
        self.versions: dict[str, VersionLink | None] = {}


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


def _is_aggregator_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in _AGGREGATOR_HOSTS)


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


@dataclass
class VersionLink:
    """High-confidence preprint ↔ version-of-record edge. OpenAlex is not a source."""

    preprint_doi: str | None
    published_doi: str
    source: str  # crossref | arxiv | biorxiv
    arxiv_id: str | None = None
    item_type: str = "journalArticle"
    published: WorkMeta | None = None


def is_preprint_doi(doi: str | None) -> bool:
    key = normalize_doi(doi) or ""
    return key.startswith(PREPRINT_DOI_PREFIXES)


def arxiv_id_from_doi(doi: str | None) -> str | None:
    key = normalize_doi(doi) or ""
    prefix = "10.48550/arxiv."
    if not key.startswith(prefix):
        return None
    return key[len(prefix) :] or None


def version_from_crossref(
    message: dict[str, Any], query_doi: str
) -> VersionLink | None:
    """Read Crossref ``is-preprint-of`` / ``has-preprint``. Other relations are ignored."""
    query = normalize_doi(query_doi)
    if not query or not isinstance(message, dict):
        return None
    relation = message.get("relation") or {}
    if not isinstance(relation, dict):
        return None
    preprint_of = _relation_doi(relation.get("is-preprint-of"), query)
    has_preprint = _relation_doi(relation.get("has-preprint"), query)
    if preprint_of:
        preprint, published = query, preprint_of
        item_type = "journalArticle"
        published_meta = None
    elif has_preprint:
        preprint, published = has_preprint, query
        item_type = _zotero_type(message.get("type"))
        published_meta = _work_from_crossref_message(message, published)
    else:
        return None
    return VersionLink(
        preprint_doi=preprint,
        published_doi=published,
        source="crossref",
        arxiv_id=arxiv_id_from_doi(preprint),
        item_type=item_type,
        published=published_meta,
    )


def version_from_arxiv_xml(
    xml_text: str, query_doi: str | None = None
) -> VersionLink | None:
    """Read ``arxiv:doi`` from an Atom entry. A missing DOI is not a link."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    doi_el = root.find(f".//{{{_ARXIV_NS}}}doi")
    published = normalize_doi(doi_el.text if doi_el is not None else None)
    if not published or is_preprint_doi(published):
        journal_ref = root.findtext(f".//{{{_ARXIV_NS}}}journal_ref") or ""
        published = normalize_doi(journal_ref)
    if not published or is_preprint_doi(published):
        return None
    ident = root.findtext(f".//{{{_ARXIV_ATOM}}}id") or ""
    m = ARXIV_NEW_RE.search(ident) or ARXIV_OLD_RE.search(ident)
    arxiv_id = m.group(1) if m else arxiv_id_from_doi(query_doi)
    preprint = f"10.48550/arxiv.{arxiv_id}" if arxiv_id else normalize_doi(query_doi)
    if preprint and normalize_doi(preprint) == published:
        return None
    return VersionLink(
        preprint_doi=preprint,
        published_doi=published,
        source="arxiv",
        arxiv_id=arxiv_id,
        item_type="journalArticle",
    )


def version_from_biorxiv(payload: dict[str, Any], query_doi: str) -> VersionLink | None:
    """Read bioRxiv/medRxiv ``published``. ``NA`` and the preprint DOI itself are not links."""
    query = normalize_doi(query_doi)
    collection = payload.get("collection") if isinstance(payload, dict) else None
    if not query or not isinstance(collection, list):
        return None
    published = None
    for record in collection:
        if not isinstance(record, dict):
            continue
        candidate = normalize_doi(str(record.get("published") or ""))
        if (
            candidate
            and candidate not in {"na"}
            and candidate != query
            and not is_preprint_doi(candidate)
        ):
            published = candidate
    if not published:
        return None
    return VersionLink(
        preprint_doi=query,
        published_doi=published,
        source="biorxiv",
        item_type="journalArticle",
    )


def version_from_openalex(payload: dict[str, Any]) -> VersionLink | None:
    """OpenAlex ``related_works`` and locations are not version edges."""
    del payload
    return None


def _relation_doi(entries: Any, query: str) -> str | None:
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        id_type = str(entry.get("id-type") or "doi").lower()
        if id_type != "doi":
            continue
        other = normalize_doi(str(entry.get("id") or ""))
        if other and other != query:
            return other
    return None


def _zotero_type(crossref_type: Any) -> str:
    return _CROSSREF_ITEM_TYPE.get(str(crossref_type or ""), "journalArticle")


def container_titles_for_type(
    work_type: str, container_titles: list[Any]
) -> tuple[str | None, str | None, str | None]:
    """Map Crossref ``container-title`` to venue / book / series.

    Book chapters often list series then book (Springer). Prefer the last
    title as the book (venue); the first as series when there are two+.
    """
    cleaned = [
        strip_title_markup(str(item))
        for item in container_titles
        if str(item or "").strip()
    ]
    cleaned = [item for item in cleaned if item]
    if not cleaned:
        return None, None, None
    if work_type == "book-chapter" and len(cleaned) >= 2:
        series_title = cleaned[0]
        book_title = cleaned[-1]
        return book_title, book_title, series_title
    venue = cleaned[0]
    if work_type == "book-chapter":
        return venue, venue, None
    return venue, None, None


def _work_from_crossref_message(msg: dict[str, Any], doi: str) -> WorkMeta:
    titles = msg.get("title") or []
    title = strip_title_markup(titles[0]) if titles else ""
    authors = msg.get("author") or []
    first = None
    if authors and isinstance(authors[0], dict):
        first = authors[0].get("family") or authors[0].get("name")
    work_type = str(msg.get("type") or "")
    venue, book_title, series_title = container_titles_for_type(
        work_type, list(msg.get("container-title") or [])
    )
    pages = str(msg.get("page") or "").strip() or None
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
        venue=venue or None,
        source="crossref",
        work_type=work_type,
        book_title=book_title,
        series_title=series_title,
        pages=pages,
    )


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
