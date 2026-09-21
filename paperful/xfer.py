"""Import interchange records into the current library adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .interop.load import parent_payload
from .library import LibraryBackend


def apply_import(
    records: list[dict[str, Any]], backend: LibraryBackend, *, dry_run: bool = False
) -> dict[str, int]:
    """Create parents, attach local PDFs, add notes. EndNote stages a bundle."""
    done = {"create": 0, "attach": 0, "notes": 0, "skipped_pdf": 0}
    if dry_run:
        done["create"] = len(records)
        done["attach"] = sum(1 for r in records if r.get("pdfs"))
        done["notes"] = sum(len(r.get("notes") or []) for r in records)
        return done
    for rec in records:
        paths = [
            p
            for p in (rec.get("collection_paths") or [])
            if isinstance(p, str) and p and p != "_uncollected"
        ]
        keys = [backend.ensure_collection_path(p) for p in paths]
        payload = parent_payload(rec, keys)
        new_key = backend.create_parent(payload)
        done["create"] += 1
        for pdf in rec.get("pdfs") or []:
            path = Path(str(pdf).replace("file://localhost", "").replace("file://", ""))
            if not path.is_file():
                done["skipped_pdf"] += 1
                continue
            backend.attach(new_key, path, rec.get("title"))
            done["attach"] += 1
        for note in rec.get("notes") or []:
            if not isinstance(note, dict):
                continue
            html = note.get("html")
            if not html:
                continue
            tag = str(note.get("tag") or "paperful-imported")
            backend.create_or_update_note(new_key, html, tag)
            done["notes"] += 1
    return done
