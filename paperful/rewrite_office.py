"""In-place unique-span edits for rewrite ``tracked.pptx`` / ``tracked.odt``.

Not Word revision markup. PowerPoint has none we round-trip; ODF tracked
changes are a later pass. Comments skip (they still land in the edit plan).
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .rewrite_plan import RewriteEdit

A_URI = "http://schemas.openxmlformats.org/drawingml/2006/main"
A = f"{{{A_URI}}}"
OFFICE_URI = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
OFFICE = f"{{{OFFICE_URI}}}"
TEXT_URI = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
TEXT = f"{{{TEXT_URI}}}"
DC_URI = "http://purl.org/dc/elements/1.1/"
MANIFEST_URI = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
MIMETYPE = b"application/vnd.oasis.opendocument.text"
_NS_DECL = re.compile(rb'xmlns:([A-Za-z0-9]+)="([^"]+)"')
_XML_DECL = re.compile(rb"<\?xml[^?]*\?>")
_SLIDE = re.compile(r"ppt/slides/slide\d+\.xml")


def _register_prefixes(xml: bytes) -> None:
    for match in _NS_DECL.finditer(xml[:12000]):
        prefix = match.group(1).decode("ascii")
        uri = match.group(2).decode("ascii")
        if prefix != "xml":
            ET.register_namespace(prefix, uri)


def _root_open_tag(xml: bytes, local: str) -> re.Match[bytes] | None:
    return re.search(
        rf"<(?:[A-Za-z0-9]+:)?{re.escape(local)}\b[^>]*>".encode("ascii"), xml
    )


def _serialize_part(original: bytes, root: ET.Element, *, local: str) -> bytes:
    """Write XML but keep the source root tag (xmlns)."""
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


def _copy_zip(src: Path) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    with zipfile.ZipFile(src) as zin:
        infos = list(zin.infolist())
        parts = {info.filename: zin.read(info.filename) for info in infos}
    return infos, parts


def _write_zip(
    dest: Path, infos: list[zipfile.ZipInfo], parts: dict[str, bytes]
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w") as zout:
        for info in infos:
            data = parts.get(info.filename)
            if data is None:
                continue
            copied = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
            copied.compress_type = info.compress_type
            copied.external_attr = info.external_attr
            zout.writestr(copied, data)


def _apply_blob(blob: str, edit: RewriteEdit) -> str | None:
    quote = edit.quote
    if not quote or quote not in blob:
        return None
    if edit.kind == "replace":
        return blob.replace(quote, edit.replacement, 1)
    if edit.kind == "delete":
        return blob.replace(quote, "", 1)
    if edit.kind == "insert":
        return blob.replace(quote, quote + edit.replacement, 1)
    return None


def _comment_skip(edit: RewriteEdit, kind: str) -> str:
    quote = (edit.quote or edit.kind)[:80]
    return f"{kind} comments are plan-only: {quote}"


def pptx_structural_issues(path: Path) -> list[str]:
    """Catch PowerPoint-repair triggers we control. Not a full SDK validator."""
    issues: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            slides = sorted(n for n in names if _SLIDE.fullmatch(n))
            if not slides:
                return ["pptx: missing ppt/slides/slideN.xml"]
            blobs = [(name, zf.read(name)) for name in slides]
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"pptx: {exc}"]
    for name, raw in blobs:
        if b"ns0:" in raw:
            issues.append(f"{name} uses ns0: prefixes")
        try:
            ET.fromstring(raw)
        except ET.ParseError as exc:
            issues.append(f"{name}: {exc}")
    return issues


def odt_structural_issues(path: Path) -> list[str]:
    """Catch LibreOffice-repair triggers we control. Not a full ODF validator."""
    try:
        with zipfile.ZipFile(path) as zf:
            raw = zf.read("content.xml")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        return [f"odt: {exc}"]
    issues: list[str] = []
    if b"ns0:" in raw:
        issues.append("content.xml uses ns0: prefixes")
    try:
        ET.fromstring(raw)
    except ET.ParseError as exc:
        issues.append(f"content.xml: {exc}")
    return issues


def _rewrite_t_nodes(nodes: list[ET.Element], edit: RewriteEdit) -> bool:
    for node in nodes:
        text = node.text or ""
        applied = _apply_blob(text, edit)
        if applied is None:
            continue
        node.text = applied
        return True
    blob = "".join(n.text or "" for n in nodes)
    applied = _apply_blob(blob, edit)
    if applied is None or not nodes:
        return False
    nodes[0].text = applied
    for node in nodes[1:]:
        node.text = ""
    return True


def apply_pptx(src: Path, dest: Path, edits: list[RewriteEdit]) -> list[str]:
    """Copy ``src`` to ``dest`` with unique-span replacements. Comments skip."""
    try:
        infos, parts = _copy_zip(src)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"pptx: {exc}"]
    slides = sorted(n for n in parts if _SLIDE.fullmatch(n))
    if not slides:
        return ["pptx: missing ppt/slides/slideN.xml"]
    parsed: list[tuple[str, bytes, ET.Element]] = []
    for name in slides:
        raw = parts[name]
        try:
            _register_prefixes(raw)
            parsed.append((name, raw, ET.fromstring(raw)))
        except ET.ParseError as exc:
            return [f"pptx: {exc}"]
    skips: list[str] = []
    rewritten: set[int] = set()
    for edit in edits:
        if edit.kind == "comment":
            skips.append(_comment_skip(edit, "pptx"))
            continue
        matched = False
        for i, (_name, _raw, root) in enumerate(parsed):
            if i in rewritten:
                continue
            nodes = list(root.iter(f"{A}t"))
            if _rewrite_t_nodes(nodes, edit):
                rewritten.add(i)
                matched = True
                break
        if not matched:
            skips.append(edit.quote[:80] or edit.kind)
    for name, raw, root in parsed:
        parts[name] = _serialize_part(raw, root, local="sld")
    _write_zip(dest, infos, parts)
    return skips


def _apply_odt_edits(paras: list[ET.Element], edits: list[RewriteEdit]) -> list[str]:
    skips: list[str] = []
    rewritten: set[int] = set()
    for edit in edits:
        if edit.kind == "comment":
            skips.append(_comment_skip(edit, "odt"))
            continue
        matched = False
        for i, para in enumerate(paras):
            if i in rewritten:
                continue
            blob = "".join(para.itertext())
            applied = _apply_blob(blob, edit)
            if applied is None:
                continue
            for child in list(para):
                para.remove(child)
            para.text = applied
            para.tail = None
            rewritten.add(i)
            matched = True
            break
        if not matched:
            skips.append(edit.quote[:80] or edit.kind)
    return skips


def apply_odt(src: Path, dest: Path, edits: list[RewriteEdit]) -> list[str]:
    """Copy ``src`` to ``dest`` with unique-span replacements. Comments skip."""
    try:
        infos, parts = _copy_zip(src)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"odt: {exc}"]
    raw = parts.get("content.xml")
    if not raw:
        return ["odt: missing content.xml"]
    try:
        _register_prefixes(raw)
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return [f"odt: {exc}"]
    skips = _apply_odt_edits(list(root.iter(f"{TEXT}p")), edits)
    parts["content.xml"] = _serialize_part(raw, root, local="document-content")
    _write_zip(dest, infos, parts)
    return skips


def _odt_manifest() -> bytes:
    ET.register_namespace("manifest", MANIFEST_URI)
    root = ET.Element(
        f"{{{MANIFEST_URI}}}manifest",
        {f"{{{MANIFEST_URI}}}version": "1.3"},
    )
    for path, media in (
        ("/", "application/vnd.oasis.opendocument.text"),
        ("content.xml", "text/xml"),
        ("styles.xml", "text/xml"),
        ("meta.xml", "text/xml"),
    ):
        attrib = {
            f"{{{MANIFEST_URI}}}full-path": path,
            f"{{{MANIFEST_URI}}}media-type": media,
        }
        if path == "/":
            attrib[f"{{{MANIFEST_URI}}}version"] = "1.3"
        ET.SubElement(root, f"{{{MANIFEST_URI}}}file-entry", attrib)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _odt_styles() -> bytes:
    ET.register_namespace("office", OFFICE_URI)
    root = ET.Element(
        f"{OFFICE}document-styles",
        {f"{OFFICE}version": "1.3"},
    )
    ET.SubElement(root, f"{OFFICE}styles")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _odt_meta() -> bytes:
    ET.register_namespace("office", OFFICE_URI)
    ET.register_namespace("dc", DC_URI)
    root = ET.Element(
        f"{OFFICE}document-meta",
        {f"{OFFICE}version": "1.3"},
    )
    meta = ET.SubElement(root, f"{OFFICE}meta")
    creator = ET.SubElement(meta, f"{{{DC_URI}}}creator")
    creator.text = "paperful rewrite"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_odt_from_paragraphs(
    dest: Path,
    paragraphs: list[str],
    edits: list[RewriteEdit],
) -> list[str]:
    """Minimal ODF text document from extract paragraphs (md → OpenDocument)."""
    ET.register_namespace("office", OFFICE_URI)
    ET.register_namespace("text", TEXT_URI)
    root = ET.Element(
        f"{OFFICE}document-content",
        {f"{OFFICE}version": "1.3"},
    )
    body = ET.SubElement(root, f"{OFFICE}body")
    text_el = ET.SubElement(body, f"{OFFICE}text")
    para_nodes: list[ET.Element] = []
    for blob in paragraphs:
        p = ET.SubElement(text_el, f"{TEXT}p")
        p.text = blob
        para_nodes.append(p)
    skips = _apply_odt_edits(para_nodes, edits)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w") as zf:
        stored = zipfile.ZipInfo("mimetype")
        stored.compress_type = zipfile.ZIP_STORED
        zf.writestr(stored, MIMETYPE)
        zf.writestr("META-INF/manifest.xml", _odt_manifest())
        zf.writestr("styles.xml", _odt_styles())
        zf.writestr("meta.xml", _odt_meta())
        zf.writestr(
            "content.xml",
            ET.tostring(root, encoding="utf-8", xml_declaration=True),
        )
    return skips
