"""PDF DOI extraction: pdftotext first, pypdf fallback."""

from __future__ import annotations

from pathlib import Path

from paperful import pdfid
from paperful.pdfid import (
    doi_from_pdf,
    page_count,
    probe_pdf,
    short_pdf_verdict,
    text_from_pdf,
    word_count,
)


def _pdf_with_title(path: Path, title: str) -> Path:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.add_metadata({"/Title": title})
    w.write(path)
    return path


def _blank_pages(path: Path, n: int) -> Path:
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(n):
        w.add_blank_page(width=72, height=72)
    w.write(path)
    return path


def test_doi_from_pypdf_title_when_pdftotext_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pdfid, "_PDFTOTEXT", None)
    monkeypatch.setattr(pdfid.shutil, "which", lambda name: None)
    path = _pdf_with_title(tmp_path / "a.pdf", "doi:10.1000/from-title")
    assert doi_from_pdf(path) == "10.1000/from-title"


def test_pdftotext_preferred(tmp_path, monkeypatch):
    path = _pdf_with_title(tmp_path / "b.pdf", "doi:10.1000/from-title")

    class Proc:
        returncode = 0
        stdout = b"See DOI 10.5555/from-text in the header"

    monkeypatch.setattr(pdfid, "_PDFTOTEXT", "/usr/bin/pdftotext")
    monkeypatch.setattr(pdfid.subprocess, "run", lambda *a, **k: Proc())
    assert doi_from_pdf(path) == "10.5555/from-text"
    assert "10.5555/from-text" in text_from_pdf(path)


def test_missing_file():
    assert doi_from_pdf(Path("/no/such.pdf")) is None


def test_corrupt_pdf_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(pdfid, "_PDFTOTEXT", None)
    monkeypatch.setattr(pdfid.shutil, "which", lambda name: None)
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.4\n<< /Type /Catalog /Pages 2 0 R >>\n%%EOF\n")
    assert text_from_pdf(path) == ""
    assert doi_from_pdf(path) is None


def test_doi_from_pdf_bytes(tmp_path, monkeypatch):
    from paperful.pdfid import doi_from_pdf_bytes

    monkeypatch.setattr(pdfid, "_PDFTOTEXT", None)
    monkeypatch.setattr(pdfid.shutil, "which", lambda name: None)
    path = _pdf_with_title(tmp_path / "c.pdf", "doi:10.1000/from-bytes")
    assert doi_from_pdf_bytes(path.read_bytes(), tmp_path) == "10.1000/from-bytes"


def test_word_count_splits_whitespace():
    assert word_count("  one two\nthree  ") == 3
    assert word_count("") == 0


def test_short_pdf_verdict_table():
    assert short_pdf_verdict(0, 0, min_words=200) == "ok"
    assert short_pdf_verdict(2, 10, min_words=200) == "ok"
    assert short_pdf_verdict(1, 50, min_words=200) == "sparse_short"
    assert short_pdf_verdict(1, 200, min_words=200) == "dense_short"
    assert short_pdf_verdict(1, 500, min_words=200) == "dense_short"


def test_probe_blank_one_page_is_sparse(tmp_path, monkeypatch):
    monkeypatch.setattr(pdfid, "_PDFTOTEXT", None)
    monkeypatch.setattr(pdfid.shutil, "which", lambda name: None)
    path = _blank_pages(tmp_path / "one.pdf", 1)
    probe = probe_pdf(path)
    assert probe.pages == 1
    assert probe.words == 0
    assert short_pdf_verdict(probe.pages, probe.words, min_words=200) == "sparse_short"


def test_probe_two_pages_is_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(pdfid, "_PDFTOTEXT", None)
    monkeypatch.setattr(pdfid.shutil, "which", lambda name: None)
    path = _blank_pages(tmp_path / "two.pdf", 2)
    assert page_count(path) == 2
    probe = probe_pdf(path)
    assert short_pdf_verdict(probe.pages, probe.words, min_words=200) == "ok"


def test_opaque_bytes_probe_stays_ok():
    from paperful.pdfid import probe_pdf_bytes

    junk = b"%PDF-1.4\n" + b"x" * 5000 + b"\n%%EOF"
    probe = probe_pdf_bytes(junk)
    assert probe.pages == 0
    assert short_pdf_verdict(probe.pages, probe.words, min_words=200) == "ok"
