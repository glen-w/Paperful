"""Local text extract for ``paperful critique``. No new PyPI deps."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .pdfid import probe_pdf, text_from_pdf

MIN_ALNUM = 40
MAX_UPLOAD_BYTES = 40 * 1024 * 1024
SUPPORTED = frozenset(
    {
        ".pdf",
        ".txt",
        ".md",
        ".html",
        ".htm",
        ".docx",
        ".odt",
        ".rtf",
        ".doc",
        ".pptx",
    }
)
ACCEPT = ",".join(sorted(SUPPORTED))
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_RTF_GROUP = re.compile(r"\\'[0-9a-fA-F]{2}|\\[a-zA-Z]+-?\d* ?|[{}]")
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_OFFICE_NS = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


class ExtractError(Exception):
    """The file could not be read as text."""


@dataclass
class ExtractedDoc:
    """Plain text plus locatable slices for findings."""

    text: str
    format: str
    pages: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    loc_kind: str = "page"  # page | paragraph | slide
    finding: str = "ok"  # ok | needs_ocr | empty_extract | unsupported | no_file
    pdf_pages: int = 0
    pdf_words: int = 0
    error: str = ""


def safe_filename(name: str) -> str:
    raw = Path(name or "upload.bin").name
    safe = _SAFE_NAME.sub("-", raw).strip(".-") or "upload.bin"
    return safe[:180]


def stage_file(cfg: object, src: Path, *, name: str | None = None) -> Path:
    """Copy ``src`` under ``state/critiques/uploads/<stamp>-<safe>/``."""
    from datetime import datetime, timezone

    from .config import Config

    assert isinstance(cfg, Config)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = safe_filename(name or src.name)
    dest_dir = cfg.state_dir / "critiques" / "uploads" / f"{stamp}-{Path(safe).stem}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe
    data = src.read_bytes()
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExtractError(
            f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    dest.write_bytes(data)
    return dest


def stage_bytes(cfg: object, data: bytes, name: str) -> Path:
    from datetime import datetime, timezone

    from .config import Config

    assert isinstance(cfg, Config)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = safe_filename(name)
    dest_dir = cfg.state_dir / "critiques" / "uploads" / f"{stamp}-{Path(safe).stem}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExtractError(
            f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    dest.write_bytes(data)
    return dest


def extract_path(path: Path) -> ExtractedDoc:
    if not path.is_file():
        return ExtractedDoc(text="", format="", finding="no_file")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        return ExtractedDoc(text="", format=suffix.lstrip("."), finding="unsupported")
    try:
        if suffix == ".pdf":
            return _from_pdf(path)
        if suffix in {".txt", ".md"}:
            return _from_plain(path, suffix.lstrip("."))
        if suffix in {".html", ".htm"}:
            return _from_html(path)
        if suffix == ".docx":
            return _from_docx(path)
        if suffix == ".odt":
            return _from_odt(path)
        if suffix == ".rtf":
            return _from_rtf(path)
        if suffix == ".pptx":
            return _from_pptx(path)
        if suffix == ".doc":
            return _from_legacy_doc(path)
    except ExtractError:
        if suffix == ".doc":
            raise
        return ExtractedDoc(
            text="",
            format=suffix.lstrip("."),
            finding="empty_extract",
            error="could not parse file",
        )
    except ET.ParseError:
        return ExtractedDoc(
            text="",
            format=suffix.lstrip("."),
            finding="empty_extract",
            error="could not parse file",
        )
    return ExtractedDoc(text="", format=suffix.lstrip("."), finding="unsupported")


def _finish(
    chunks: list[str],
    *,
    fmt: str,
    loc_kind: str,
    pdf_pages: int = 0,
    pdf_words: int = 0,
) -> ExtractedDoc:
    paragraphs = [c.strip() for c in chunks if c and c.strip()]
    text = "\n\n".join(paragraphs)
    alnum = sum(1 for ch in text if ch.isalnum())
    finding = "ok"
    if alnum < MIN_ALNUM:
        finding = "empty_extract" if text.strip() else "empty_extract"
        if fmt == "pdf":
            finding = "needs_ocr"
    pages = paragraphs if loc_kind != "page" else (chunks or paragraphs)
    return ExtractedDoc(
        text=text,
        format=fmt,
        pages=pages,
        paragraphs=paragraphs,
        loc_kind=loc_kind,
        finding=finding,
        pdf_pages=pdf_pages,
        pdf_words=pdf_words,
    )


def _from_pdf(path: Path) -> ExtractedDoc:
    probe = probe_pdf(path)
    text = text_from_pdf(path, max_pages=None)
    # Split on form feed when pdftotext kept pages; else one blob.
    raw_pages = [p for p in text.split("\f")] if "\f" in text else [text]
    pages = [p.strip() for p in raw_pages if p.strip()] or ([text] if text.strip() else [])
    alnum = sum(1 for ch in text if ch.isalnum())
    finding = "ok"
    if alnum < MIN_ALNUM:
        finding = "needs_ocr"
    return ExtractedDoc(
        text="\n\n".join(pages) if pages else text,
        format="pdf",
        pages=pages or ([text] if text else []),
        paragraphs=pages or ([text] if text else []),
        loc_kind="page",
        finding=finding,
        pdf_pages=probe.pages,
        pdf_words=probe.words,
    )


def _from_plain(path: Path, fmt: str) -> ExtractedDoc:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return _finish(paras or ([text] if text.strip() else []), fmt=fmt, loc_kind="paragraph")


def _from_html(path: Path) -> ExtractedDoc:
    from bs4 import BeautifulSoup

    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    paras: list[str] = []
    for node in soup.find_all(["p", "h1", "h2", "h3", "h4", "li", "div"]):
        t = node.get_text(" ", strip=True)
        if t:
            paras.append(t)
    if not paras:
        blob = soup.get_text("\n", strip=True)
        paras = [p.strip() for p in blob.splitlines() if p.strip()]
    return _finish(paras, fmt="html", loc_kind="paragraph")


def _from_docx(path: Path) -> ExtractedDoc:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise ExtractError(f"not a readable .docx: {path.name}") from exc
    root = ET.fromstring(xml)
    paras: list[str] = []
    for p in root.iter(f"{_W_NS}p"):
        bits = [t.text or "" for t in p.iter(f"{_W_NS}t")]
        line = "".join(bits).strip()
        if line:
            paras.append(line)
    return _finish(paras, fmt="docx", loc_kind="paragraph")


def _from_odt(path: Path) -> ExtractedDoc:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("content.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise ExtractError(f"not a readable .odt: {path.name}") from exc
    root = ET.fromstring(xml)
    paras: list[str] = []
    for p in root.iter(f"{_TEXT_NS}p"):
        line = "".join(p.itertext()).strip()
        if line:
            paras.append(line)
    if not paras:
        body = root.find(f"{_OFFICE_NS}body")
        blob = "".join(body.itertext()) if body is not None else "".join(root.itertext())
        paras = [p.strip() for p in blob.splitlines() if p.strip()]
    return _finish(paras, fmt="odt", loc_kind="paragraph")


def _from_rtf(path: Path) -> ExtractedDoc:
    raw = path.read_text(encoding="latin-1", errors="replace")
    # Hex escapes first, then drop control words.
    def _hex(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("\\'"):
            try:
                return bytes.fromhex(token[2:]).decode("latin-1", errors="replace")
            except ValueError:
                return ""
        if token in "{}":
            return ""
        if token.startswith("\\par"):
            return "\n"
        if token.startswith("\\tab"):
            return "\t"
        return " "

    text = _RTF_GROUP.sub(_hex, raw)
    text = re.sub(r"[ \t]+\n", "\n", text)
    paras = [p.strip() for p in re.split(r"\n+", text) if p.strip() and not p.startswith("rtf")]
    return _finish(paras, fmt="rtf", loc_kind="paragraph")


def _from_pptx(path: Path) -> ExtractedDoc:
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ExtractError(f"not a readable .pptx: {path.name}") from exc
    slides: list[str] = []
    names = sorted(
        n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
    )
    with zf:
        for name in names:
            try:
                root = ET.fromstring(zf.read(name))
            except ET.ParseError as exc:
                raise ExtractError(f"not a readable .pptx: {path.name}") from exc
            bits = [t.text or "" for t in root.iter(f"{_A_NS}t")]
            line = "\n".join(b.strip() for b in bits if b.strip())
            slides.append(line)
    return _finish(slides, fmt="pptx", loc_kind="slide")


def _from_legacy_doc(path: Path) -> ExtractedDoc:
    """OLE Word. Optional antiword / catdoc / LibreOffice; else a clear error."""
    for cmd in (
        ["antiword", str(path)],
        ["catdoc", str(path)],
    ):
        exe = shutil.which(cmd[0])
        if not exe:
            continue
        try:
            proc = subprocess.run(
                [exe, *cmd[1:]],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        text = (proc.stdout or b"").decode("utf-8", errors="replace")
        if proc.returncode == 0 and text.strip():
            paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
            return _finish(paras, fmt="doc", loc_kind="paragraph")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            try:
                proc = subprocess.run(
                    [
                        soffice,
                        "--headless",
                        "--convert-to",
                        "txt:Text",
                        "--outdir",
                        str(out),
                        str(path),
                    ],
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ExtractError(
                    "LibreOffice failed converting .doc; save as .docx or .pdf"
                ) from exc
            produced = list(out.glob("*.txt"))
            if proc.returncode == 0 and produced:
                return _from_plain(produced[0], "doc")
    raise ExtractError(
        "Cannot read legacy .doc (OLE). Save as .docx or .pdf, "
        "or install antiword, catdoc, or LibreOffice."
    )


def loc_for(doc: ExtractedDoc, index: int) -> str:
    """Human loc for a 0-based page/paragraph/slide index."""
    n = index + 1
    if doc.loc_kind == "slide":
        return f"slide {n}"
    if doc.loc_kind == "paragraph":
        return f"para {n}"
    return f"p. {n}"


def loc_of_span(doc: ExtractedDoc, span: str) -> str:
    needle = re.sub(r"\s+", " ", (span or "").strip().lower())
    if not needle:
        return ""
    for i, chunk in enumerate(doc.pages or doc.paragraphs):
        hay = re.sub(r"\s+", " ", chunk.lower())
        if needle[:80] in hay or needle in hay:
            return loc_for(doc, i)
    return loc_for(doc, 0) if (doc.pages or doc.paragraphs) else ""
