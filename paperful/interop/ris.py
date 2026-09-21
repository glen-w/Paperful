"""RIS (RefMan) parse/write. Notes in N1, tags in KW, PDFs in L1, DOI in DO/DOI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .types import ris_to_zotero, zotero_to_ris

_TAG = re.compile(r"^([A-Z][A-Z0-9])  - ?(.*)$")


def parse_ris(text: str) -> list[dict[str, Any]]:
    """Split on ER. Tolerates CRLF, a UTF-8 BOM, and blank lines after ER."""
    if text.startswith("\ufeff"):
        text = text[1:]
    records: list[dict[str, Any]] = []
    current: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        m = _TAG.match(line)
        if not m:
            if current and line.startswith("  "):
                tag, prev = current[-1]
                current[-1] = (tag, prev + " " + line.strip())
            continue
        tag, value = m.group(1), m.group(2)
        if tag == "ER":
            rec = _from_pairs(current)
            if rec.get("title") or rec.get("doi"):
                records.append(rec)
            current = []
            continue
        current.append((tag, value))
    if current:
        rec = _from_pairs(current)
        if rec.get("title") or rec.get("doi"):
            records.append(rec)
    return records


def _from_pairs(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    fields: dict[str, list[str]] = {}
    for tag, value in pairs:
        fields.setdefault(tag, []).append(value)

    def first(tag: str) -> str:
        return (fields.get(tag) or [""])[0].strip()
    item_type = ris_to_zotero(first("TY"))
    title = first("TI") or first("T1") or first("T2")
    year = None
    date = first("PY") or first("Y1") or first("DA")
    m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", date)
    if m:
        year = int(m.group(1))
    doi = first("DO") or first("DOI")
    if doi.lower().startswith("https://doi.org/"):
        doi = doi.split("doi.org/", 1)[-1]
    creators = []
    for name in fields.get("AU") or fields.get("A1") or []:
        creators.append(_person(name, "author"))
    for name in fields.get("A2") or fields.get("ED") or []:
        creators.append(_person(name, "editor"))
    tags = [{"tag": k} for k in (fields.get("KW") or []) if k.strip()]
    notes = []
    for i, body in enumerate(fields.get("N1") or fields.get("N2") or []):
        if body.strip():
            notes.append(
                {
                    "file": f"ris-note-{i + 1}.html",
                    "html": f"<p>{_escape(body.strip())}</p>",
                    "tag": "paperful-imported",
                }
            )
    pdfs = [p.strip() for p in (fields.get("L1") or []) if p.strip()]
    pdfs += [p.strip() for p in (fields.get("L2") or []) if p.strip()]
    url = first("UR") or first("L3")
    extra_bits = []
    pmid = first("AN")
    if pmid.lower().startswith("pmid"):
        extra_bits.append(f"PMID: {pmid.split(':', 1)[-1].strip()}")
        pmid = pmid.split(":", 1)[-1].strip()
    elif first("C2"):
        pmid = first("C2")
        extra_bits.append(f"PMID: {pmid}")
    return {
        "item_type": item_type,
        "title": title,
        "creators": creators,
        "date": date or (str(year) if year else ""),
        "year": year,
        "publication_title": first("JO") or first("T2") or first("JF"),
        "doi": doi or None,
        "pmid": pmid or None,
        "url": url or None,
        "abstract": first("AB") or first("N2"),
        "extra": "\n".join(extra_bits),
        "tags": tags,
        "notes": notes,
        "pdfs": pdfs,
        "collection_paths": [],
    }


def records_to_ris(records: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for rec in records:
        lines = [f"TY  - {zotero_to_ris(str(rec.get('item_type') or 'document'))}"]
        if rec.get("title"):
            lines.append(f"TI  - {rec['title']}")
        for creator in rec.get("creators") or []:
            if not isinstance(creator, dict):
                continue
            name = _creator_name(creator)
            if not name:
                continue
            tag = "AU" if creator.get("creatorType") != "editor" else "ED"
            lines.append(f"{tag}  - {name}")
        year = rec.get("year") or rec.get("date")
        if year:
            lines.append(f"PY  - {year}")
        if rec.get("publication_title"):
            lines.append(f"JO  - {rec['publication_title']}")
        if rec.get("doi"):
            lines.append(f"DO  - {rec['doi']}")
        if rec.get("url"):
            lines.append(f"UR  - {rec['url']}")
        if rec.get("abstract"):
            lines.append(f"AB  - {rec['abstract']}")
        if rec.get("pmid"):
            lines.append(f"AN  - PMID:{rec['pmid']}")
        for tag in rec.get("tags") or []:
            label = tag.get("tag") if isinstance(tag, dict) else tag
            if label:
                lines.append(f"KW  - {label}")
        for note in rec.get("notes") or []:
            html = note.get("html") if isinstance(note, dict) else ""
            if html:
                lines.append(f"N1  - {_strip_html(html)}")
        for pdf in rec.get("pdfs") or []:
            lines.append(f"L1  - {_file_url(pdf)}")
        lines.append("ER  - ")
        chunks.append("\r\n".join(lines))
    return "\r\n".join(chunks) + ("\r\n" if chunks else "")


def _person(name: str, role: str) -> dict[str, str]:
    name = name.strip()
    if "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
        return {"creatorType": role, "lastName": last, "firstName": first}
    parts = name.split()
    if len(parts) >= 2:
        return {
            "creatorType": role,
            "lastName": parts[-1],
            "firstName": " ".join(parts[:-1]),
        }
    return {"creatorType": role, "lastName": name, "firstName": ""}


def _creator_name(creator: dict[str, Any]) -> str:
    last = (creator.get("lastName") or creator.get("name") or "").strip()
    first = (creator.get("firstName") or "").strip()
    if last and first:
        return f"{last}, {first}"
    return last


def _file_url(pdf: Any) -> str:
    text = str(pdf)
    if text.startswith("file:") or text.startswith("internal-pdf:"):
        return text
    path = Path(text)
    if path.is_file() or path.is_absolute():
        return path.resolve().as_uri() if path.exists() else path.as_uri()
    return text


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").replace("&nbsp;", " ").strip()
