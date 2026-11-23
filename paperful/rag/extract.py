"""Per-page PDF text for the index, with a cache so re-chunking never re-parses."""

from __future__ import annotations

import hashlib
import logging
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
_LOG = logging.getLogger("paperful.rag.extract")
_LITEPARSE_EXTRA = (
    "liteparse is not installed; pip install 'paperful[rag-liteparse]' "
    'or set [rag].parser = "light"'
)
_TABLE_LAYOUT_REASONS = frozenset({"table-likely", "multi-column"})


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
        proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell, operator-configured tool
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
                return [_strip_placeholders(document.export_to_markdown())]
            return [
                _strip_placeholders(document.export_to_markdown(page_no=n))
                for n in numbers
            ]
        except Exception as exc:
            raise ParseError(f"docling failed: {exc}") from exc


def _strip_placeholders(markdown: str) -> str:
    """Docling / LiteParse mark figures with comments; they are not text to search."""
    return (
        markdown.replace("<!-- image -->", "")
        .replace("![]()", "")
        .replace("![](image)", "")
    )


class GrobidParser:
    """Markdown pages from an operator-owned GROBID sidecar. Needs ``[grobid]``.

    TEI is cached under ``state/grobid/<sha256>.tei.xml``. OCR stays off here:
    scans should get a text layer from OCRmyPDF first.
    """

    name = "grobid"
    version = 1

    def __init__(self, cfg: Config) -> None:
        if not cfg.grobid_enabled:
            raise ParserUnavailable(
                "GROBID parser needs [grobid].enabled = true and a running "
                "server at [grobid].base_url; see docs/grobid.md"
            )
        self.cfg = cfg

    def pages(self, path: Path) -> list[str]:
        from ..grobid_client import GrobidError
        from ..sections.grobid import process_pdf, tei_to_markdown_pages

        if not path.is_file():
            raise ParseError(f"no such file: {path}")
        try:
            tei = process_pdf(self.cfg, path)
        except GrobidError as exc:
            raise ParseError(f"grobid failed: {exc}") from exc
        pages = tei_to_markdown_pages(tei)
        if pages:
            return pages
        raise ParseError("GROBID returned empty TEI")


class LiteParseParser:
    """Markdown pages from LiteParse. Needs ``paperful[rag-liteparse]``.

    OCRmyPDF still rewrites scans in ``out_dir`` first. Parse-time OCR here
    is for embedded images and remaining sparse pages, using Tesseract.
    """

    name = "liteparse"
    version = 1

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def cache_extra(self) -> dict[str, Any]:
        return {}

    def pages(self, path: Path) -> list[str]:
        if not path.is_file():
            raise ParseError(f"no such file: {path}")
        try:
            result = _liteparse_client(
                self.cfg, ocr_enabled=True, target_pages=None
            ).parse(str(path))
        except ParserUnavailable:
            raise
        except Exception as exc:
            raise ParseError(f"liteparse failed: {exc}") from exc
        pages = _liteparse_markdown_pages(result)
        if pages:
            return pages
        raise ParseError("LiteParse returned empty text")


class HybridParser:
    """``light`` pages, with LiteParse markdown spliced onto routed pages."""

    name = "hybrid"
    version = 1

    def __init__(
        self,
        cfg: Config,
        *,
        light: Parser | None = None,
        client_factory: Any | None = None,
    ) -> None:
        self.cfg = cfg
        self._light = light or LightParser()
        self._client_factory = client_factory

    def cache_extra(self) -> dict[str, Any]:
        return {"liteparse_route": self.cfg.rag_liteparse_route}

    def pages(self, path: Path) -> list[str]:
        light_pages = self._light.pages(path)
        try:
            probe = self._client(ocr_enabled=False, target_pages=None)
            complexity = probe.is_complex(str(path))
        except ParserUnavailable:
            raise
        except Exception as exc:
            _LOG.warning("liteparse is_complex failed; keeping light pages: %s", exc)
            return light_pages
        layout_nums, ocr_nums = routed_page_numbers(
            complexity, self.cfg.rag_liteparse_route
        )
        if not layout_nums and not ocr_nums:
            return light_pages
        replacements: dict[int, str] = {}
        if layout_nums:
            replacements.update(
                self._parse_targets(path, layout_nums, ocr_enabled=False)
            )
        if ocr_nums:
            replacements.update(self._parse_targets(path, ocr_nums, ocr_enabled=True))
        out = list(light_pages)
        for index, text in replacements.items():
            if 0 <= index < len(out):
                out[index] = text
        return out

    def _client(self, *, ocr_enabled: bool, target_pages: str | None) -> Any:
        if self._client_factory is not None:
            return self._client_factory(
                ocr_enabled=ocr_enabled, target_pages=target_pages
            )
        return _liteparse_client(
            self.cfg, ocr_enabled=ocr_enabled, target_pages=target_pages
        )

    def _parse_targets(
        self, path: Path, page_numbers: list[int], *, ocr_enabled: bool
    ) -> dict[int, str]:
        target = ",".join(str(n) for n in page_numbers)
        try:
            result = self._client(ocr_enabled=ocr_enabled, target_pages=target).parse(
                str(path)
            )
        except ParserUnavailable:
            raise
        except Exception as exc:
            _LOG.warning(
                "liteparse parse failed for pages %s; keeping light text: %s",
                target,
                exc,
            )
            return {}
        by_index: dict[int, str] = {}
        parsed = list(getattr(result, "pages", None) or [])
        texts = _liteparse_markdown_pages(result)
        if len(parsed) == len(texts) == len(page_numbers) == 1:
            by_index[page_numbers[0] - 1] = texts[0]
            return by_index
        if len(parsed) == len(texts):
            for page, text in zip(parsed, texts):
                number = _page_number(page)
                if number >= 1:
                    by_index[number - 1] = text
            if by_index:
                return by_index
        if len(texts) == len(page_numbers):
            return {n - 1: text for n, text in zip(page_numbers, texts)}
        return by_index


def routed_page_numbers(pages: Any, route: str) -> tuple[list[int], list[int]]:
    """1-based page numbers for layout-only LiteParse vs parse-time OCR.

    Layout reasons live on ``page.layout.reasons`` (object or dict). When the
    binding omits ``layout``, ``tables`` routes nothing; ``ocr`` still uses
    ``needs_ocr``. ``dense-graphics`` is ignored.
    """
    want_tables = route in {"all", "tables"}
    want_ocr = route in {"all", "ocr"}
    layout: list[int] = []
    ocr: list[int] = []
    seen_layout: set[int] = set()
    seen_ocr: set[int] = set()
    for page in pages or []:
        number = _page_number(page)
        if number < 1:
            continue
        needs = bool(getattr(page, "needs_ocr", False))
        table = bool(_layout_reasons(page) & _TABLE_LAYOUT_REASONS)
        if want_ocr and needs:
            if number not in seen_ocr:
                ocr.append(number)
                seen_ocr.add(number)
        elif want_tables and table:
            if number not in seen_layout:
                layout.append(number)
                seen_layout.add(number)
    return layout, ocr


def _liteparse_client(
    cfg: Config, *, ocr_enabled: bool, target_pages: str | None
) -> Any:
    cls = _liteparse_class()
    kwargs: dict[str, Any] = {
        "ocr_enabled": ocr_enabled,
        "ocr_language": _ocr_language(cfg),
        "output_format": "markdown",
        "quiet": True,
    }
    if target_pages:
        kwargs["target_pages"] = target_pages
    try:
        return cls(image_mode="off", **kwargs)
    except TypeError:
        return cls(**kwargs)


def _liteparse_class() -> Any:
    try:
        from liteparse import LiteParse
    except ImportError as exc:
        raise ParserUnavailable(_LITEPARSE_EXTRA) from exc
    return LiteParse


def _ocr_language(cfg: Config) -> str:
    raw = (cfg.ocr_languages or "eng").replace("+", " ").split()
    return raw[0] if raw else "eng"


def _page_number(page: Any) -> int:
    value = getattr(page, "page_number", None)
    if value is None:
        value = getattr(page, "page_num", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _layout_reasons(page: Any) -> set[str]:
    layout = getattr(page, "layout", None)
    if layout is None:
        return set()
    if isinstance(layout, dict):
        reasons = layout.get("reasons") or []
    else:
        reasons = getattr(layout, "reasons", None) or []
    return {str(item) for item in reasons}


def _liteparse_markdown_pages(result: Any) -> list[str]:
    pages = list(getattr(result, "pages", None) or [])
    full = _strip_placeholders(str(getattr(result, "text", "") or ""))
    if not pages:
        return [full] if full.strip() else []
    out: list[str] = []
    for page in pages:
        markdown = getattr(page, "markdown", None)
        text = getattr(page, "text", None)
        chosen = markdown if markdown not in (None, "") else text
        out.append(_strip_placeholders(str(chosen or "")))
    if len(pages) == 1 and full.strip() and len(full) >= len(out[0]):
        return [full]
    if full.strip() and all(not page.strip() for page in out):
        return [full]
    return out


def get_parser(cfg: Config) -> Parser:
    if cfg.rag_parser == "docling":
        return DoclingParser()
    if cfg.rag_parser == "grobid":
        return GrobidParser(cfg)
    if cfg.rag_parser == "liteparse":
        return LiteParseParser(cfg)
    if cfg.rag_parser == "hybrid":
        return HybridParser(cfg)
    return LightParser()


def text_cache_path(cfg: Config, key: str) -> Path:
    return cfg.rag_dir / "text" / f"{key}.json"


def cached_pages(
    cfg: Config, key: str, path: Path, sha256: str, parser: Parser
) -> list[str]:
    """Pages of ``path``, parsed once per file content and parser version."""
    cache = text_cache_path(cfg, key)
    stored = load_json(cache)
    extra = _cache_extra(parser)
    if (
        stored is not None
        and stored.get("schema") == TEXT_SCHEMA
        and stored.get("sha256") == sha256
        and stored.get("parser") == parser.name
        and stored.get("parser_version") == parser.version
        and isinstance(stored.get("pages"), list)
        and all(stored.get(k) == v for k, v in extra.items())
    ):
        return [str(page) for page in stored["pages"]]
    pages = parser.pages(path)
    payload: dict[str, Any] = {
        "schema": TEXT_SCHEMA,
        "key": key,
        "sha256": sha256,
        "parser": parser.name,
        "parser_version": parser.version,
        "pages": pages,
    }
    payload.update(extra)
    write_json(cache, payload)
    return pages


def _cache_extra(parser: Parser) -> dict[str, Any]:
    extra = getattr(parser, "cache_extra", None)
    if extra is None:
        return {}
    if callable(extra):
        extra = extra()
    return dict(extra) if extra else {}
