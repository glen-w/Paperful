"""Tracked-changes OOXML via stdlib zipfile + ElementTree. No python-docx."""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from .rewrite_plan import RewriteEdit

W_URI = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_URI}}}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
RELS_URI = "http://schemas.openxmlformats.org/package/2006/relationships"
RELS = f"{{{RELS_URI}}}"
COMMENTS_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
)
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
AUTHOR = "paperful rewrite"
_NS_DECL = re.compile(rb'xmlns:([A-Za-z0-9]+)="([^"]+)"')

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


def _register_prefixes(xml: bytes) -> None:
    """Keep Word's ``w:`` prefixes instead of ElementTree ``ns0:`` on write."""
    ET.register_namespace("w", W_URI)
    for match in _NS_DECL.finditer(xml[:8000]):
        prefix = match.group(1).decode("ascii")
        uri = match.group(2).decode("ascii")
        if prefix != "xml":
            ET.register_namespace(prefix, uri)


def _xml_id(el: ET.Element) -> int | None:
    raw = el.get(f"{W}id") or el.get("id")
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def _next_comment_id(doc_root: ET.Element, comments_root: ET.Element | None) -> int:
    ids: list[int] = []
    for tag in ("commentRangeStart", "commentRangeEnd", "commentReference"):
        for el in doc_root.iter(_w(tag)):
            n = _xml_id(el)
            if n is not None:
                ids.append(n)
    if comments_root is not None:
        for el in comments_root.iter(_w("comment")):
            n = _xml_id(el)
            if n is not None:
                ids.append(n)
    return (max(ids) + 1) if ids else 0


def _parse_comments(raw: bytes | None) -> ET.Element | None:
    if not raw:
        return None
    try:
        _register_prefixes(raw)
        return ET.fromstring(raw)
    except ET.ParseError:
        return None


def _ensure_comments_rel(rels: bytes) -> bytes:
    if b"comments.xml" in rels:
        return rels
    try:
        root = ET.fromstring(rels)
    except ET.ParseError:
        return _DOC_RELS_TMPL.encode("utf-8")
    existing = {el.get("Id") for el in root}
    rid = "rIdCmt1"
    n = 1
    while rid in existing:
        n += 1
        rid = f"rIdCmt{n}"
    ET.SubElement(
        root,
        f"{RELS}Relationship",
        {"Id": rid, "Type": COMMENTS_REL, "Target": "comments.xml"},
    )
    ET.register_namespace("", RELS_URI)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


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


def _is_comment_ref_run(child: ET.Element) -> bool:
    if child.tag != _w("r"):
        return False
    has_ref = any(el.tag == _w("commentReference") for el in child.iter())
    has_text = any(el.tag == _w("t") for el in child.iter())
    return has_ref and not has_text


def _detach_comment_chrome(
    p: ET.Element,
) -> tuple[list[ET.Element], list[ET.Element]]:
    starts: list[ET.Element] = []
    tails: list[ET.Element] = []
    for child in list(p):
        if child.tag == _w("commentRangeStart"):
            starts.append(child)
            p.remove(child)
        elif child.tag == _w("commentRangeEnd") or _is_comment_ref_run(child):
            tails.append(child)
            p.remove(child)
    return starts, tails


def _reattach_comment_chrome(
    p: ET.Element, starts: list[ET.Element], tails: list[ET.Element]
) -> None:
    pPr = p.find(_w("pPr"))
    idx = 1 if pPr is not None else 0
    for start in starts:
        p.insert(idx, start)
        idx += 1
    for tail in tails:
        p.append(tail)


def _rewrite_paragraph(p: ET.Element, edit: RewriteEdit, rev: int, when: str) -> bool:
    blob = _para_text(p)
    quote = edit.quote
    if not quote or quote not in blob:
        return False
    before, after = blob.split(quote, 1)
    starts, tails = _detach_comment_chrome(p)
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
    _reattach_comment_chrome(p, starts, tails)
    return True


def _apply_edits_to_paras(
    paras: list[ET.Element],
    edits: list[RewriteEdit],
    *,
    comment_id: int,
    rev: int,
    when: str,
) -> tuple[list[tuple[int, str]], list[str], int, int]:
    """Comments may stack on one paragraph; only one body rewrite per paragraph."""
    comments: list[tuple[int, str]] = []
    skips: list[str] = []
    rewritten: set[int] = set()

    def _match(edit: RewriteEdit, *, body: bool) -> bool:
        nonlocal comment_id, rev
        for i, p in enumerate(paras):
            if body and i in rewritten:
                continue
            blob = _para_text(p)
            if not (edit.quote and edit.quote in blob):
                continue
            if not body:
                _anchor_comment(p, comment_id)
                comments.append((comment_id, edit.body or edit.quote))
                comment_id += 1
                return True
            if not _rewrite_paragraph(p, edit, rev, when):
                continue
            rev += 2
            rewritten.add(i)
            return True
        return False

    for edit in edits:
        if edit.kind == "comment":
            if not _match(edit, body=False):
                skips.append(edit.quote[:80] or edit.kind)
    for edit in edits:
        if edit.kind != "comment":
            if not _match(edit, body=True):
                skips.append(edit.quote[:80] or edit.kind)
    return comments, skips, comment_id, rev


def _comment_el(cid: int, body: str, when: str) -> ET.Element:
    node = _el("comment", {"id": str(cid), "author": AUTHOR, "date": when, "initials": "pf"})
    p = _el("p")
    ref_run = _el("r")
    ref_run.append(_el("annotationRef"))
    p.append(ref_run)
    p.append(_run(body))
    node.append(p)
    return node


def _comments_xml(
    comments: list[tuple[int, str]],
    when: str,
    *,
    existing: bytes | None = None,
) -> bytes:
    ET.register_namespace("w", W_URI)
    root = _parse_comments(existing)
    if root is None:
        root = ET.Element(_w("comments"))
    for cid, body in comments:
        root.append(_comment_el(cid, body, when))
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
        _register_prefixes(xml)
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return [f"docx: {exc}"]
    existing_comments = parts.get("word/comments.xml")
    comments_root = _parse_comments(existing_comments)
    paras = list(root.iter(_w("p")))
    comments, edit_skips, _, _ = _apply_edits_to_paras(
        paras,
        edits,
        comment_id=_next_comment_id(root, comments_root),
        rev=1,
        when=when,
    )
    skips.extend(edit_skips)
    parts["word/document.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if comments:
        parts["word/comments.xml"] = _comments_xml(
            comments, when, existing=existing_comments
        )
        rels = parts.get("word/_rels/document.xml.rels", b"")
        parts["word/_rels/document.xml.rels"] = _ensure_comments_rel(rels)
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
    comments, skips, _, _ = _apply_edits_to_paras(
        para_nodes,
        edits,
        comment_id=0,
        rev=1,
        when=when,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    ET.register_namespace("w", W_URI)
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
