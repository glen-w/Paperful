"""Collection-scoped authors/orgs frequency report and field author-pack seed.

Harvest counts creators once per item. Corporate Zotero creators (single
``name`` field) go in the orgs table. ``--apply`` writes
``state/reports/<slug>-authors.json`` and merges top people into a proposed
field author pack under ``state/author-packs/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .acronyms import file_slug
from .config import Config
from .snowball.authors import (
    AuthorPack,
    PackAuthor,
    load_pack_file,
    name_fingerprint,
    pack_path,
    pack_slug,
    write_pack,
)
from .zot import Item

SCHEMA = "paperful.authors_report.v1"


@dataclass(frozen=True)
class FreqRow:
    name: str
    key: str  # fingerprint for people; casefold name for orgs
    count: int
    kind: str  # author | org


@dataclass
class AuthorsReport:
    authors: list[FreqRow] = field(default_factory=list)
    orgs: list[FreqRow] = field(default_factory=list)


def _prefer_display(surname: str, first_author: str | None) -> str:
    display = surname.strip()
    if not display:
        return ""
    if (
        first_author
        and " " in first_author.strip()
        and first_author.strip().casefold().endswith(display.casefold())
    ):
        return first_author.strip()
    return display


def harvest(items: list[Item], *, min_count: int = 2) -> AuthorsReport:
    """Count each person/org once per item. Filter by ``min_count``."""
    if min_count < 1:
        raise ValueError("min_count must be at least 1")
    author_counts: dict[str, int] = {}
    author_names: dict[str, str] = {}
    org_counts: dict[str, int] = {}
    org_names: dict[str, str] = {}
    for item in items:
        corporate = {c.strip() for c in (item.corporate_creators or []) if c.strip()}
        corporate_fold = {c.casefold() for c in corporate}
        seen_authors: set[str] = set()
        seen_orgs: set[str] = set()
        for org in corporate:
            key = org.casefold()
            if key in seen_orgs:
                continue
            seen_orgs.add(key)
            org_counts[key] = org_counts.get(key, 0) + 1
            if key not in org_names or len(org) > len(org_names[key]):
                org_names[key] = org
        surnames = [s for s in (item.creator_surnames or []) if s]
        if not surnames and item.first_author:
            surnames = [item.first_author.strip()]
        for i, raw in enumerate(surnames):
            display = raw.strip()
            if not display:
                continue
            if display.casefold() in corporate_fold:
                continue
            if i == 0:
                display = _prefer_display(display, item.first_author)
            fp = name_fingerprint(display)
            if not fp or fp in seen_authors:
                continue
            seen_authors.add(fp)
            author_counts[fp] = author_counts.get(fp, 0) + 1
            prev = author_names.get(fp, "")
            if len(display) > len(prev):
                author_names[fp] = display
    authors = [
        FreqRow(name=author_names[fp], key=fp, count=count, kind="author")
        for fp, count in author_counts.items()
        if count >= min_count
    ]
    orgs = [
        FreqRow(name=org_names[key], key=key, count=count, kind="org")
        for key, count in org_counts.items()
        if count >= min_count
    ]
    authors.sort(key=lambda row: (-row.count, row.name.casefold()))
    orgs.sort(key=lambda row: (-row.count, row.name.casefold()))
    return AuthorsReport(authors=authors, orgs=orgs)


def report_path(cfg: Config, slug: str) -> Path:
    return cfg.reports_dir / f"{slug}-authors.json"


def write_report(
    cfg: Config,
    slug: str,
    *,
    scope: str,
    report: AuthorsReport,
    min_count: int,
    n_items: int,
) -> Path:
    path = report_path(cfg, slug)
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "scope": scope,
        "min_count": min_count,
        "items": n_items,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "authors": [
            {"name": row.name, "fingerprint": row.key, "frequency": row.count}
            for row in report.authors
        ],
        "orgs": [
            {"name": row.name, "key": row.key, "frequency": row.count}
            for row in report.orgs
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def seed_proposed_pack(
    cfg: Config,
    *,
    collection: str,
    authors: list[FreqRow],
    max_authors: int = 15,
) -> Path | None:
    """Merge top people into a proposed field author pack. Orgs are not seeded."""
    if max_authors < 1:
        raise ValueError("max_authors must be at least 1")
    top = [row for row in authors if row.kind == "author"][:max_authors]
    if not top:
        return None
    slug = pack_slug(collection)
    dest = pack_path(cfg, slug, promoted=False)
    pack = load_pack_file(dest) or AuthorPack(
        name=slug,
        collection=collection,
        status="proposed",
        authors=[],
    )
    pack.collection = collection or pack.collection
    pack.status = "proposed"
    by_fp = {
        (row.fingerprint or name_fingerprint(row.name)): row for row in pack.authors
    }
    for row in top:
        fp = row.key or name_fingerprint(row.name)
        existing = by_fp.get(fp)
        if existing is not None:
            existing.frequency = row.count
            if len(row.name) > len(existing.name or ""):
                existing.name = row.name
            if not existing.fingerprint:
                existing.fingerprint = fp
            continue
        author = PackAuthor(
            name=row.name,
            fingerprint=fp,
            frequency=row.count,
            source="corpus",
        )
        pack.authors.append(author)
        by_fp[fp] = author
    return write_pack(dest, pack)


def scope_slug(collections: list[str], *, library: bool) -> str:
    return file_slug(collections, library=library)
