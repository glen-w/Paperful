"""DOI then title+year library fingerprints. Shared by snowball, ingest, refs gap, inbox."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .dedupe import normalize_dedupe_title
from .resolve import normalize_doi

PREPRINT_DOI_LINE = re.compile(r"(?im)^Preprint DOI:\s*(\S+)")

Lookup = Callable[[str | None, str | None], Any]


def publication_year(value: object) -> int | None:
    """Calendar year, or None when the field is blank or not a whole number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class LookupHit:
    item_key: str
    kind: str  # doi | title_year


class LibraryFingerprint:
    """Indexed DOI and title+year keys for items already in the library."""

    def __init__(
        self,
        by_doi: dict[str, str],
        by_title_year: dict[tuple[str, int], str],
        *,
        doi_of: dict[str, str] | None = None,
    ) -> None:
        self.by_doi = by_doi
        self.by_title_year = by_title_year
        self.doi_of = doi_of or {}

    @classmethod
    def from_items(
        cls,
        items: Iterable[Any],
        *,
        scope: str = "library",
        collection: str = "",
    ) -> LibraryFingerprint:
        if scope == "collection":
            want = collection.strip()
            items = [
                item
                for item in items
                if want and want in (getattr(item, "collection_paths", None) or [])
            ]
        by_doi: dict[str, str] = {}
        by_title_year: dict[tuple[str, int], str] = {}
        doi_of: dict[str, str] = {}
        for item in items:
            key = str(getattr(item, "key", "") or "")
            if not key:
                continue
            doi = normalize_doi(getattr(item, "doi", None))
            if doi:
                by_doi.setdefault(doi, key)
                doi_of.setdefault(key, doi)
            arxiv_id = getattr(item, "arxiv_id", None)
            if arxiv_id:
                arxiv_doi = normalize_doi(f"10.48550/arxiv.{arxiv_id}")
                if arxiv_doi:
                    by_doi.setdefault(arxiv_doi, key)
            extra = getattr(item, "extra", "") or ""
            preprint_line = PREPRINT_DOI_LINE.search(extra)
            if preprint_line:
                preprint = normalize_doi(preprint_line.group(1))
                if preprint:
                    by_doi.setdefault(preprint, key)
            title = normalize_dedupe_title(getattr(item, "title", None))
            year = publication_year(getattr(item, "year", None))
            if title and year is not None:
                by_title_year.setdefault((title, year), key)
        return cls(by_doi, by_title_year, doi_of=doi_of)

    def find(
        self,
        doi: str | None = None,
        title: str | None = None,
        year: object = None,
    ) -> LookupHit | None:
        found = normalize_doi(doi) if doi else None
        if found and found in self.by_doi:
            return LookupHit(self.by_doi[found], "doi")
        key = normalize_dedupe_title(title)
        parsed = publication_year(year)
        if key and parsed is not None and (key, parsed) in self.by_title_year:
            return LookupHit(self.by_title_year[(key, parsed)], "title_year")
        return None


def library_lookup(backend: Any, *, scope: str, collection: str) -> Lookup:
    """Callable matching snowball's indexed lookup, with Zotero fallback."""
    items = None
    if hasattr(backend, "items_in_scope"):
        try:
            items = list(backend.items_in_scope(None))
        except Exception:
            items = None
    if items is not None:
        fp = LibraryFingerprint.from_items(
            items, scope=scope, collection=collection
        )

        def indexed(
            doi: str | None, title: str | None, year: int | None = None
        ) -> Any:
            hit = fp.find(doi, title, year)
            if hit is None:
                return None
            return hit.item_key, hit.kind

        return indexed

    zl = getattr(backend, "zl", None)

    def lookup(
        doi: str | None, title: str | None, year: int | None = None
    ) -> str | None:
        del year
        if zl is None:
            return None
        return zl.find_top_item_key(doi=doi, title=title)

    return lookup


def merge_tags(*groups: Iterable[str] | None) -> list[str]:
    """Stable unique tags, skipping blanks."""
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        if not group:
            continue
        for raw in group:
            tag = str(raw or "").strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            out.append(tag)
    return out


def seed_slug(value: str | Path | None, *, fallback: str = "seed") -> str:
    """Filesystem-safe slug for ``from-<seed>`` provenance tags."""
    if isinstance(value, Path):
        text = value.stem
    else:
        text = str(value or "")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.strip()).strip("-").lower()
    return (slug or fallback)[:40]


def from_seed_tag(seed: dict[str, Any] | str | Path | None) -> str | None:
    """``from-<slug>`` from a snowball seed dict, DOI/keyword string, or file path."""
    if seed is None:
        return None
    if isinstance(seed, dict):
        raw = seed.get("value") or seed.get("type") or ""
    else:
        raw = seed
    slug = seed_slug(raw, fallback="")
    return f"from-{slug}" if slug else None


def inbox_dir_tag(inbox_dir: str | Path | None) -> str | None:
    """``inbox:<dirname>`` when a drop folder is configured."""
    if inbox_dir is None or str(inbox_dir).strip() == "":
        return None
    name = Path(str(inbox_dir)).expanduser().name.strip()
    slug = seed_slug(name, fallback="")
    return f"inbox:{slug}" if slug else None
