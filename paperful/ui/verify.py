"""PDF on disk vs library identity (workbench honesty)."""

from __future__ import annotations

from typing import Any

from ..resolve import normalize_doi
from ..store import STATUS_ATTACHED, STATUS_OK


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
