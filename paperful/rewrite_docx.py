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
_XML_DECL = re.compile(rb"<\?xml[^?]*\?>")
_IGNORABLE = re.compile(r'\s(?:mc:)?Ignorable="([^"]+)"')

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


def _w_ids(*roots: ET.Element | None) -> list[int]:
    ids: list[int] = []
    for root in roots:
        if root is None:
            continue
        for el in root.iter():
            n = _xml_id(el)
            if n is not None:
                ids.append(n)
    return ids


def _next_w_id(*roots: ET.Element | None) -> int:
    ids = _w_ids(*roots)
    return (max(ids) + 1) if ids else 0


def _root_open_tag(xml: bytes, local: str) -> re.Match[bytes] | None:
    return re.search(rf"<w:{re.escape(local)}\b[^>]*>".encode("ascii"), xml)


def _serialize_part(original: bytes, root: ET.Element, *, local: str) -> bytes:
    """Write XML but keep the source root tag (xmlns / mc:Ignorable)."""
    _register_prefixes(original)
    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    orig_decl = _XML_DECL.match(original)
    new_decl = _XML_DECL.match(out)
    if orig_decl and new_decl:
        out = orig_decl.group(0) + out[new_decl.end() :]
    orig_root = _root_open_tag(original, local)
    new_root = _root_open_tag(out, local)
    if orig_root and new_root:
        out = out[: new_root.start()] + orig_root.group(0) + out[new_root.end() :]
    return out


def _undeclared_ignorable(xml: bytes) -> list[str]:
    found = _root_open_tag(xml, "document") or _root_open_tag(xml, "comments")
    if found is None:
        return []
    open_tag = found.group(0).decode("utf-8", "replace")
    declared = set(re.findall(r"xmlns:([A-Za-z0-9]+)=", open_tag))
    match = _IGNORABLE.search(open_tag)
    if not match:
        return []
    issues: list[str] = []
    for prefix in match.group(1).split():
        if prefix not in declared:
            issues.append(f"Ignorable prefix {prefix!r} is not declared")
    return issues


def docx_structural_issues(path: Path) -> list[str]:
    """Catch Word-repair triggers we control. Not a full OOXML schema validator."""
    issues: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            raw = zf.read("word/document.xml")
            comments_raw = zf.read("word/comments.xml") if "word/comments.xml" in names else None
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        return [f"docx: {exc}"]
    if b"ns0:" in raw:
        issues.append("document.xml uses ns0: prefixes")
    issues.extend(_undeclared_ignorable(raw))
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return issues + [f"document.xml: {exc}"]
    stack: list[str] = []
    starts: list[str] = []
    ends: list[str] = []
    refs: list[str] = []
    rev_ids: list[str] = []
    for el in root.iter():
        cid = el.get(f"{W}id")
        if el.tag == _w("commentRangeStart"):
            if cid in stack:
                issues.append(f"duplicate open comment {cid}")
            stack.append(cid or "")
            starts.append(cid or "")
        elif el.tag == _w("commentRangeEnd"):
            if not stack:
                issues.append(f"commentRangeEnd {cid} with no start")
            elif stack[-1] != cid:
                issues.append(f"crossed comment ranges: end {cid} while open {stack}")
                if cid in stack:
                    stack.remove(cid)
            else:
                stack.pop()
            ends.append(cid or "")
        elif el.tag == _w("commentReference"):
            refs.append(cid or "")
        elif el.tag in {_w("ins"), _w("del")} and cid is not None:
            rev_ids.append(cid)
    if stack:
        issues.append(f"unclosed comment ranges {stack}")
    if set(starts) != set(ends):
        issues.append("commentRangeStart/End ids do not match")
    if set(starts) != set(refs):
        issues.append("commentRangeStart/commentReference ids do not match")
    overlap = sorted(set(starts) & set(rev_ids), key=lambda x: int(x) if x.isdigit() else x)
    if overlap:
        issues.append(f"ins/del ids collide with comment ids {overlap}")
    if comments_raw is not None:
        if b"ns0:" in comments_raw:
            issues.append("comments.xml uses ns0: prefixes")
        try:
            croot = ET.fromstring(comments_raw)
        except ET.ParseError as exc:
            issues.append(f"comments.xml: {exc}")
        else:
            bodies = [
                el.get(f"{W}id") or ""
                for el in croot.iter(_w("comment"))
            ]
            missing = sorted(set(starts) - set(bodies))
            if missing:
                issues.append(f"comment ranges missing bodies {missing}")
    return issues


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
    next_id: int,
    when: str,
) -> tuple[list[tuple[int, str]], list[str]]:
    """Comments may stack on one paragraph; only one body rewrite per paragraph."""
    comments: list[tuple[int, str]] = []
    skips: list[str] = []
    rewritten: set[int] = set()

    def _match(edit: RewriteEdit, *, body: bool) -> bool:
        nonlocal next_id
        for i, p in enumerate(paras):
            if body and i in rewritten:
                continue
            blob = _para_text(p)
            if not (edit.quote and edit.quote in blob):
                continue
            if not body:
                _anchor_comment(p, next_id)
                comments.append((next_id, edit.body or edit.quote))
                next_id += 1
                return True
            if not _rewrite_paragraph(p, edit, next_id, when):
                continue
            next_id += 2 if edit.kind == "replace" else 1
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
    return comments, skips


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
    comments, edit_skips = _apply_edits_to_paras(
        paras,
        edits,
        next_id=_next_w_id(root, comments_root),
        when=when,
    )
    skips.extend(edit_skips)
    parts["word/document.xml"] = _serialize_part(xml, root, local="document")
    if comments:
        merged = _comments_xml(comments, when, existing=existing_comments)
        if existing_comments:
            merged_root = ET.fromstring(merged)
            parts["word/comments.xml"] = _serialize_part(
                existing_comments, merged_root, local="comments"
            )
        else:
            parts["word/comments.xml"] = merged
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
    comments, skips = _apply_edits_to_paras(
        para_nodes,
        edits,
        next_id=0,
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
