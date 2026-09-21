"""Minimal BibTeX parse/write for library interchange (title, authors, year, DOI, file)."""

from __future__ import annotations

import re
from typing import Any

from .types import bibtex_to_zotero, zotero_to_bibtex

_ENTRY = re.compile(
    r"@(\w+)\s*\{\s*([^,]+)\s*,(.*?)\n\}",
    re.DOTALL | re.IGNORECASE,
)
_FIELD = re.compile(
    r"(\w+)\s*=\s*(\{+(?:[^{}]|\{[^{}]*\})*\}+|\"[^\"]*\"|[^\s,]+)\s*,?",
    re.DOTALL,
)


def parse_bibtex(text: str) -> list[dict[str, Any]]:
    if text.startswith("\ufeff"):
        text = text[1:]
    records: list[dict[str, Any]] = []
    for m in _ENTRY.finditer(text):
        entry_type, _key, body = m.group(1), m.group(2), m.group(3)
        fields: dict[str, str] = {}
        for fm in _FIELD.finditer(body):
            fields[fm.group(1).lower()] = _unquote(fm.group(2))
        title = fields.get("title") or ""
        year = None
        raw_year = fields.get("year") or fields.get("date") or ""
        ym = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", raw_year)
        if ym:
            year = int(ym.group(1))
        doi = (fields.get("doi") or "").replace("https://doi.org/", "")
        creators = [_person(p, "author") for p in _split_and(fields.get("author") or "")]
        creators += [_person(p, "editor") for p in _split_and(fields.get("editor") or "")]
        pdfs = []
        file_field = fields.get("file") or fields.get("pdf") or ""
        for part in re.split(r"[;]", file_field):
            path = part.strip()
            if ":" in path and not path.startswith("/") and not re.match(r"^[A-Za-z]:", path):
                # JabRef: description:path:type
                bits = path.split(":")
                path = bits[1] if len(bits) >= 2 else bits[0]
            if path:
                pdfs.append(path)
        keywords = fields.get("keywords") or fields.get("mendeley-tags") or ""
        tags = [{"tag": k.strip()} for k in re.split(r"[,;]", keywords) if k.strip()]
        extra = ""
        if fields.get("pmid"):
            extra = f"PMID: {fields['pmid']}"
        rec = {
            "item_type": bibtex_to_zotero(entry_type),
            "title": title.strip("{} "),
            "creators": [c for c in creators if c.get("lastName")],
            "date": raw_year or (str(year) if year else ""),
            "year": year,
            "publication_title": fields.get("journal") or fields.get("booktitle") or "",
            "doi": doi or None,
            "pmid": fields.get("pmid") or None,
            "url": fields.get("url") or None,
            "abstract": fields.get("abstract") or "",
            "extra": extra,
            "tags": tags,
            "notes": [],
            "pdfs": pdfs,
            "collection_paths": [],
        }
        note = fields.get("note") or fields.get("annote") or ""
        if note:
            rec["notes"].append(
                {
                    "file": "bibtex-note.html",
                    "html": f"<p>{_escape(note)}</p>",
                    "tag": "paperful-imported",
                }
            )
        if rec["title"] or rec["doi"]:
            records.append(rec)
    return records


def records_to_bibtex(records: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for i, rec in enumerate(records, start=1):
        entry = zotero_to_bibtex(str(rec.get("item_type") or "document"))
        key = _cite_key(rec, i)
        fields = [
            ("title", rec.get("title") or ""),
            ("author", " and ".join(_creator_bib(c) for c in rec.get("creators") or [] if isinstance(c, dict))),
            ("year", str(rec.get("year") or rec.get("date") or "")),
            ("journal", rec.get("publication_title") or ""),
            ("doi", rec.get("doi") or ""),
            ("url", rec.get("url") or ""),
            ("abstract", rec.get("abstract") or ""),
        ]
        if rec.get("pmid"):
            fields.append(("pmid", str(rec["pmid"])))
        tags = [
            t.get("tag") if isinstance(t, dict) else t for t in (rec.get("tags") or [])
        ]
        tags = [str(t) for t in tags if t]
        if tags:
            fields.append(("keywords", ", ".join(tags)))
        pdfs = rec.get("pdfs") or []
        if pdfs:
            fields.append(("file", ";".join(str(p) for p in pdfs)))
        body = ",\n".join(
            f"  {name} = {{{_escape_braces(val)}}}" for name, val in fields if val
        )
        chunks.append(f"@{entry}{{{key},\n{body}\n}}")
    return "\n\n".join(chunks) + ("\n" if chunks else "")


def _unquote(value: str) -> str:
    value = value.strip().rstrip(",").strip()
    if (value.startswith("{") and value.endswith("}")) or (
        value.startswith('"') and value.endswith('"')
    ):
        value = value[1:-1]
        if value.startswith("{") and value.endswith("}"):
            value = value[1:-1]
    return value.strip()


def _split_and(authors: str) -> list[str]:
    return [p.strip() for p in re.split(r"\s+and\s+", authors, flags=re.I) if p.strip()]


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


def _creator_bib(creator: dict[str, Any]) -> str:
    last = (creator.get("lastName") or creator.get("name") or "").strip()
    first = (creator.get("firstName") or "").strip()
    if last and first:
        return f"{last}, {first}"
    return last


def _cite_key(rec: dict[str, Any], n: int) -> str:
    last = "item"
    for c in rec.get("creators") or []:
        if isinstance(c, dict) and c.get("lastName"):
            last = re.sub(r"[^A-Za-z0-9]", "", c["lastName"]) or "item"
            break
    year = rec.get("year") or "nd"
    return f"{last}{year}_{n}"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_braces(text: str) -> str:
    return str(text).replace("{", "\\{").replace("}", "\\}")
