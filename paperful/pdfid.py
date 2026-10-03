"""Extract text and DOIs from PDFs on disk. pdftotext first, then pypdf."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .resolve import DOI_RE, normalize_doi

_PDFTOTEXT = shutil.which("pdftotext")

ShortPdfVerdict = Literal["ok", "sparse_short", "dense_short"]


@dataclass(frozen=True)
class PdfProbe:
    """Page count and first-page word count for short-PDF gating."""

    pages: int
    words: int


def pdftotext_available() -> bool:
    return bool(_PDFTOTEXT)


def word_count(text: str) -> int:
    return len(text.split())


def page_count(path: Path) -> int:
    """Return page count, or ``0`` when the PDF cannot be opened."""
    if not path.is_file():
        return 0
    try:
        from pypdf import PdfReader
    except ImportError:
        return 0
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return 0


def probe_pdf(path: Path) -> PdfProbe:
    pages = page_count(path)
    if pages < 1:
        return PdfProbe(pages=0, words=0)
    text = text_from_pdf(path, max_pages=1)
    return PdfProbe(pages=pages, words=word_count(text))


def probe_pdf_bytes(content: bytes) -> PdfProbe:
    """Write ``content`` to a temp file and probe it."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
        fh.write(content)
        dest = Path(fh.name)
    try:
        return probe_pdf(dest)
    finally:
        dest.unlink(missing_ok=True)


def short_pdf_verdict(
    pages: int, words: int, *, min_words: int
) -> ShortPdfVerdict:
    """Classify a PDF for the one-page density gate.

    Unreadable PDFs (``pages < 1``) stay ``ok`` so opaque but otherwise-valid
    downloads are not rejected. One-page sparse stubs soft-reject; denser
    one-pagers go to the admit lane.
    """
    if pages < 1 or pages >= 2:
        return "ok"
    if words < min_words:
        return "sparse_short"
    return "dense_short"


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
        # A damaged page tree raises here, on the first look at the pages.
        pages = list(reader.pages) if max_pages is None else reader.pages[:max_pages]
    except Exception:
        return ""
    chunks: list[str] = []
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
