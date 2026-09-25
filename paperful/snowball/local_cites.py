"""How many items already in scope list a work in their references.

OpenAlex ``referenced_works`` is inverted once per DOI set and cached under
``state/cites/``. A budget miss keeps whatever was fetched and does not
abort item creation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..resolve import normalize_doi
from .openalex import OpenAlexBudgetExceeded, OpenAlexClient, short_id


@dataclass
class LocalCites:
    """Cited OpenAlex id → local item keys that reference it."""

    by_openalex: dict[str, set[str]] = field(default_factory=dict)
    key_oa: dict[str, str] = field(default_factory=dict)
    doi_to_oa: dict[str, str] = field(default_factory=dict)
    library: bool = False
    client: OpenAlexClient | None = None

    def count(self, *, openalex: str = "", doi: str = "") -> int:
        oa = short_id(openalex)
        if not oa and doi:
            oa = self.doi_to_oa.get(normalize_doi(doi) or "", "")
        if not oa:
            return 0
        keys = set(self.by_openalex.get(oa, ()))
        self_keys = {key for key, owner in self.key_oa.items() if owner == oa}
        return len(keys - self_keys)

    def prepare(self, rows: list[Any], client: OpenAlexClient) -> None:
        """Resolve DOI-only candidates so ``count`` can see their OpenAlex id."""
        missing: list[str] = []
        for row in rows:
            ids = getattr(row, "ids", None) or {}
            if ids.get("openalex"):
                continue
            doi = normalize_doi(str(ids.get("doi") or "")) or ""
            if doi and doi not in self.doi_to_oa and doi not in missing:
                missing.append(doi)
        if not missing:
            return
        try:
            works = client.works_by_dois(missing)
        except OpenAlexBudgetExceeded as exc:
            works = list(exc.partial or [])
        for work in works:
            doi = normalize_doi(str(work.get("doi") or "")) or ""
            oa = short_id(str(work.get("id") or ""))
            if doi and oa:
                self.doi_to_oa[doi] = oa


def load_local_cites(
    backend: Any,
    collection: str,
    *,
    state_dir: Path,
    client: OpenAlexClient,
    library: bool = False,
) -> LocalCites:
    """Build or reload the inverted reference index for this scope."""
    items = _scope_items(backend, collection, library=library)
    pairs: list[tuple[str, str]] = []
    for item in items:
        doi = normalize_doi(getattr(item, "doi", None) or "") or ""
        key = str(getattr(item, "key", "") or "")
        if doi and key:
            pairs.append((key, doi))
    dois = sorted({doi for _, doi in pairs})
    if not dois:
        empty = LocalCites(library=library)
        empty.client = client
        return empty
    cached = _read_cache(state_dir, dois)
    if cached is not None:
        cached.library = library
        cached.client = client
        return cached
    by_key = {key: doi for key, doi in pairs}
    complete = True
    try:
        works = client.works_by_dois(dois)
    except OpenAlexBudgetExceeded as exc:
        works = list(exc.partial or [])
        complete = False
    index = _invert(works, by_key)
    index.library = library
    index.client = client
    if works and complete:
        _write_cache(state_dir, dois, index)
    return index


def _scope_items(backend: Any, collection: str, *, library: bool) -> list[Any]:
    if library:
        try:
            return list(backend.items_in_scope(None))
        except Exception:
            return []
    try:
        root = backend.resolve_collection(collection)
        keys = backend.subtree_keys(root)
        return list(backend.items_in_scope(keys))
    except Exception:
        return []


def _invert(works: list[dict[str, Any]], by_key: dict[str, str]) -> LocalCites:
    """``by_key`` is local item key → DOI. A work citing itself is dropped."""
    doi_to_key = {doi: key for key, doi in by_key.items()}
    index = LocalCites()
    for work in works:
        doi = normalize_doi(str(work.get("doi") or "")) or ""
        oa = short_id(str(work.get("id") or ""))
        key = doi_to_key.get(doi, "")
        if not key or not oa:
            continue
        index.key_oa[key] = oa
        index.doi_to_oa[doi] = oa
        for ref in work.get("referenced_works") or []:
            ref_id = short_id(str(ref))
            if not ref_id or ref_id == oa:
                continue
            index.by_openalex.setdefault(ref_id, set()).add(key)
    return index


def _cache_path(state_dir: Path, dois: list[str]) -> Path:
    digest = hashlib.sha256("\n".join(dois).encode()).hexdigest()[:16]
    return state_dir / "cites" / f"{digest}.json"


def _read_cache(state_dir: Path, dois: list[str]) -> LocalCites | None:
    path = _cache_path(state_dir, dois)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if list(raw.get("dois") or []) != dois:
        return None
    index = LocalCites()
    for oa, keys in (raw.get("by_openalex") or {}).items():
        index.by_openalex[str(oa)] = {str(key) for key in keys}
    index.key_oa = {str(k): str(v) for k, v in (raw.get("key_oa") or {}).items()}
    index.doi_to_oa = {str(k): str(v) for k, v in (raw.get("doi_to_oa") or {}).items()}
    return index


def _write_cache(state_dir: Path, dois: list[str], index: LocalCites) -> None:
    path = _cache_path(state_dir, dois)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dois": dois,
        "by_openalex": {oa: sorted(keys) for oa, keys in index.by_openalex.items()},
        "key_oa": index.key_oa,
        "doi_to_oa": index.doi_to_oa,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
