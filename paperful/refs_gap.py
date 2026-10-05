"""Cited-in-PDF works that are not in the library fingerprint."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dedupe import normalize_dedupe_title, scope_slug
from .identity import LibraryFingerprint
from .pdfid import text_from_pdf
from .resolve import DOI_RE, normalize_doi
from .snowball.bibliography import parse_bibliography_entries
from .snowball.expand import publication_year
from .zot import Item

SCHEMA = "paperful.refs_gap.pack.v1"
BIBLIO_PAGES = None  # whole PDF; bibliography is often at the end


@dataclass
class CiteRef:
    doi: str = ""
    title: str = ""
    year: int | None = None
    citing_keys: list[str] = field(default_factory=list)
    already_exists: bool = False
    exists_key: str = ""
    exists_kind: str = ""
    oa_hint: str = ""
    suggested_action: str = "skip"
    finding: str = ""


@dataclass
class ScanFinding:
    item_key: str
    path: str = ""
    finding: str = ""  # needs_ocr | no_pdf | no_refs | ok


def scan_pdf_citations(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Parse bibliography entries from a local PDF. Finding when text is thin."""
    if not path.is_file():
        return [], "no_pdf"
    text = text_from_pdf(path, max_pages=BIBLIO_PAGES)
    alnum = sum(1 for ch in text if ch.isalnum())
    if alnum < 40:
        return [], "needs_ocr"
    entries = parse_bibliography_entries(text)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for entry in entries:
        doi = normalize_doi(entry.get("doi")) or ""
        title = str(entry.get("title") or "").strip()
        year = publication_year(entry.get("year"))
        ident = doi or f"{normalize_dedupe_title(title)}|{year}"
        if not ident or ident in seen:
            continue
        seen.add(ident)
        out.append({"doi": doi, "title": title, "year": year, "raw": entry.get("raw")})
    for match in DOI_RE.finditer(text):
        doi = normalize_doi(match.group(1))
        if not doi or doi in seen:
            continue
        seen.add(doi)
        out.append({"doi": doi, "title": "", "year": None, "raw": ""})
    if not out:
        return [], "no_refs"
    return out, "ok"


def aggregate_citations(
    sources: list[tuple[str, list[dict[str, Any]]]],
    fingerprint: LibraryFingerprint,
) -> list[CiteRef]:
    """Merge cites by DOI or title+year; mark library hits."""
    buckets: dict[str, CiteRef] = {}
    order: list[str] = []
    for citing_key, entries in sources:
        for entry in entries:
            doi = normalize_doi(entry.get("doi")) or ""
            title = str(entry.get("title") or "").strip()
            year = publication_year(entry.get("year"))
            ident = doi or f"{normalize_dedupe_title(title)}|{year}"
            if not ident or ident == "|None":
                continue
            row = buckets.get(ident)
            if row is None:
                row = CiteRef(doi=doi, title=title, year=year)
                buckets[ident] = row
                order.append(ident)
            elif not row.doi and doi:
                row.doi = doi
            if citing_key not in row.citing_keys:
                row.citing_keys.append(citing_key)
    refs: list[CiteRef] = []
    for ident in order:
        row = buckets[ident]
        hit = fingerprint.find(row.doi or None, row.title or None, row.year)
        if hit is not None:
            row.already_exists = True
            row.exists_key = hit.item_key
            row.exists_kind = hit.kind
            row.suggested_action = "skip"
        elif row.doi:
            row.suggested_action = "ingest-dois"
        elif row.title:
            row.suggested_action = "snowball doi"
        else:
            row.suggested_action = "skip"
        refs.append(row)
    return refs


def write_pack(
    state_dir: Path,
    scope: str,
    refs: list[CiteRef],
    findings: list[ScanFinding],
    *,
    stamp: str | None = None,
) -> Path:
    stamp = stamp or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = state_dir / "refs-gaps" / f"{stamp}-{scope_slug(scope)}"
    folder.mkdir(parents=True, exist_ok=True)
    missing = [r for r in refs if not r.already_exists]
    payload = {
        "schema": SCHEMA,
        "scope": scope,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "counts": {
            "cited": len(refs),
            "already_exists": sum(1 for r in refs if r.already_exists),
            "missing": len(missing),
            "ingest_dois": sum(1 for r in missing if r.suggested_action == "ingest-dois"),
            "needs_ocr": sum(1 for f in findings if f.finding == "needs_ocr"),
            "no_pdf": sum(1 for f in findings if f.finding == "no_pdf"),
        },
        "findings": [asdict(f) for f in findings],
        "rows": [
            {
                **asdict(r),
                "cited_by_count_in_scope": len(r.citing_keys),
            }
            for r in refs
        ],
    }
    json_path = folder / "pack.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (folder / "dois.txt").write_text(
        "".join(
            f"{r.doi}\n"
            for r in refs
            if r.doi and not r.already_exists and r.suggested_action == "ingest-dois"
        ),
        encoding="utf-8",
    )
    (folder / "pack.md").write_text(_markdown(scope, payload["counts"], refs), encoding="utf-8")
    return folder


def scan_items(
    items: list[Item],
    pdf_for_item: Any,
    fingerprint: LibraryFingerprint,
) -> tuple[list[CiteRef], list[ScanFinding]]:
    sources: list[tuple[str, list[dict[str, Any]]]] = []
    findings: list[ScanFinding] = []
    for item in items:
        path = pdf_for_item(item)
        if path is None:
            findings.append(ScanFinding(item.key, finding="no_pdf"))
            continue
        entries, finding = scan_pdf_citations(Path(path))
        findings.append(ScanFinding(item.key, path=str(path), finding=finding))
        if finding == "ok":
            sources.append((item.key, entries))
    return aggregate_citations(sources, fingerprint), findings


def _markdown(scope: str, counts: dict[str, Any], refs: list[CiteRef]) -> str:
    lines = [
        f"# Bibliography gap — {scope}",
        "",
        f"Cited {counts.get('cited', 0)}; missing {counts.get('missing', 0)}; "
        f"already in library {counts.get('already_exists', 0)}.",
        "",
        "| Cited by | DOI | Title | Year | In library | Action |",
        "| ---: | --- | --- | ---: | --- | --- |",
    ]
    ordered = sorted(refs, key=lambda r: (-len(r.citing_keys), r.doi or r.title))
    for row in ordered:
        title = (row.title or "").replace("|", "/")
        doi = row.doi or ""
        lib = row.exists_key if row.already_exists else ""
        lines.append(
            f"| {len(row.citing_keys)} | {doi} | {title} | {row.year or ''} | {lib} | {row.suggested_action} |"
        )
    lines.append("")
    return "\n".join(lines)
