"""Load RIS / BibTeX / EndNote XML into interchange records, and write them back out."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .bibtex import parse_bibtex, records_to_bibtex
from .endnote_xml import parse_endnote_xml, records_to_endnote_xml
from .ris import parse_ris, records_to_ris


def detect_format(path: Path, text: str | None = None) -> str:
    suffix = path.suffix.lower()
    if suffix in {".ris"}:
        return "ris"
    if suffix in {".bib", ".bibtex"}:
        return "bibtex"
    if suffix in {".xml"}:
        return "endnote-xml"
    sample = text if text is not None else path.read_text(encoding="utf-8", errors="replace")[:2000]
    head = sample.lstrip("\ufeff")
    if head.lstrip().startswith("@") or "\n@" in head:
        return "bibtex"
    if "<xml" in head[:200].lower() or "<records" in head[:400].lower():
        return "endnote-xml"
    if "TY  -" in head or "TY  - " in head:
        return "ris"
    raise ValueError(
        f"Cannot detect format of {path.name}. Use --format ris, bibtex, or endnote-xml."
    )


def load_records(path: Path, fmt: str | None = None) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    kind = (fmt or detect_format(path, text)).strip().lower().replace("_", "-")
    if kind == "ris":
        return parse_ris(text)
    if kind in {"bibtex", "bib", "biblatex"}:
        return parse_bibtex(text)
    if kind in {"endnote-xml", "endnote", "xml"}:
        return parse_endnote_xml(text, xml_path=path)
    raise ValueError(f"Unknown format {fmt!r}. Use ris, bibtex, or endnote-xml.")


def dump_records(records: list[dict[str, Any]], fmt: str) -> str:
    kind = fmt.strip().lower().replace("_", "-")
    if kind == "ris":
        return records_to_ris(records)
    if kind in {"bibtex", "bib", "biblatex"}:
        return records_to_bibtex(records)
    if kind in {"endnote-xml", "endnote", "xml"}:
        return records_to_endnote_xml(records)
    raise ValueError(f"Unknown format {fmt!r}. Use ris, bibtex, or endnote-xml.")


def record_from_item_json(data: dict[str, Any], item_dir: Path | None = None) -> dict[str, Any]:
    """``paperful.item.v1`` (or a restore folder) → interchange record."""
    pdfs: list[str] = []
    if item_dir is not None:
        pdfs = [str(p) for p in sorted(item_dir.glob("*.pdf")) if p.is_file()]
    notes: list[dict[str, Any]] = []
    for note in data.get("notes") or []:
        if not isinstance(note, dict):
            continue
        row = dict(note)
        fname = str(note.get("file") or "")
        if item_dir is not None and fname:
            html_path = item_dir / "notes" / fname
            if html_path.is_file():
                row["html"] = html_path.read_text(encoding="utf-8")
        notes.append(row)
    return {
        "item_type": data.get("item_type") or "document",
        "title": data.get("title") or "",
        "creators": list(data.get("creators") or []),
        "date": data.get("date") or "",
        "year": data.get("year"),
        "publication_title": data.get("publication_title") or "",
        "doi": data.get("doi") or data.get("library_doi"),
        "pmid": data.get("pmid"),
        "url": data.get("url"),
        "abstract": data.get("abstract") or "",
        "extra": data.get("extra") or "",
        "tags": list(data.get("tags") or []),
        "notes": notes,
        "pdfs": pdfs,
        "collection_paths": [
            p
            for p in (data.get("collection_paths") or [])
            if isinstance(p, str) and p and p != "_uncollected"
        ],
        "fields": data.get("fields") if isinstance(data.get("fields"), dict) else {},
        "item_key": data.get("item_key"),
    }


def parent_payload(record: dict[str, Any], collection_keys: list[str]) -> dict[str, Any]:
    """Zotero-shaped create payload (restore / import)."""
    data: dict[str, Any] = {
        "itemType": record.get("item_type") or "document",
        "title": record.get("title") or "",
        "creators": record.get("creators") or [],
        "abstractNote": record.get("abstract") or "",
        "date": record.get("date") or "",
        "DOI": record.get("doi") or "",
        "url": record.get("url") or "",
        "extra": record.get("extra") or "",
        "publicationTitle": record.get("publication_title") or "",
        "tags": list(record.get("tags") or []),
        "collections": collection_keys,
        "relations": {},
    }
    pmid = record.get("pmid")
    if pmid and "PMID:" not in (data["extra"] or ""):
        extra = (data["extra"] or "").rstrip()
        data["extra"] = f"{extra}\nPMID: {pmid}".strip() if extra else f"PMID: {pmid}"
    fields = record.get("fields")
    if isinstance(fields, dict):
        for key, value in fields.items():
            if key not in data:
                data[key] = value
    return data
