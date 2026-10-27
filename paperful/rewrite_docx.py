"""Tracked-changes OOXML via stdlib zipfile + ElementTree. No python-docx."""

from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from .rewrite_plan import RewriteEdit

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
AUTHOR = "paperful rewrite"

_CONTENT_TYPES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
</Types>
"""
_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
_DOC_RELS_TMPL = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
</Relationships>
"""


def _w(tag: str) -> str:
    return f"{W}{tag}"


def _el(tag: str, attrib: dict[str, str] | None = None, text: str | None = None) -> ET.Element:
    node = ET.Element(_w(tag))
    for k, v in (attrib or {}).items():
        node.set(_w(k), v)
    if text is not None:
        node.text = text
    return node


def _run(text: str) -> ET.Element:
    r = _el("r")
    t = _el("t", text=text)
    t.set(XML_SPACE, "preserve")
    r.append(t)
    return r


def _ins(text: str, rev: int, when: str) -> ET.Element:
    node = _el("ins", {"id": str(rev), "author": AUTHOR, "date": when})
    node.append(_run(text))
    return node


def _del(text: str, rev: int, when: str) -> ET.Element:
    node = _el("del", {"id": str(rev), "author": AUTHOR, "date": when})
    inner = _el("r")
    dt = _el("delText", text=text)
    dt.set(XML_SPACE, "preserve")
    inner.append(dt)
    node.append(inner)
    return node


def _para_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(_w("t")))


def _rewrite_paragraph(p: ET.Element, edit: RewriteEdit, rev: int, when: str) -> bool:
    blob = _para_text(p)
    quote = edit.quote
    if not quote or quote not in blob:
        return False
    before, after = blob.split(quote, 1)
    pPr = p.find(_w("pPr"))
    for child in list(p):
        if child is not pPr:
            p.remove(child)
    if before:
        p.append(_run(before))
    if edit.kind == "replace":
        p.append(_del(quote, rev, when))
        p.append(_ins(edit.replacement, rev + 1, when))
    elif edit.kind == "delete":
        p.append(_del(quote, rev, when))
    elif edit.kind == "insert":
        p.append(_run(quote))
        p.append(_ins(edit.replacement, rev, when))
    else:
        p.append(_run(quote))
    if after:
        p.append(_run(after))
    return True


def _comments_xml(comments: list[tuple[int, str]], when: str) -> bytes:
    root = ET.Element(_w("comments"))
    for cid, body in comments:
        node = _el("comment", {"id": str(cid), "author": AUTHOR, "date": when, "initials": "pf"})
        p = _el("p")
        p.append(_run(body))
        node.append(p)
        root.append(node)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _anchor_comment(p: ET.Element, cid: int) -> None:
    start = _el("commentRangeStart", {"id": str(cid)})
    end = _el("commentRangeEnd", {"id": str(cid)})
    ref_p = _el("r")
    ref_p.append(_el("commentReference", {"id": str(cid)}))
    children = list(p)
    # Insert start after pPr if present.
    idx = 1 if children and children[0].tag == _w("pPr") else 0
    p.insert(idx, start)
    p.append(end)
    p.append(ref_p)


def apply_tracked_docx(src: Path, dest: Path, edits: list[RewriteEdit]) -> list[str]:
    """Copy ``src`` to ``dest`` with ins/del/comments. Returns skip reasons."""
    skips: list[str] = []
    when = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with zipfile.ZipFile(src) as zin:
            parts = {name: zin.read(name) for name in zin.namelist()}
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"docx: {exc}"]
    xml = parts.get("word/document.xml")
    if not xml:
        return ["docx: missing word/document.xml"]
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return [f"docx: {exc}"]
    paras = list(root.iter(_w("p")))
    rev = 1
    comment_id = 0
    comments: list[tuple[int, str]] = []
    used: set[int] = set()
    for edit in edits:
        matched = False
        for i, p in enumerate(paras):
            if i in used:
                continue
            blob = _para_text(p)
            if edit.quote and edit.quote in blob:
                if edit.kind == "comment":
                    comment_id += 1
                    _anchor_comment(p, comment_id)
                    comments.append((comment_id, edit.body or edit.quote))
                else:
                    if not _rewrite_paragraph(p, edit, rev, when):
                        continue
                    rev += 2
                used.add(i)
                matched = True
                break
        if not matched:
            skips.append(edit.quote[:80] or edit.kind)
    parts["word/document.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if comments:
        parts["word/comments.xml"] = _comments_xml(comments, when)
        rels = parts.get("word/_rels/document.xml.rels", b"")
        if b"comments.xml" not in rels:
            parts["word/_rels/document.xml.rels"] = _DOC_RELS_TMPL.encode("utf-8")
        ctypes = parts.get("[Content_Types].xml", b"")
        if b"word/comments.xml" not in ctypes:
            try:
                ct_root = ET.fromstring(ctypes) if ctypes else ET.fromstring(_CONTENT_TYPES)
                ET.SubElement(
                    ct_root,
                    f"{CT}Override",
                    {
                        "PartName": "/word/comments.xml",
                        "ContentType": (
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.comments+xml"
                        ),
                    },
                )
                parts["[Content_Types].xml"] = ET.tostring(
                    ct_root, encoding="utf-8", xml_declaration=True
                )
            except ET.ParseError:
                parts["[Content_Types].xml"] = _CONTENT_TYPES.encode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, data in parts.items():
            zout.writestr(name, data)
    return skips


def build_docx_from_paragraphs(
    dest: Path,
    paragraphs: list[str],
    edits: list[RewriteEdit],
) -> list[str]:
    """Minimal tracked-changes docx from extract paragraphs (md → Word spine)."""
    when = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = ET.Element(_w("document"))
    body = _el("body")
    document.append(body)
    para_nodes: list[ET.Element] = []
    for text in paragraphs:
        p = _el("p")
        p.append(_run(text))
        body.append(p)
        para_nodes.append(p)
    skips: list[str] = []
    rev = 1
    comment_id = 0
    comments: list[tuple[int, str]] = []
    used: set[int] = set()
    for edit in edits:
        matched = False
        for i, p in enumerate(para_nodes):
            if i in used:
                continue
            blob = _para_text(p)
            if edit.quote and edit.quote in blob:
                if edit.kind == "comment":
                    comment_id += 1
                    _anchor_comment(p, comment_id)
                    comments.append((comment_id, edit.body or edit.quote))
                else:
                    _rewrite_paragraph(p, edit, rev, when)
                    rev += 2
                used.add(i)
                matched = True
                break
        if not matched:
            skips.append(edit.quote[:80] or edit.kind)
    dest.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("word/_rels/document.xml.rels", _DOC_RELS_TMPL)
        zf.writestr(
            "word/document.xml",
            ET.tostring(document, encoding="utf-8", xml_declaration=True),
        )
        zf.writestr("word/comments.xml", _comments_xml(comments, when))
    dest.write_bytes(buf.getvalue())
    return skips
