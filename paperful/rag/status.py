"""What the index holds, and how far it is behind the mirror."""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..ocr import ocrmypdf_available
from ..store import MirrorEntry
from .extract import get_parser
from .index import (
    Index,
    IndexMismatch,
    IndexMissing,
    RagUnavailable,
    index_dir,
    ledger_path,
    load_meta,
)
from .ingest import chunk_params
from .ledger import (
    ACTION_META,
    ACTION_SKIP,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_STUB,
    Ledger,
    pick_pdf,
    plan_item,
)


def _lists_pdf(entry: MirrorEntry) -> bool:
    """True when the record names a PDF attachment in the reference manager."""
    attachments = entry.record.get("attachments")
    if not isinstance(attachments, list):
        return False
    for att in attachments:
        if not isinstance(att, dict):
            continue
        if att.get("linkMode") == "linked_url":
            continue  # a web link, not a file the manager holds
        kind = str(att.get("contentType") or "").lower()
        name = str(att.get("filename") or "").lower()
        if kind == "application/pdf" or name.endswith(".pdf"):
            return True
    return False


def index_status(cfg: Config, entries: list[MirrorEntry] | None = None) -> dict[str, Any]:
    """Facts for ``rag status`` and ``doctor``. Reads only; never embeds.

    With ``entries`` (the mirror in scope) it also reports coverage: how many
    items a fresh ``rag ingest`` would touch, and how many PDFs the reference
    manager holds that the mirror does not.
    """
    meta = load_meta(cfg)
    ledger = Ledger(ledger_path(cfg))
    rows = ledger.rows()
    status: dict[str, Any] = {
        "enabled": cfg.rag_enabled,
        "embed_provider": cfg.rag_embed_provider,
        "embed_model": cfg.rag_embed_model,
        "path": str(index_dir(cfg)),
        "exists": meta is not None,
        "dim": (meta or {}).get("dim"),
        "items": len(rows),
        "items_pdf": sum(1 for r in rows if r.status == STATUS_OK),
        "items_abstract": sum(1 for r in rows if r.status == STATUS_STUB),
        "items_failed": sum(1 for r in rows if r.status == STATUS_FAILED),
        "items_ocr_pending": sum(1 for r in rows if r.ocr_pending),
        "items_with_error": sum(1 for r in rows if r.error),
        "items_multi_pdf": sum(1 for r in rows if r.pdf_count > 1),
        "chunks": sum(r.chunks for r in rows),
        "index_rows": None,
        "problem": "",
    }
    if meta is not None:
        try:
            status["index_rows"] = Index.open(cfg).count()
        except (RagUnavailable, IndexMissing, IndexMismatch) as exc:
            status["problem"] = str(exc)
    if entries is None:
        return status
    params = chunk_params(cfg, get_parser(cfg))
    can_ocr = cfg.rag_ocr == "auto" and ocrmypdf_available()
    stale = 0
    with_pdf = 0
    held_elsewhere = 0
    for entry in entries:
        pdf = pick_pdf(entry)
        if pdf is not None:
            with_pdf += 1
        elif _lists_pdf(entry):
            held_elsewhere += 1
        plan = plan_item(
            entry,
            ledger.get(entry.key),
            pdf=pdf,
            params=params,
            ocr_available=can_ocr,
            abstracts=cfg.rag_abstracts,
        )
        if plan.action not in (ACTION_SKIP, ACTION_META):
            stale += 1
    status["mirror"] = {
        "items": len(entries),
        "with_pdf": with_pdf,
        "pdf_not_in_mirror": held_elsewhere,
        "stale": stale,
    }
    return status
