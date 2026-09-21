"""EndNote XML parse/write. PDFs via pdf-urls; notes via research-notes / notes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .types import endnote_to_zotero, zotero_to_endnote


def parse_endnote_xml(text: str, *, xml_path: Path | None = None) -> list[dict[str, Any]]:
    """Parse EndNote-generated XML. Resolves internal-pdf:// against xml_path parent."""
    if text.startswith("\ufeff"):
        text = text[1:]
    root = ET.fromstring(text)
    records: list[dict[str, Any]] = []
    base = xml_path.parent if xml_path is not None else None
    for rec_el in root.iter("record"):
        rec = _from_record(rec_el, base)
        if rec.get("title") or rec.get("doi"):
            records.append(rec)
    return records


def records_to_endnote_xml(
    records: list[dict[str, Any]], *, database: str = "paperful"
) -> str:
    xml = ET.Element("xml")
    recs = ET.SubElement(xml, "records")
    for i, rec in enumerate(records, start=1):
        recs.append(_to_record(rec, i, database))
    body = ET.tostring(xml, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8" ?>\n' + body + "\n"


def _from_record(el: ET.Element, base: Path | None) -> dict[str, Any]:
    ref = el.find("ref-type")
    name = (ref.get("name") if ref is not None else None) or ""
    number = None
    if ref is not None and (ref.text or "").strip().isdigit():
        number = int(ref.text.strip())
    title = _style_text(el.find("./titles/title"))
    year_s = _style_text(el.find("./dates/year"))
    year = int(year_s) if year_s.isdigit() else None
    if year is None:
        m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", year_s)
        year = int(m.group(1)) if m else None
    doi = _style_text(el.find("electronic-resource-num"))
    creators = []
    for author in el.findall("./contributors/authors/author"):
        creators.append(_person(_style_text(author), "author"))
    for editor in el.findall("./contributors/secondary-authors/author"):
        creators.append(_person(_style_text(editor), "editor"))
    keywords = [
        _style_text(k)
        for k in el.findall("./keywords/keyword")
        if _style_text(k)
    ]
    notes: list[dict[str, Any]] = []
    research = _style_text(el.find("research-notes"))
    if research:
        notes.append(
            {
                "file": "research-notes.html",
                "html": f"<p>{_escape(research)}</p>",
                "tag": "paperful-imported",
            }
        )
    body = _style_text(el.find("notes"))
    if body:
        notes.append(
            {
                "file": "notes.html",
                "html": f"<p>{_escape(body)}</p>",
                "tag": "paperful-imported",
            }
        )
    pdfs: list[str] = []
    for url in el.findall("./urls/pdf-urls/url"):
        href = (url.text or "").strip()
        if not href:
            continue
        resolved = _resolve_pdf(href, base)
        pdfs.append(resolved)
    url = _style_text(el.find("./urls/related-urls/url")) or _style_text(
        el.find("./web-urls/url")
    )
    extra = ""
    accession = _style_text(el.find("accession-num"))
    if accession:
        extra = f"PMID: {accession}" if accession.isdigit() else accession
    label = _style_text(el.find("label"))
    paths = [label] if label and "/" in label else []
    return {
        "item_type": endnote_to_zotero(name, number),
        "title": title,
        "creators": creators,
        "date": year_s or (str(year) if year else ""),
        "year": year,
        "publication_title": _style_text(el.find("./titles/secondary-title")),
        "doi": doi or None,
        "pmid": accession if accession.isdigit() else None,
        "url": url or None,
        "abstract": _style_text(el.find("abstract")),
        "extra": extra,
        "tags": [{"tag": k} for k in keywords],
        "notes": notes,
        "pdfs": pdfs,
        "collection_paths": paths,
    }


def _to_record(rec: dict[str, Any], n: int, database: str) -> ET.Element:
    num, name = zotero_to_endnote(str(rec.get("item_type") or "document"))
    el = ET.Element("record")
    db = ET.SubElement(el, "database")
    db.set("name", database)
    db.text = database
    src = ET.SubElement(el, "source-app")
    src.set("name", "paperful")
    src.text = "paperful"
    ET.SubElement(el, "rec-number").text = str(n)
    ref = ET.SubElement(el, "ref-type")
    ref.set("name", name)
    ref.text = str(num)
    contrib = ET.SubElement(el, "contributors")
    authors_el = ET.SubElement(contrib, "authors")
    editors_el = None
    for creator in rec.get("creators") or []:
        if not isinstance(creator, dict):
            continue
        display = _creator_name(creator)
        if not display:
            continue
        parent = authors_el
        if creator.get("creatorType") == "editor":
            if editors_el is None:
                editors_el = ET.SubElement(contrib, "secondary-authors")
            parent = editors_el
        a = ET.SubElement(parent, "author")
        _style(a, display)
    titles = ET.SubElement(el, "titles")
    _style(ET.SubElement(titles, "title"), rec.get("title") or "")
    if rec.get("publication_title"):
        _style(ET.SubElement(titles, "secondary-title"), rec["publication_title"])
    dates = ET.SubElement(el, "dates")
    _style(ET.SubElement(dates, "year"), str(rec.get("year") or rec.get("date") or ""))
    if rec.get("abstract"):
        _style(ET.SubElement(el, "abstract"), rec["abstract"])
    if rec.get("doi"):
        _style(ET.SubElement(el, "electronic-resource-num"), rec["doi"])
    if rec.get("pmid"):
        _style(ET.SubElement(el, "accession-num"), str(rec["pmid"]))
    tags = rec.get("tags") or []
    if tags:
        kw = ET.SubElement(el, "keywords")
        for tag in tags:
            label = tag.get("tag") if isinstance(tag, dict) else tag
            if label:
                _style(ET.SubElement(kw, "keyword"), str(label))
    notes_html = []
    for note in rec.get("notes") or []:
        if isinstance(note, dict) and note.get("html"):
            notes_html.append(_strip_html(note["html"]))
    if notes_html:
        _style(ET.SubElement(el, "research-notes"), "\n\n".join(notes_html))
    paths = rec.get("collection_paths") or []
    if paths:
        _style(ET.SubElement(el, "label"), paths[0])
    urls = ET.SubElement(el, "urls")
    pdfs = rec.get("pdfs") or []
    if pdfs:
        pdf_urls = ET.SubElement(urls, "pdf-urls")
        for pdf in pdfs:
            url = ET.SubElement(pdf_urls, "url")
            url.text = _pdf_href(pdf)
    if rec.get("url"):
        related = ET.SubElement(urls, "related-urls")
        u = ET.SubElement(related, "url")
        u.text = str(rec["url"])
    return el


def _style_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    style = el.find("style")
    if style is not None:
        return "".join(style.itertext()).strip()
    return "".join(el.itertext()).strip()


def _style(parent: ET.Element, text: str) -> None:
    style = ET.SubElement(parent, "style")
    style.set("face", "normal")
    style.set("font", "default")
    style.set("size", "100%")
    style.text = text


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


def _resolve_pdf(href: str, base: Path | None) -> str:
    if href.startswith("internal-pdf://"):
        name = href.split("://", 1)[-1].lstrip("/")
        if base is not None:
            for candidate in (
                base / "PDF" / name,
                base / name,
                base / Path(name).name,
            ):
                if candidate.is_file():
                    return str(candidate)
            nested = base / "PDF"
            if nested.is_dir():
                hits = list(nested.rglob(Path(name).name))
                if hits:
                    return str(hits[0])
        return str((base / "PDF" / name) if base is not None else Path(name))
    if href.startswith("file://"):
        return href.replace("file://", "", 1)
    return href


def _pdf_href(pdf: Any) -> str:
    text = str(pdf)
    if text.startswith("internal-pdf://") or text.startswith("file://"):
        return text
    path = Path(text)
    if path.exists():
        return path.resolve().as_uri()
    return f"internal-pdf://{Path(text).name}"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").replace("&nbsp;", " ").strip()
