"""File existing library keys into a collection. Dry-run unless ``--apply``."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .library import LibraryBackend, LibraryError

SCHEMA = "paperful.collections_add.v1"


@dataclass
class AddRow:
    key: str
    status: str  # add | added | already-in | not-found | error
    title: str = ""
    detail: str = ""


@dataclass
class AddBatch:
    rows: list[AddRow] = field(default_factory=list)
    to_add: int = 0
    added: int = 0
    already_in: int = 0
    not_found: int = 0
    failed: int = 0
    applied: bool = False

    def counts(self) -> dict[str, int]:
        return {
            "rows": len(self.rows),
            "add": self.to_add,
            "added": self.added,
            "already_in": self.already_in,
            "not_found": self.not_found,
            "failed": self.failed,
        }


def parse_key_lines(text: str) -> list[str]:
    """One item key per line. ``#`` comments. Blank lines skipped. Deduped, order kept."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def keys_from_file(path: Path) -> list[str]:
    return parse_key_lines(path.read_text(encoding="utf-8"))


def classify_rows(
    keys: Iterable[str],
    backend: LibraryBackend,
    *,
    collection_key: str,
    collection_path: str,
) -> AddBatch:
    batch = AddBatch()
    for key in keys:
        status = _membership(backend, key, collection_key, collection_path)
        title = ""
        item = backend.get_item(key) if status != "not-found" else None
        if item is not None:
            title = item.title or ""
        row = AddRow(key=key, status=status, title=title)
        batch.rows.append(row)
        if status == "add":
            batch.to_add += 1
        elif status == "already-in":
            batch.already_in += 1
        else:
            batch.not_found += 1
    return batch


def apply_adds(
    backend: LibraryBackend,
    batch: AddBatch,
    collection_key: str,
) -> AddBatch:
    for row in batch.rows:
        if row.status != "add":
            continue
        try:
            backend.add_to_collection(row.key, collection_key)
        except LibraryError as exc:
            row.status = "error"
            row.detail = str(exc)
            batch.failed += 1
            continue
        row.status = "added"
        batch.added += 1
    batch.applied = True
    return batch


def write_summary(state_dir: Path, collection: str, batch: AddBatch) -> Path:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = state_dir / "collections-add" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "collection": collection,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "applied": batch.applied,
        "counts": batch.counts(),
        "rows": [asdict(r) for r in batch.rows],
    }
    path = folder / "summary.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return folder


def _membership(
    backend: LibraryBackend,
    item_key: str,
    collection_key: str,
    collection_path: str,
) -> str:
    """Return ``add``, ``already-in``, or ``not-found``."""
    raw = backend.raw_item(item_key)
    item = backend.get_item(item_key)
    if raw is None and item is None:
        return "not-found"
    if isinstance(raw, dict):
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        cols = data.get("collections") if isinstance(data, dict) else None
        if isinstance(cols, list) and cols:
            keys = {str(c) for c in cols}
            return "already-in" if collection_key in keys else "add"
    if item is not None and collection_path in (item.collection_paths or []):
        return "already-in"
    if item is None and raw is None:
        return "not-found"
    return "add"
