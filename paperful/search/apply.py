"""Create metadata parents from a search run. PDFs stay ``paperful run``."""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..identity import LibraryFingerprint
from ..interop.load import parent_payload
from ..library import LibraryBackend, LibraryError, get_backend
from ..lint import normalize_saved_title


def mark_exists(cfg: Config, candidates: list[dict[str, Any]], backend: Any | None = None) -> None:
    items: list[Any] = []
    lib = backend
    if lib is None:
        try:
            lib = get_backend(cfg)
        except Exception:
            lib = None
    if lib is not None and hasattr(lib, "items_in_scope"):
        try:
            items = list(lib.items_in_scope(None))
        except Exception:
            items = []
    if not items:
        return
    fp = LibraryFingerprint.from_items(items, scope="library", collection="")
    for row in candidates:
        if row.get("status") == "blocked":
            continue
        hit = fp.find(
            row.get("doi") or None,
            row.get("title"),
            row.get("year"),
            url=row.get("url"),
        )
        if hit is not None:
            row["status"] = "exists"
            row["item_key"] = hit.item_key


def apply_candidates(
    cfg: Config,
    candidates: list[dict[str, Any]],
    collection: str,
    *,
    backend: LibraryBackend | None = None,
    urls: list[str] | None = None,
) -> dict[str, Any]:
    """Create ``new`` rows in ``collection``. Dry-run when backend is a stub that records."""
    wanted = {u.strip() for u in (urls or []) if str(u).strip()}
    rows = [
        row
        for row in candidates
        if row.get("status") == "new"
        and (not wanted or str(row.get("url") or "") in wanted)
    ]
    lib = backend if backend is not None else get_backend(cfg)
    if not lib.supports_write():
        raise LibraryError("Library write API is off. Search apply needs Zotero 10+ (or a writing manager).")
    collection_key = lib.ensure_collection_path(collection)
    created = 0
    failed = 0
    errors: list[str] = []
    keys: list[str] = []
    for row in rows:
        title = normalize_saved_title(str(row.get("title") or row.get("url") or "Untitled"))
        playbook = str(row.get("playbook") or "").strip()
        stamp = f"grey:{playbook}" if playbook else "web:searxng"
        extra = f"paperful {stamp}"
        if row.get("doi"):
            extra += f"\nDOI: {row['doi']}"
        year = row.get("year")
        record = {
            "item_type": "report",
            "title": title,
            "date": str(year) if year else "",
            "doi": row.get("doi") or "",
            "url": row.get("url") or "",
            "extra": extra,
            "tags": [{"tag": "paperful-search"}, {"tag": stamp}],
        }
        payload = parent_payload(record, [collection_key])
        try:
            key = lib.create_parent(payload)
        except LibraryError as exc:
            failed += 1
            errors.append(str(exc))
            row["status"] = "error"
            continue
        created += 1
        row["status"] = "created"
        row["item_key"] = key
        keys.append(key)
    return {
        "created": created,
        "failed": failed,
        "skipped": len(candidates) - len(rows),
        "keys": keys,
        "errors": errors,
    }
