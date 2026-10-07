"""PDF on disk vs library identity (workbench honesty)."""

from __future__ import annotations

from typing import Any

from ..resolve import normalize_doi
from ..store import STATUS_ATTACHED, STATUS_OK

VERIFICATION_PLAIN: dict[str, str] = {
    "doi_match": "PDF on disk and DOI matches the library",
    "doi_mismatch": "PDF on disk but DOI does not match the library",
    "snapshot": "HTML page snapshot, not a publisher PDF",
    "unverified": "PDF on disk, identity not verified",
    "missing": "No PDF file on disk",
}

REASON_PLAIN: dict[str, str] = {
    "no_file": "Nothing attached in the manifest",
    "htmlpdf": "Saved from HTML conversion",
    "doi_differs": "Embedded DOI differs from the library item",
    "grey": "Grey-literature source",
    "no_doi_in_file": "No DOI found inside the PDF",
}


def verification_plain(state: str | None) -> str:
    if not state:
        return ""
    return VERIFICATION_PLAIN.get(state, state)


def reason_plain(reason: str | None) -> str:
    if not reason:
        return ""
    return REASON_PLAIN.get(reason, reason)


def _doi_key(raw: str | None) -> str | None:
    norm = normalize_doi(raw)
    if norm:
        return norm
    text = (raw or "").strip().lower()
    return text or None


def file_verification(
    record: Any | None,
    *,
    item_doi: str | None = None,
) -> dict[str, str]:
    """Return state, reason, source for a manifest record."""
    if record is None:
        return {"state": "missing", "reason": "no_file", "source": ""}
    status = str(getattr(record, "status", "") or "")
    source = str(getattr(record, "source", "") or "")
    if status not in {STATUS_OK, STATUS_ATTACHED}:
        return {"state": "missing", "reason": "no_file", "source": source}
    if source.strip().lower() == "htmlpdf":
        return {"state": "snapshot", "reason": "htmlpdf", "source": source}
    pdf_doi = _doi_key(getattr(record, "pdf_doi", None))
    lib_doi = _doi_key(item_doi or getattr(record, "doi", None))
    if pdf_doi and lib_doi:
        if pdf_doi == lib_doi:
            return {"state": "doi_match", "reason": "", "source": source}
        return {"state": "doi_mismatch", "reason": "doi_differs", "source": source}
    if source.startswith("grey:") or source.startswith("grey_"):
        return {"state": "unverified", "reason": "grey", "source": source}
    return {"state": "unverified", "reason": "no_doi_in_file", "source": source}
