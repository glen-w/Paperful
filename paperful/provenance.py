"""Zotero-visible provenance for an attached PDF.

The manifest ``source`` field stays the source of record. This string is the
note on the Zotero attachment.
"""

from __future__ import annotations

_OA = frozenset(
    {
        "unpaywall",
        "openalex",
        "arxiv",
        "biorxiv",
        "europepmc",
        "semanticscholar",
        "core",
    }
)
_WEB = frozenset({"htmlpdf", "scholar", "browser_agent", "direct"})


def provenance_label(source: str | None, *, playbook: str | None = None) -> str:
    """Stable taxonomy token: ``oa:``, ``campus:``, ``grey:``, ``web:``, ``pirate:``."""
    src = (source or "").strip().lower()
    book = (playbook or "").strip()
    if src in _OA:
        return f"oa:{src}"
    if src == "ezproxy":
        return "campus:ezproxy"
    if src == "scihub":
        return "pirate:scihub"
    if src == "direct" and book:
        return f"grey:{book}"
    if src == "direct":
        return "web:direct"
    if src in _WEB or src:
        return f"web:{src}"
    return "web:unknown"


_SOURCE_NAMES = {
    "unpaywall": "Unpaywall",
    "openalex": "OpenAlex",
    "arxiv": "arXiv",
    "biorxiv": "bioRxiv",
    "europepmc": "Europe PMC",
    "semanticscholar": "Semantic Scholar",
    "core": "CORE",
}


def provenance_sentence(
    source: str | None,
    *,
    playbook: str | None = None,
    pdf_doi_mismatch: bool = False,
) -> str:
    """Plain-language line for the parent. The attachment note stays the token."""
    src = (source or "").strip().lower()
    book = (playbook or "").strip()
    if src in _SOURCE_NAMES:
        line = f"Free copy from {_SOURCE_NAMES[src]}."
    elif src == "ezproxy":
        line = "Downloaded through your library login."
    elif src == "scihub":
        line = "Downloaded from Sci-Hub."
    elif src == "direct" and book:
        line = f"Saved from {book}."
    elif src == "scholar":
        line = "Found via Google Scholar."
    elif src == "htmlpdf":
        line = "Printed from the web page."
    elif src == "browser_agent":
        line = "Found by the browser recovery."
    elif src == "direct":
        line = "Saved from the web page."
    elif src:
        line = f"Saved from {src}."
    else:
        line = "Saved from the web."
    if pdf_doi_mismatch:
        line = f"{line} This PDF's DOI does not match the record."
    return line


def provenance_stamp(
    source: str | None,
    *,
    playbook: str | None = None,
    pdf_doi_mismatch: bool = False,
) -> str:
    """Attachment note. Title stays ``Full Text PDF``."""
    parts = ["paperful", provenance_label(source, playbook=playbook)]
    if pdf_doi_mismatch:
        parts.append("warn:pdf_doi_mismatch")
    return " ".join(parts)
