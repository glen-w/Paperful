"""Read-only library lint: identifiers vs APIs vs PDF text on disk."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import Config
from .library import LibraryBackend
from .pdfid import doi_from_pdf
from .resolve import IdentifierCache, prepare_identifiers
from .store import Manifest
from .zot import Item

_SCHOLARLY = frozenset(
    {
        "journalArticle",
        "conferencePaper",
        "preprint",
        "report",
        "thesis",
        "book",
        "bookSection",
        "manuscript",
    }
)


@dataclass
class Finding:
    itemKey: str
    code: str
    title: str
    detail: str
    library_doi: str | None = None
    doi: str | None = None
    pdf_doi: str | None = None


def resolve_pdf_path(cfg: Config, item: Item, manifest: Manifest | None) -> Path | None:
    if item.pdf_path:
        p = Path(item.pdf_path)
        if p.is_file():
            return p
    rec = manifest.get(item.key) if manifest else None
    if rec and rec.path:
        p = Path(rec.path)
        if p.is_file():
            return p
    return None


def lint_item(
    client: httpx.Client,
    cfg: Config,
    item: Item,
    *,
    backend: LibraryBackend | None = None,
    manifest: Manifest | None = None,
    cache: IdentifierCache | None = None,
) -> list[Finding]:
    notes = prepare_identifiers(
        client,
        item,
        email=cfg.email,
        min_score=cfg.crossref_min_score,
        suspect_score=cfg.doi_suspect_score,
        verify=cfg.verify_doi,
        cache=cache,
    )
    findings: list[Finding] = []
    scholarly = item.item_type in _SCHOLARLY

    def add(code: str, detail: str, pdf_doi: str | None = None) -> None:
        findings.append(
            Finding(
                itemKey=item.key,
                code=code,
                title=item.title,
                detail=detail,
                library_doi=item.library_doi,
                doi=item.doi,
                pdf_doi=pdf_doi,
            )
        )

    if item.doi_verified == "swapped":
        add(
            "swappable_doi",
            next(
                (n for n in notes if n.startswith("swap:")),
                "library DOI disagrees with title match",
            ),
        )
    elif item.doi_verified == "suspect":
        add(
            "suspect_doi",
            next(
                (n for n in notes if n.startswith("verify:")),
                "library DOI title mismatch",
            ),
        )
    elif scholarly and item.doi_verified == "missing" and not item.doi:
        add("missing_doi", "no DOI after prepare")
    if not item.doi and not item.arxiv_id and not item.pmid and not item.url:
        add("no_identifier", "no DOI, arXiv id, PMID or URL")
    if item.pmid and not item.doi and "pubmed:no-doi" in notes:
        add("pmid_no_doi", f"PMID {item.pmid} did not convert")

    pdf_path = resolve_pdf_path(cfg, item, manifest)
    if pdf_path is None and item.has_pdf and backend is not None:
        dest = cfg.pdf_cache_dir / f"{item.key}.pdf"
        pdf_path = backend.export_pdf(item, dest)
        if pdf_path:
            item.pdf_path = str(pdf_path)
    if pdf_path and pdf_path.is_file():
        pdf_doi = doi_from_pdf(pdf_path)
        if pdf_doi:
            lib = (item.library_doi or "").lower()
            working = (item.doi or "").lower()
            if pdf_doi != lib and pdf_doi != working:
                add("pdf_doi_mismatch", f"PDF DOI {pdf_doi}", pdf_doi=pdf_doi)
    return findings


def lint_items(
    client: httpx.Client,
    cfg: Config,
    items: list[Item],
    *,
    backend: LibraryBackend | None = None,
    manifest: Manifest | None = None,
) -> list[Finding]:
    cache = IdentifierCache()
    out: list[Finding] = []
    for item in items:
        out.extend(
            lint_item(
                client, cfg, item, backend=backend, manifest=manifest, cache=cache
            )
        )
    return out
