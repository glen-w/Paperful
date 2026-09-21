"""Extract text and DOIs from PDFs on disk. pdftotext first, then pypdf."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .resolve import DOI_RE, normalize_doi

_PDFTOTEXT = shutil.which("pdftotext")


def pdftotext_available() -> bool:
    return bool(_PDFTOTEXT)


def text_from_pdf(path: Path, *, max_pages: int | None = 2) -> str:
    """Return extracted text. Empty string if nothing could be read.

    ``max_pages=None`` reads the whole document (for summarize).
    """
    if not path.is_file():
        return ""
    text = _pdftotext(path, max_pages)
    if text.strip():
        return text
    return _pypdf_text(path, max_pages)


def doi_from_pdf(path: Path) -> str | None:
    text = text_from_pdf(path)
    if text:
        m = DOI_RE.search(text)
        if m:
            return normalize_doi(m.group(1))
    title = _pypdf_title(path)
    if title:
        return normalize_doi(title)
    return None


def doi_from_pdf_bytes(content: bytes, tmp_dir: Path) -> str | None:
    """Write bytes to tmp_dir and extract. Prefer doi_from_pdf(path) in production."""
    dest = tmp_dir / "probe.pdf"
    dest.write_bytes(content)
    return doi_from_pdf(dest)


def _pdftotext(path: Path, max_pages: int | None) -> str:
    exe = _PDFTOTEXT or shutil.which("pdftotext")
    if not exe:
        return ""
    cmd = [exe, "-f", "1", "-enc", "UTF-8", str(path), "-"]
    if max_pages is not None:
        cmd = [exe, "-f", "1", "-l", str(max_pages), "-enc", "UTF-8", str(path), "-"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or b"").decode("utf-8", errors="replace")


def _pypdf_text(path: Path, max_pages: int | None) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
    except Exception:
        return ""
    chunks: list[str] = []
    pages = reader.pages if max_pages is None else reader.pages[:max_pages]
    for page in pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(chunks)


def _pypdf_title(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        meta = reader.metadata
    except Exception:
        return ""
    if not meta:
        return ""
    return str(getattr(meta, "title", None) or "")
