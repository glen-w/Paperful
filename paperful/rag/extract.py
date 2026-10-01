"""Per-page PDF text for the index, with a cache so re-chunking never re-parses."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Protocol

from ..config import Config
from ..store import load_json, write_json

TEXT_SCHEMA = "paperful.rag.text.v1"
# A page has a text layer once it yields this many non-space characters.
# Below that, a page number or a watermark is all there is.
MIN_CHARS_PER_PAGE = 80
# OCR only when fewer than this share of pages has text. A born-digital paper
# with a figure-only cover is left alone; a scan behind a typed cover is not.
MIN_TEXT_PAGE_FRACTION = 0.6
# Whole-document extraction. Typical papers take well under a second.
_PDFTOTEXT_TIMEOUT_S = 180.0


class ParseError(Exception):
    """The PDF could not be read by the configured parser."""


class ParserUnavailable(ParseError):
    """The configured parser needs a package that is not installed."""


class Parser(Protocol):
    name: str
    version: int

    def pages(self, path: Path) -> list[str]: ...


def needs_ocr(pages: list[str]) -> str | None:
    """``no text`` or ``partial text`` when OCR should run. None when the layer is enough."""
    if not pages:
        return "no text"
    with_text = sum(
        1 for page in pages if len("".join(page.split())) >= MIN_CHARS_PER_PAGE
    )
    if with_text == 0:
        return "no text"
    if with_text / len(pages) < MIN_TEXT_PAGE_FRACTION:
        return "partial text"
    return None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class LightParser:
    """pdftotext for the whole file, split on form feeds. pypdf when that yields nothing."""

    name = "light"
    version = 1

    def pages(self, path: Path) -> list[str]:
        if not path.is_file():
            raise ParseError(f"no such file: {path}")
        pages = _pdftotext_pages(path)
        if any(page.strip() for page in pages):
            return pages
        fallback = _pypdf_pages(path)
        if fallback is None:
            if pages:
                return pages
            raise ParseError("PDF could not be opened")
        # Keep whichever saw more pages, so an all-image file still counts its pages.
        return fallback if len(fallback) >= len(pages) else pages


def _pdftotext_pages(path: Path) -> list[str]:
    exe = shutil.which("pdftotext")
    if not exe:
        return []
    try:
        proc = subprocess.run(
            [exe, "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            timeout=_PDFTOTEXT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    parts = (proc.stdout or b"").decode("utf-8", errors="replace").split("\f")
    # pdftotext ends every page with a form feed, the last one included.
    if parts and not parts[-1].strip():
        parts.pop()
    return parts


def _pypdf_pages(path: Path) -> list[str] | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        count = len(reader.pages)
    except Exception:
        return None
    pages: list[str] = []
    for index in range(count):
        try:
            pages.append(reader.pages[index].extract_text() or "")
        except Exception:
            pages.append("")
    return pages


class DoclingParser:
    """Layout-aware markdown per page. Needs ``paperful[rag-docling]``.

    OCR stays off here: scans get their text layer from OCRmyPDF first, so
    docling only ever sees files that already have one.
    """

    name = "docling"
    version = 1

    def __init__(self) -> None:
        self._converter: Any = None

    def _load(self) -> Any:
        if self._converter is not None:
            return self._converter
        try:
            from docling.datamodel.accelerator_options import (
                AcceleratorDevice,
                AcceleratorOptions,
            )
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:
            raise ParserUnavailable(
                "docling is not installed; pip install 'paperful[rag-docling]' "
                'or set [rag].parser = "light"'
            ) from exc
        options = PdfPipelineOptions()
        options.do_ocr = False
        # The layout model uses float64 position embeddings, which Apple's MPS
        # backend does not support; auto-detect would pick MPS and crash.
        options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)
        self._converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        return self._converter

    def pages(self, path: Path) -> list[str]:
        converter = self._load()
        try:
            document = converter.convert(path).document
            numbers = sorted(document.pages)
            if not numbers:
                return [document.export_to_markdown()]
            return [document.export_to_markdown(page_no=n) for n in numbers]
        except Exception as exc:
            raise ParseError(f"docling failed: {exc}") from exc


def get_parser(cfg: Config) -> Parser:
    if cfg.rag_parser == "docling":
        return DoclingParser()
    return LightParser()


def text_cache_path(cfg: Config, key: str) -> Path:
    return cfg.rag_dir / "text" / f"{key}.json"


def cached_pages(
    cfg: Config, key: str, path: Path, sha256: str, parser: Parser
) -> list[str]:
    """Pages of ``path``, parsed once per file content and parser version."""
    cache = text_cache_path(cfg, key)
    stored = load_json(cache)
    if (
        stored is not None
        and stored.get("schema") == TEXT_SCHEMA
        and stored.get("sha256") == sha256
        and stored.get("parser") == parser.name
        and stored.get("parser_version") == parser.version
        and isinstance(stored.get("pages"), list)
    ):
        return [str(page) for page in stored["pages"]]
    pages = parser.pages(path)
    write_json(
        cache,
        {
            "schema": TEXT_SCHEMA,
            "key": key,
            "sha256": sha256,
            "parser": parser.name,
            "parser_version": parser.version,
            "pages": pages,
        },
    )
    return pages
