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
