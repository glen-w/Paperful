"""Non-DOI grey identity: ISBN, report number, and title|year|host.

Large publisher and resolver hosts are not registrant hosts. A title+year
hit is refused when both sides have a host and the hosts differ.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# eTLD+1 suffixes that identify a platform, not a grey publisher.
_PLATFORM_SUFFIXES = (
    "doi.org",
    "crossref.org",
    "unpaywall.org",
    "openalex.org",
    "semanticscholar.org",
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "ssrn.com",
    "researchgate.net",
    "academia.edu",
    "wiley.com",
    "springer.com",
    "springerlink.com",
    "sciencedirect.com",
    "elsevier.com",
    "tandfonline.com",
    "sagepub.com",
    "nature.com",
    "science.org",
    "sciencemag.org",
    "pnas.org",
    "oup.com",
    "oxfordacademic.com",
    "cambridge.org",
    "ieee.org",
    "acm.org",
    "jstor.org",
    "nih.gov",
    "ncbi.nlm.nih.gov",
    "europepmc.org",
    "mdpi.com",
    "frontiersin.org",
    "plos.org",
    "hindawi.com",
    "google.com",
    "googleusercontent.com",
)

_ISBN_RE = re.compile(
    r"\b(?:97[89][-\s]?)?(?:\d[-\s]?){9}[\dXx]\b",
)
_REPORT_RE = re.compile(
    r"(?i)\b(?:report(?:\s+(?:no|number|#))?|rpt)[:\s.#-]*([A-Z0-9][A-Z0-9./-]{2,})\b"
)
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_EXTRA_ISBN = re.compile(r"(?im)^ISBN:\s*(\S+)")
_EXTRA_REPORT = re.compile(r"(?im)^Report(?:\s+Number)?:\s*(.+)$")


def _host(url: str | None) -> str:
    if not url:
        return ""
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _platform(host: str) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in _PLATFORM_SUFFIXES)


def registrable_host(url: str | None) -> str:
    """eTLD+1 of ``url``, or empty for resolvers and large publisher platforms."""
    host = _host(url)
    if not host or _platform(host):
        return ""
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def normalize_isbn(value: str | None) -> str:
    raw = re.sub(r"[^0-9Xx]", "", value or "")
    return raw.upper()


def normalize_report_number(value: str | None) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip())
    return text.upper()


def isbn_from_text(text: str | None) -> str:
    match = _ISBN_RE.search(text or "")
    return normalize_isbn(match.group(0) if match else "")


def report_from_text(text: str | None) -> str:
    match = _REPORT_RE.search(text or "")
    return normalize_report_number(match.group(1) if match else "")


def host_from_text(text: str | None) -> str:
    for match in _URL_RE.finditer(text or ""):
        host = registrable_host(match.group(0).rstrip(".,;"))
        if host:
            return host
    return ""


def identifiers_from_item(item: object) -> tuple[str, str, str]:
    """ISBN, report number, and registrant host from an item or record-like object."""
    isbn = normalize_isbn(getattr(item, "isbn", None) or "")
    report = normalize_report_number(getattr(item, "report_number", None) or "")
    extra = str(getattr(item, "extra", "") or "")
    if not isbn:
        found = _EXTRA_ISBN.search(extra)
        isbn = normalize_isbn(found.group(1) if found else "")
    if not report:
        found = _EXTRA_REPORT.search(extra)
        report = normalize_report_number(found.group(1) if found else "")
    host = registrable_host(getattr(item, "url", None))
    return isbn, report, host


def grey_key(
    title: str | None,
    year: object,
    *,
    url: str | None = None,
    host: str | None = None,
) -> tuple[str, int, str] | None:
    """``norm(title)|year|registrant_host`` when all three are present."""
    from .dedupe import normalize_dedupe_title
    from .identity import publication_year

    norm = normalize_dedupe_title(title)
    parsed = publication_year(year)
    registrant = (host or registrable_host(url) or "").strip().lower()
    if not norm or parsed is None or not registrant:
        return None
    return norm, parsed, registrant


def grey_token(title: str | None, year: object, host: str) -> str:
    from .dedupe import normalize_dedupe_title

    norm = normalize_dedupe_title(title)
    return f"{norm}|{year}|{host}"


SNAPSHOT_NOTE_MARK = "snapshot:htmlpdf"
LEGACY_HTMLPDF_MARK = "web:htmlpdf"


def is_snapshot_note(note: str | None) -> bool:
    """True for an htmlpdf print, including the older ``web:htmlpdf`` stamp."""
    text = (note or "").lower()
    return SNAPSHOT_NOTE_MARK in text or LEGACY_HTMLPDF_MARK in text
