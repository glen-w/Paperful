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
from .resolve import (
    IdentifierCache,
    WorkMeta,
    date_precision,
    prepare_identifiers,
    strip_title_markup,
    title_similarity,
    work_by_doi,
)
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
    prepared: bool = False,
) -> Patch | None:
    """Build a field whitelist patch from lint findings + work metadata.

    When ``prepared`` is True (caller already ran ``lint_item`` / ``prepare_identifiers``),
    skip a second network prepare pass.
    """
    if not prepared:
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

    pdf_work = _maybe_adopt_pdf_doi(
        client,
        cfg,
        item,
        findings,
        after,
        overwrite=overwrite,
        cache=cache,
    )
    if pdf_work is not None:
        work = pdf_work
        source = "pdf"

    if work:
        if overwrite or not item.publication_title:
            if work.venue:
                after["publicationTitle"] = work.venue
        candidate_date = work.date or (str(work.year) if work.year else None)
        if candidate_date and _should_set_date(item.date, candidate_date, overwrite):
            after["date"] = candidate_date
        if overwrite and work.title:
            after["title"] = work.title
        if source != "pdf":
            source = work.source or source

    cleaned = strip_title_markup(item.title)
    if cleaned and cleaned != item.title.strip():
        # Deterministic HTML cleanup only; never invent a title.
        if "title" not in after:
            after["title"] = cleaned
            if source == "prepare":
                source = "title_html"

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


def _maybe_adopt_pdf_doi(
    client: httpx.Client,
    cfg: Config,
    item: Item,
    findings: list[Finding],
    after: dict[str, Any],
    *,
    overwrite: bool,
    cache: IdentifierCache | None,
) -> WorkMeta | None:
    """Adopt a PDF-text DOI when it verifies against the title."""
    pdf_doi = next(
        (
            f.pdf_doi
            for f in findings
            if f.itemKey == item.key and f.code == "pdf_doi_mismatch" and f.pdf_doi
        ),
        None,
    )
    if not pdf_doi:
        return None

    work = work_by_doi(client, pdf_doi, cfg.email, cache)
    if work is None:
        return None
    score = title_similarity(item.title, work.title)
    if score < cfg.crossref_min_score:
        return None

    lib = (item.library_doi or "").lower()
    pdf_l = pdf_doi.lower()
    if lib == pdf_l:
        return None

    library_ok = item.doi_verified == "ok" and bool(lib)
    if library_ok and not overwrite:
        # Trusted library DOI wins over PDF unless --overwrite.
        return None
    if "doi" in after and after["doi"].lower() == pdf_l:
        return work
    if "doi" in after and not overwrite:
        # Prefer an already-proposed swap over PDF when both differ.
        return None

    after["doi"] = pdf_doi
    return work


def _should_set_date(existing: str | None, candidate: str, overwrite: bool) -> bool:
    exist_p = date_precision(existing)
    cand_p = date_precision(candidate)
    if cand_p == 0:
        return False
    if exist_p == 0:
        return True
    if not overwrite:
        # Fill only when empty/junk; never shorten or replace a set date.
        return False
    # With --overwrite: allow replace when candidate is at least as precise,
    # or when existing is junk-year-parseable but candidate is richer.
    return cand_p >= exist_p


def dedupe_patches(patches: list[Patch]) -> list[Patch]:
    """Keep the last patch per itemKey within a single fix-metadata invocation."""
    by_key: dict[str, Patch] = {}
    for p in patches:
        by_key[p.itemKey] = p
    return list(by_key.values())


def write_patches(path: Path, patches: list[Patch]) -> None:
    """Append patches to the audit JSONL (history log, not a curated queue)."""
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
