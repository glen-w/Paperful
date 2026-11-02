"""Content-addressed watch cache: same identity, changed metadata vs new work."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..fsio import atomic_write_json
from .candidate import Candidate

SCHEMA = "paperful.snowball.watch.responses.v1"
DRIFT_NEW = "new"
DRIFT_UNCHANGED = "unchanged"
DRIFT_METADATA = "metadata_changed"
DRIFT_REASSIGNED = "reassigned_id"
DRIFT_CLASSES = (DRIFT_NEW, DRIFT_UNCHANGED, DRIFT_METADATA, DRIFT_REASSIGNED)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def candidate_payload(row: Candidate) -> dict[str, Any]:
    return {
        "identity": row.identity,
        "openalex": str(row.ids.get("openalex") or ""),
        "doi": str(row.ids.get("doi") or ""),
        "title": str(row.biblio.get("title") or ""),
        "year": row.biblio.get("year"),
        "type": str(row.biblio.get("type") or ""),
        "cited_by_count": row.biblio.get("cited_by_count"),
    }


def candidate_hash(row: Candidate) -> str:
    blob = json.dumps(candidate_payload(row), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cache_path(watch_folder: Path) -> Path:
    return watch_folder / "responses.json"


def load_cache(watch_folder: Path) -> dict[str, Any]:
    path = cache_path(watch_folder)
    if not path.is_file():
        return {"schema": SCHEMA, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": SCHEMA, "entries": {}}
    if not isinstance(data, dict):
        return {"schema": SCHEMA, "entries": {}}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    return {"schema": SCHEMA, "entries": entries}


def save_cache(watch_folder: Path, cache: dict[str, Any]) -> Path:
    watch_folder.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": SCHEMA,
        "entries": cache.get("entries") if isinstance(cache.get("entries"), dict) else {},
    }
    path = cache_path(watch_folder)
    atomic_write_json(path, body)
    return path


def classify_row(entry: dict[str, Any] | None, row: Candidate, digest: str) -> str:
    if not entry:
        return DRIFT_NEW
    old_hash = str(entry.get("sha256") or "")
    if old_hash == digest:
        return DRIFT_UNCHANGED
    old_oa = str(entry.get("openalex_id") or "")
    new_oa = str(row.ids.get("openalex") or "")
    if old_oa and new_oa and old_oa != new_oa:
        return DRIFT_REASSIGNED
    return DRIFT_METADATA


def record_row(cache: dict[str, Any], row: Candidate, digest: str, drift: str) -> None:
    entries = cache.setdefault("entries", {})
    identity = row.identity
    if not identity:
        return
    entries[identity] = {
        "sha256": digest,
        "openalex_id": str(row.ids.get("openalex") or ""),
        "title": str(row.biblio.get("title") or ""),
        "year": row.biblio.get("year"),
        "drift": drift,
        "updated_at": _now(),
    }


def classify_drift(watch_folder: Path, rows: list[Candidate]) -> dict[str, int]:
    """Update the watch response cache. Returns drift class counts."""
    cache = load_cache(watch_folder)
    counts = {name: 0 for name in DRIFT_CLASSES}
    entries = cache.get("entries") if isinstance(cache.get("entries"), dict) else {}
    for row in rows:
        if not row.identity:
            continue
        digest = candidate_hash(row)
        previous = entries.get(row.identity) if isinstance(entries, dict) else None
        drift = classify_row(previous if isinstance(previous, dict) else None, row, digest)
        counts[drift] = counts.get(drift, 0) + 1
        record_row(cache, row, digest, drift)
        entries = cache.get("entries") if isinstance(cache.get("entries"), dict) else entries
    save_cache(watch_folder, cache)
    return counts
