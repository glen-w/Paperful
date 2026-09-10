"""Propose bibliographic patches on disk; --apply writes through LibraryBackend."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .config import Config
from .library import LibraryBackend
from .lint import Finding
from .resolve import IdentifierCache, WorkMeta, prepare_identifiers, work_by_doi
from .zot import Item

PATCH_FIELDS = ("doi", "title", "date", "publicationTitle")


@dataclass
class Patch:
    itemKey: str
    title: str
    before: dict[str, Any]
    after: dict[str, Any]
    source: str
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def propose_patch(
    client: httpx.Client,
    cfg: Config,
    item: Item,
    findings: list[Finding],
    *,
    overwrite: bool = False,
    cache: IdentifierCache | None = None,
) -> Patch | None:
    prepare_identifiers(
        client,
        item,
        email=cfg.email,
        min_score=cfg.crossref_min_score,
        suspect_score=cfg.doi_suspect_score,
        verify=cfg.verify_doi,
        cache=cache,
    )
    codes = {f.code for f in findings if f.itemKey == item.key}
    after: dict[str, Any] = {}
    source = "prepare"

    if item.doi and (
        item.doi_verified in {"swapped", "ok"} or "swappable_doi" in codes
    ):
        if item.doi != item.library_doi:
            after["doi"] = item.doi
            source = "swap"
        elif not item.library_doi:
            after["doi"] = item.doi
            source = item.doi_source or "pubmed"

    work: WorkMeta | None = None
    if item.doi and item.doi_verified in {"ok", "swapped"}:
        work = work_by_doi(client, item.doi, cfg.email, cache)

    if work:
        if overwrite or not item.publication_title:
            if work.venue:
                after["publicationTitle"] = work.venue
        if overwrite or not item.date:
            if work.year:
                after["date"] = str(work.year)
        if overwrite and work.title:
            after["title"] = work.title
        source = work.source or source

    after = {k: v for k, v in after.items() if k in PATCH_FIELDS and v}
    if not after:
        return None
    before = {
        "doi": item.library_doi,
        "title": item.title,
        "date": item.date,
        "publicationTitle": item.publication_title,
    }
    changed = {k: v for k, v in after.items() if before.get(k) != v}
    if not changed:
        return None
    return Patch(
        itemKey=item.key, title=item.title, before=before, after=changed, source=source
    )


def write_patches(path: Path, patches: list[Patch]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for p in patches:
            fh.write(p.to_json() + "\n")


def apply_patches(
    backend: LibraryBackend, patches: list[Patch]
) -> tuple[int, list[str]]:
    ok = 0
    errors: list[str] = []
    for p in patches:
        try:
            backend.apply_patch(p.itemKey, p.after)
            ok += 1
        except Exception as exc:
            errors.append(f"{p.itemKey}: {type(exc).__name__}: {exc}")
    return ok, errors
