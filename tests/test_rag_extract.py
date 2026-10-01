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
    LightParser,
    ParseError,
    ParserUnavailable,
    cached_pages,
    file_sha256,
    get_parser,
    needs_ocr,
    text_cache_path,
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


def test_light_parser_falls_back_to_pypdf_and_keeps_the_page_count(tmp_path, monkeypatch):
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


def test_file_sha256_matches_hashlib(tmp_path):
    import hashlib

    path = tmp_path / "blob"
    path.write_bytes(b"abc" * 500_000)
    assert file_sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()
