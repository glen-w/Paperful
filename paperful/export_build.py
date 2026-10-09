"""Build interchange records for ``paperful export`` and agent/MCP export."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .interop.load import record_from_item_json
from .library import LibraryBackend, LibraryError
from .mirror import pdf_for
from .store import Manifest, item_dirname, item_filename, load_json, record_path
from .zot import Item


def build_scope_records(
    cfg: Any,
    backend: LibraryBackend,
    items: list[Item],
    *,
    pdf_dir: Path | None = None,
    include_notes: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Mirror-first records for RIS / BibTeX / EndNote XML."""
    records: list[dict[str, Any]] = []
    copied = 0
    manifest = Manifest(cfg.manifest_path)
    for it in items:
        rec_json = None
        for folder in it.collection_paths or ["_uncollected"]:
            rec_json = load_json(record_path(cfg.out_dir / folder / item_dirname(it)))
            if rec_json:
                break
        rec = record_from_item_json(rec_json or {}, None)
        rec["item_type"] = it.item_type
        rec["title"] = it.title
        rec["doi"] = it.doi
        rec["year"] = it.year
        rec["date"] = it.date or rec.get("date") or (str(it.year) if it.year else "")
        rec["publication_title"] = it.publication_title or rec.get("publication_title")
        rec["url"] = it.url
        rec["pmid"] = it.pmid
        rec["abstract"] = it.abstract or rec.get("abstract")
        rec["collection_paths"] = [p for p in it.collection_paths if p != "_uncollected"]
        rec["item_key"] = it.key
        pdf_list: list[str] = []
        if pdf_dir is not None and it.has_pdf:
            target = pdf_dir / item_filename(it)
            local = pdf_for(cfg.out_dir, it, manifest)
            try:
                if local is not None:
                    exported = shutil.copyfile(local, target)
                else:
                    exported = backend.export_pdf(it, target)
            except LibraryError:
                exported = None
            if exported is not None and Path(exported).is_file():
                pdf_list.append(str(exported))
                copied += 1
        rec["pdfs"] = pdf_list
        if include_notes:
            notes = []
            try:
                kids = backend.children(it.key)
            except LibraryError:
                kids = []
            for ch in kids:
                data = ch.get("data") or {}
                if data.get("itemType") != "note":
                    continue
                html = str(data.get("note") or "")
                if not html:
                    continue
                tags = [
                    t.get("tag")
                    for t in (data.get("tags") or [])
                    if isinstance(t, dict) and t.get("tag")
                ]
                notes.append(
                    {
                        "file": f"{ch.get('key') or 'note'}.html",
                        "html": html,
                        "tag": tags[0] if tags else "paperful-exported",
                    }
                )
            if notes:
                rec["notes"] = notes
        records.append(rec)
    return records, copied
