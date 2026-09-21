"""Zotero parent-key remap after an attach miss.

Used when sync or restore changed the item key the manifest still holds.
This path reads ``attacher.zl`` and is Zotero-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .attach import AttachResult
from .resolve import normalize_doi
from .store import STATUS_ATTACHED, Record


def live_parent_key(pipe: Any, rec: Record) -> str | None:
    """Map a stale manifest key to the current library item via DOI/title."""
    zl = getattr(pipe.attacher, "zl", None) if pipe.attacher else None
    if zl is None:
        return None
    if pipe._parent_by_doi is None or pipe._parent_by_title is None:
        by_doi: dict[str, str] = {}
        by_title: dict[str, str] = {}
        for it in zl.items_in_scope(None):
            if it.doi:
                nd = normalize_doi(it.doi)
                if nd and nd not in by_doi:
                    by_doi[nd] = it.key
            title = (it.title or "").strip().lower()
            if title and title not in by_title:
                by_title[title] = it.key
        pipe._parent_by_doi = by_doi
        pipe._parent_by_title = by_title
    nd = normalize_doi(rec.doi)
    if nd and nd in pipe._parent_by_doi:
        return pipe._parent_by_doi[nd]
    title = (rec.title or "").strip().lower()
    if title and title in pipe._parent_by_title:
        return pipe._parent_by_title[title]
    return None


def attach_after_remap(
    pipe: Any, rec: Record, pdf: Path, prior_reason: str
) -> AttachResult:
    """Retry attach when Zotero remapped the parent key (sync / restore)."""
    zl = getattr(pipe.attacher, "zl", None) if pipe.attacher else None
    if zl is None:
        return AttachResult(False, reason=prior_reason, code="parent_missing")
    new_key = live_parent_key(pipe, rec)
    if not new_key or new_key == rec.itemKey:
        return AttachResult(False, reason=prior_reason, code="parent_missing")
    old_key = rec.itemKey
    if pipe._pdf_parents is None:
        pipe._pdf_parents = zl._pdf_parent_keys()
    if new_key in pipe._pdf_parents:
        rec.itemKey = new_key
        pipe.manifest.write(
            Record(
                itemKey=old_key,
                status=STATUS_ATTACHED,
                title=rec.title,
                doi=rec.doi,
                path=rec.path,
                source=rec.source,
                reason=f"remapped to {new_key} (PDF already present)",
                md5=rec.md5,
            )
        )
        return AttachResult(
            True,
            reason=f"remapped {old_key}→{new_key} (already attached)",
            code="unchanged",
        )
    assert pipe.attacher is not None
    res = pipe.attacher.attach(new_key, pdf)
    if res.ok:
        rec.itemKey = new_key
        pipe._pdf_parents.add(new_key)
        pipe.manifest.write(
            Record(
                itemKey=old_key,
                status=STATUS_ATTACHED,
                title=rec.title,
                doi=rec.doi,
                path=rec.path,
                source=rec.source,
                reason=f"remapped to {new_key}",
                md5=rec.md5,
            )
        )
        res.reason = f"remapped {old_key}→{new_key} ({res.reason})"
    return res
