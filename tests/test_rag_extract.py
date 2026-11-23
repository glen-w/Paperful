"""Per-page extraction, the OCR decision, and the text cache (offline)."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

import paperful.rag.extract as extract
from paperful.rag.extract import (
    DoclingParser,
    HybridParser,
    LightParser,
    LiteParseParser,
    ParseError,
    ParserUnavailable,
    cached_pages,
    file_sha256,
    get_parser,
    needs_ocr,
    routed_page_numbers,
    text_cache_path,
    _liteparse_client,
    _liteparse_markdown_pages,
    _ocr_language,
    _page_number,
)
from paperful.store import load_json

BODY = "word " * 40  # 160 non-space characters


def _blank_pdf(path: Path, pages: int = 1) -> Path:
    from pypdf import PdfWriter

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    writer.write(path)
    return path


def _fake_pdftotext(monkeypatch, stdout: bytes, returncode: int = 0):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=b"")

    monkeypatch.setattr(extract.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(extract.subprocess, "run", run)
    return calls


# ---- needs_ocr ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("pages", "verdict"),
    [
        ([], "no text"),
        (["", "  \n "], "no text"),
        (["12", "Page 3 of 9"], "no text"),
        ([BODY, BODY, BODY], None),
        # A figure-only cover in front of a born-digital paper: 3 of 4 pages have text.
        (["", BODY, BODY, BODY], None),
        # A typed cover in front of a scan: 1 of 4.
        ([BODY, "", "", ""], "partial text"),
        ([BODY, BODY, "", "", ""], "partial text"),
        ([BODY, BODY, BODY, "", ""], None),
    ],
)
def test_needs_ocr(pages, verdict):
    assert needs_ocr(pages) == verdict


def test_needs_ocr_ignores_whitespace_padding():
    spaced = "a " * 79  # 79 letters, 158 characters
    assert needs_ocr([spaced]) == "no text"
    assert needs_ocr([spaced + "b"]) is None


# ---- LightParser -------------------------------------------------------------


def test_light_parser_splits_on_form_feeds(tmp_path, monkeypatch):
    pdf = _blank_pdf(tmp_path / "a.pdf", pages=3)
    calls = _fake_pdftotext(monkeypatch, b"one\x0ctwo\n\x0c\x0c")
    assert LightParser().pages(pdf) == ["one", "two\n", ""]
    assert calls[0][-2:] == [str(pdf), "-"]


def test_light_parser_falls_back_to_pypdf_and_keeps_the_page_count(
    tmp_path, monkeypatch
):
    pdf = _blank_pdf(tmp_path / "scan.pdf", pages=4)
    _fake_pdftotext(monkeypatch, b"", returncode=1)
    pages = LightParser().pages(pdf)
    assert pages == ["", "", "", ""]
    assert needs_ocr(pages) == "no text"


def test_light_parser_without_pdftotext(tmp_path, monkeypatch):
    pdf = _blank_pdf(tmp_path / "scan.pdf", pages=2)
    monkeypatch.setattr(extract.shutil, "which", lambda name: None)
    assert LightParser().pages(pdf) == ["", ""]


def test_light_parser_rejects_unreadable_files(tmp_path, monkeypatch):
    monkeypatch.setattr(extract.shutil, "which", lambda name: None)
    with pytest.raises(ParseError, match="no such file"):
        LightParser().pages(tmp_path / "missing.pdf")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(ParseError, match="could not be opened"):
        LightParser().pages(broken)


def test_light_parser_survives_a_pdftotext_timeout(tmp_path, monkeypatch):
    pdf = _blank_pdf(tmp_path / "slow.pdf")

    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(extract.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(extract.subprocess, "run", run)
    assert LightParser().pages(pdf) == [""]


# ---- parser choice -----------------------------------------------------------


def test_get_parser_follows_config(cfg):
    assert get_parser(cfg).name == "light"
    cfg.rag_parser = "docling"
    assert get_parser(cfg).name == "docling"
    cfg.rag_parser = "grobid"
    cfg.grobid_enabled = True
    assert get_parser(cfg).name == "grobid"
    cfg.rag_parser = "liteparse"
    assert get_parser(cfg).name == "liteparse"
    cfg.rag_parser = "hybrid"
    assert get_parser(cfg).name == "hybrid"


def test_docling_parser_names_the_extra_when_missing(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "docling", None)
    with pytest.raises(ParserUnavailable, match=r"paperful\[rag-docling\]"):
        DoclingParser().pages(_blank_pdf(tmp_path / "a.pdf"))


def test_docling_figure_placeholders_are_dropped():
    from paperful.rag.extract import _strip_placeholders

    assert _strip_placeholders("<!-- image -->\n\nBody text.") == "\n\nBody text."


# ---- cache -------------------------------------------------------------------


class _CountingParser:
    name = "light"
    version = 1

    def __init__(self):
        self.calls = 0

    def pages(self, path):
        self.calls += 1
        return ["page one", "page two"]


def test_cached_pages_parses_once_per_content(cfg, tmp_path):
    pdf = _blank_pdf(tmp_path / "a.pdf")
    parser = _CountingParser()
    sha = file_sha256(pdf)
    assert cached_pages(cfg, "KEY1", pdf, sha, parser) == ["page one", "page two"]
    assert cached_pages(cfg, "KEY1", pdf, sha, parser) == ["page one", "page two"]
    assert parser.calls == 1
    stored = load_json(text_cache_path(cfg, "KEY1"))
    assert stored["sha256"] == sha and stored["parser"] == "light"
    assert text_cache_path(cfg, "KEY1") == cfg.state_dir / "rag" / "text" / "KEY1.json"


def test_cached_pages_reparses_on_new_content_or_parser(cfg, tmp_path):
    pdf = _blank_pdf(tmp_path / "a.pdf")
    parser = _CountingParser()
    cached_pages(cfg, "KEY1", pdf, "sha-a", parser)
    cached_pages(cfg, "KEY1", pdf, "sha-b", parser)
    assert parser.calls == 2
    parser.version = 2
    cached_pages(cfg, "KEY1", pdf, "sha-b", parser)
    assert parser.calls == 3
    other = types.SimpleNamespace(name="docling", version=2, pages=lambda path: ["md"])
    assert cached_pages(cfg, "KEY1", pdf, "sha-b", other) == ["md"]


def test_cached_pages_reparses_when_liteparse_route_changes(cfg, tmp_path):
    pdf = _blank_pdf(tmp_path / "a.pdf")

    class _Hybrid:
        name = "hybrid"
        version = 1

        def __init__(self, route):
            self._route = route
            self.calls = 0

        def cache_extra(self):
            return {"liteparse_route": self._route}

        def pages(self, path):
            self.calls += 1
            return [self._route]

    first = _Hybrid("all")
    cached_pages(cfg, "KEY1", pdf, "sha", first)
    second = _Hybrid("tables")
    cached_pages(cfg, "KEY1", pdf, "sha", second)
    assert first.calls == 1 and second.calls == 1
    stored = load_json(text_cache_path(cfg, "KEY1"))
    assert stored["liteparse_route"] == "tables"


def _complex_page(number, *, needs_ocr=False, reasons=()):
    return types.SimpleNamespace(
        page_number=number,
        needs_ocr=needs_ocr,
        layout=types.SimpleNamespace(reasons=list(reasons)),
    )


def test_routed_page_numbers_splits_tables_and_ocr():
    pages = [
        _complex_page(1, reasons=("table-likely",)),
        _complex_page(2, needs_ocr=True, reasons=("scanned",)),
        _complex_page(3, reasons=("multi-column",)),
        _complex_page(4, reasons=("dense-graphics",)),
    ]
    layout, ocr = routed_page_numbers(pages, "all")
    assert layout == [1, 3] and ocr == [2]
    layout, ocr = routed_page_numbers(pages, "tables")
    assert layout == [1, 3] and ocr == []
    layout, ocr = routed_page_numbers(pages, "ocr")
    assert layout == [] and ocr == [2]


def test_routed_page_numbers_accepts_dict_layout_and_omitted_layout():
    dict_page = types.SimpleNamespace(
        page_number=1,
        needs_ocr=False,
        layout={"reasons": ["table-likely"]},
    )
    bare = types.SimpleNamespace(page_number=2, needs_ocr=True)
    layout, ocr = routed_page_numbers([dict_page, bare], "all")
    assert layout == [1] and ocr == [2]
    layout, ocr = routed_page_numbers([bare], "tables")
    assert layout == [] and ocr == []


def test_liteparse_parser_names_the_extra_when_missing(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "liteparse", None)
    cfg = types.SimpleNamespace(ocr_languages="eng")
    with pytest.raises(ParserUnavailable, match=r"paperful\[rag-liteparse\]"):
        LiteParseParser(cfg).pages(_blank_pdf(tmp_path / "a.pdf"))


def test_hybrid_replaces_only_routed_pages(cfg, tmp_path):
    pdf = _blank_pdf(tmp_path / "a.pdf", pages=3)
    light = types.SimpleNamespace(
        name="light",
        version=1,
        pages=lambda path: ["L1", "L2", "L3"],
    )

    class _Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def is_complex(self, path):
            return [
                _complex_page(1, reasons=("table-likely",)),
                _complex_page(2),
                _complex_page(3, needs_ocr=True),
            ]

        def parse(self, path):
            targets = self.kwargs.get("target_pages") or ""
            pages = []
            for part in targets.split(","):
                n = int(part)
                pages.append(
                    types.SimpleNamespace(
                        page_num=n,
                        text=f"MD{n}",
                        markdown=f"MD{n}",
                    )
                )
            return types.SimpleNamespace(pages=pages, text="")

    parser = HybridParser(cfg, light=light, client_factory=_Client)
    cfg.rag_liteparse_route = "all"
    assert parser.pages(pdf) == ["MD1", "L2", "MD3"]
    parser_tables = HybridParser(cfg, light=light, client_factory=_Client)
    cfg.rag_liteparse_route = "tables"
    assert parser_tables.pages(pdf) == ["MD1", "L2", "L3"]


def test_liteparse_parser_uses_markdown_pages(cfg, monkeypatch, tmp_path):
    pdf = _blank_pdf(tmp_path / "a.pdf", pages=2)

    class _Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def parse(self, path):
            return types.SimpleNamespace(
                text="# A\n\n# B",
                pages=[
                    types.SimpleNamespace(page_num=1, text="A", markdown="# A"),
                    types.SimpleNamespace(page_num=2, text="B", markdown="# B"),
                ],
            )

    monkeypatch.setattr(
        "paperful.rag.extract._liteparse_client",
        lambda cfg, **kwargs: _Client(**kwargs),
    )
    pages = LiteParseParser(cfg).pages(pdf)
    assert pages == ["# A", "# B"]


def test_hybrid_names_the_extra_when_missing(cfg, tmp_path, monkeypatch):
    pdf = _blank_pdf(tmp_path / "a.pdf")
    monkeypatch.setitem(sys.modules, "liteparse", None)
    light = types.SimpleNamespace(pages=lambda path: ["keep"])
    with pytest.raises(ParserUnavailable, match=r"paperful\[rag-liteparse\]"):
        HybridParser(cfg, light=light).pages(pdf)


def test_hybrid_keeps_light_when_target_parse_fails(cfg, tmp_path):
    pdf = _blank_pdf(tmp_path / "a.pdf", pages=2)
    light = types.SimpleNamespace(pages=lambda path: ["L1", "L2"])

    class _Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def is_complex(self, path):
            return [_complex_page(1, reasons=("table-likely",)), _complex_page(2)]

        def parse(self, path):
            raise RuntimeError("parse down")

    assert HybridParser(cfg, light=light, client_factory=_Client).pages(pdf) == [
        "L1",
        "L2",
    ]


def test_hybrid_splices_multiple_layout_pages_by_page_num(cfg, tmp_path):
    pdf = _blank_pdf(tmp_path / "a.pdf", pages=3)
    light = types.SimpleNamespace(pages=lambda path: ["L1", "L2", "L3"])

    class _Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def is_complex(self, path):
            return [
                _complex_page(1, reasons=("table-likely",)),
                _complex_page(2, reasons=("multi-column",)),
                _complex_page(3),
            ]

        def parse(self, path):
            return types.SimpleNamespace(
                text="",
                pages=[
                    types.SimpleNamespace(page_num=2, markdown="MD2"),
                    types.SimpleNamespace(page_num=1, markdown="MD1"),
                ],
            )

    assert HybridParser(cfg, light=light, client_factory=_Client).pages(pdf) == [
        "MD1",
        "MD2",
        "L3",
    ]


def test_hybrid_aligns_texts_to_targets_when_pages_lack_numbers(cfg, tmp_path):
    pdf = _blank_pdf(tmp_path / "a.pdf", pages=2)
    light = types.SimpleNamespace(pages=lambda path: ["L1", "L2"])

    class _Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def is_complex(self, path):
            return [
                _complex_page(1, reasons=("table-likely",)),
                _complex_page(2, reasons=("multi-column",)),
            ]

        def parse(self, path):
            return types.SimpleNamespace(
                text="",
                pages=[
                    types.SimpleNamespace(markdown="MD1"),
                    types.SimpleNamespace(markdown="MD2"),
                ],
            )

    assert HybridParser(cfg, light=light, client_factory=_Client).pages(pdf) == [
        "MD1",
        "MD2",
    ]


def test_liteparse_client_drops_image_mode_when_unsupported(cfg, monkeypatch):
    seen = []

    class _Cls:
        def __init__(self, **kwargs):
            if "image_mode" in kwargs:
                raise TypeError("no image_mode")
            seen.append(kwargs)

    monkeypatch.setattr("paperful.rag.extract._liteparse_class", lambda: _Cls)
    client = _liteparse_client(cfg, ocr_enabled=False, target_pages="1,3")
    assert isinstance(client, _Cls)
    assert seen[0]["target_pages"] == "1,3"
    assert "image_mode" not in seen[0]


def test_liteparse_markdown_helpers():
    assert _ocr_language(types.SimpleNamespace(ocr_languages="")) == "eng"
    assert _ocr_language(types.SimpleNamespace(ocr_languages="fra+eng")) == "fra"
    assert _page_number(types.SimpleNamespace(page_number="x")) == 0
    assert _liteparse_markdown_pages(types.SimpleNamespace(text="  ", pages=None)) == []
    one = types.SimpleNamespace(
        text="# Full table\n| a | b |",
        pages=[types.SimpleNamespace(text="a")],
    )
    assert _liteparse_markdown_pages(one) == ["# Full table\n| a | b |"]
    empty_cells = types.SimpleNamespace(
        text="DOC",
        pages=[types.SimpleNamespace(text=""), types.SimpleNamespace(markdown="")],
    )
    assert _liteparse_markdown_pages(empty_cells) == ["DOC"]


def test_hybrid_keeps_light_pages_when_is_complex_fails(cfg, tmp_path):
    pdf = _blank_pdf(tmp_path / "a.pdf")
    light = types.SimpleNamespace(pages=lambda path: ["keep"])

    class _Boom:
        def __init__(self, **kwargs):
            pass

        def is_complex(self, path):
            raise RuntimeError("probe down")

    parser = HybridParser(cfg, light=light, client_factory=_Boom)
    assert parser.pages(pdf) == ["keep"]


def test_file_sha256_matches_hashlib(tmp_path):
    import hashlib

    path = tmp_path / "blob"
    path.write_bytes(b"abc" * 500_000)
    assert file_sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()
