"""PDF DOI extraction: pdftotext first, pypdf fallback."""

from __future__ import annotations

from pathlib import Path

from paperful import pdfid
from paperful.pdfid import doi_from_pdf, text_from_pdf


def _pdf_with_title(path: Path, title: str) -> Path:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.add_metadata({"/Title": title})
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


def test_doi_from_pdf_bytes(tmp_path, monkeypatch):
    from paperful.pdfid import doi_from_pdf_bytes

    monkeypatch.setattr(pdfid, "_PDFTOTEXT", None)
    monkeypatch.setattr(pdfid.shutil, "which", lambda name: None)
    path = _pdf_with_title(tmp_path / "c.pdf", "doi:10.1000/from-bytes")
    assert doi_from_pdf_bytes(path.read_bytes(), tmp_path) == "10.1000/from-bytes"
