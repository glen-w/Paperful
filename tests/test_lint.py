"""Lint findings against mocked HTTP; no Zotero."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from paperful.lint import lint_item
from paperful.metadata import propose_patch
from tests.conftest import make_item, mock_client


def _json(payload, status=200):
    return httpx.Response(
        status,
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )


def test_lint_swappable_doi(cfg):
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        host = req.url.host or ""
        path = req.url.path
        if "crossref.org" in host and "/works/" in path and not path.endswith("/works"):
            return _json(
                {
                    "message": {
                        "DOI": "10.1/wrong",
                        "title": ["Unrelated"],
                        "issued": {"date-parts": [[2010]]},
                    }
                }
            )
        if "crossref.org" in host:
            return _json(
                {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.9/right",
                                "title": [title],
                                "issued": {"date-parts": [[2019]]},
                            }
                        ]
                    }
                }
            )
        return httpx.Response(404)

    item = make_item(doi="10.1/wrong", title=title, url=None)
    findings = lint_item(mock_client(handler), cfg, item)
    assert any(f.code == "swappable_doi" for f in findings)


def test_lint_no_identifier(cfg):
    item = make_item(doi=None, url=None, arxiv_id=None, title="Short")
    findings = lint_item(mock_client(lambda r: httpx.Response(500)), cfg, item)
    codes = {f.code for f in findings}
    assert "no_identifier" in codes


def test_propose_patch_sets_doi_on_swap(cfg):
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        host = req.url.host or ""
        path = req.url.path
        if "crossref.org" in host and "/works/" in path and not path.endswith("/works"):
            doi = path.rsplit("/", 1)[-1]
            if doi.startswith("10.9"):
                return _json(
                    {
                        "message": {
                            "DOI": "10.9/right",
                            "title": [title],
                            "issued": {"date-parts": [[2019]]},
                            "container-title": ["Marine Policy"],
                        }
                    }
                )
            return _json(
                {
                    "message": {
                        "DOI": "10.1/wrong",
                        "title": ["Unrelated"],
                        "issued": {"date-parts": [[2010]]},
                    }
                }
            )
        if "crossref.org" in host:
            return _json(
                {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.9/right",
                                "title": [title],
                                "issued": {"date-parts": [[2019]]},
                            }
                        ]
                    }
                }
            )
        return httpx.Response(404)

    item = make_item(
        doi="10.1/wrong", title=title, url=None, publication_title=None, date=None
    )
    client = mock_client(handler)
    findings = lint_item(client, cfg, item)
    patch = propose_patch(client, cfg, item, findings)
    assert patch is not None
    assert patch.after.get("doi") == "10.9/right"


def test_pdf_doi_mismatch_uses_disk_not_export(cfg, tmp_path, monkeypatch):
    from pypdf import PdfWriter

    pdf = tmp_path / "item.pdf"
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.add_metadata({"/Title": "doi:10.5555/pdf-only"})
    w.write(pdf)
    monkeypatch.setattr("paperful.pdfid._PDFTOTEXT", None)
    monkeypatch.setattr("paperful.pdfid.shutil.which", lambda name: None)
    item = make_item(doi="10.1000/test.doi", pdf_path=str(pdf), has_pdf=True)

    class Boom:
        def export_pdf(self, *a, **k):
            raise AssertionError("export_pdf should not run when the file is on disk")

    findings = lint_item(
        mock_client(lambda r: httpx.Response(500)),
        cfg,
        item,
        backend=Boom(),
    )
    assert any(
        f.code == "pdf_doi_mismatch" and f.pdf_doi == "10.5555/pdf-only"
        for f in findings
    )


def test_pmid_no_doi(cfg):
    item = make_item(
        doi=None,
        url=None,
        pmid="123",
        title="A sufficiently long test title about marine governance",
    )

    def handler(req):
        if "idconv" in str(req.url):
            return _json({"records": [{}]})
        return _json({"message": {"items": []}})

    findings = lint_item(mock_client(handler), cfg, item)
    assert any(f.code == "pmid_no_doi" for f in findings)


def test_lint_suspect_doi_no_swap(cfg):
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        host = req.url.host or ""
        path = req.url.path
        if "crossref.org" in host and "/works/" in path and not path.endswith("/works"):
            return _json(
                {
                    "message": {
                        "DOI": "10.1/wrong",
                        "title": ["Totally different"],
                        "issued": {"date-parts": [[2010]]},
                    }
                }
            )
        return _json({"message": {"items": []}})

    item = make_item(doi="10.1/wrong", title=title, url=None)
    findings = lint_item(mock_client(handler), cfg, item)
    assert any(f.code == "suspect_doi" for f in findings)
    assert not any(f.code == "swappable_doi" for f in findings)


def test_lint_exports_pdf_when_not_on_disk(cfg, tmp_path, monkeypatch):
    from pypdf import PdfWriter

    monkeypatch.setattr("paperful.pdfid._PDFTOTEXT", None)
    monkeypatch.setattr("paperful.pdfid.shutil.which", lambda name: None)

    class Backend:
        def export_pdf(self, item, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            w = PdfWriter()
            w.add_blank_page(width=72, height=72)
            w.add_metadata({"/Title": "doi:10.5555/exported"})
            w.write(dest)
            return dest

    item = make_item(doi="10.1000/test.doi", has_pdf=True, pdf_path=None)
    findings = lint_item(
        mock_client(lambda r: httpx.Response(500)),
        cfg,
        item,
        backend=Backend(),
    )
    assert any(
        f.code == "pdf_doi_mismatch" and f.pdf_doi == "10.5555/exported"
        for f in findings
    )
    assert item.pdf_path and Path(item.pdf_path).is_file()


def test_apply_patches_calls_backend():
    from paperful.metadata import Patch, apply_patches

    class Backend:
        def __init__(self):
            self.calls = []

        def apply_patch(self, key, fields):
            self.calls.append((key, fields))

    p = Patch(
        itemKey="K",
        title="T",
        before={"doi": None},
        after={"doi": "10.1/x"},
        source="swap",
    )
    ok, errors = apply_patches(Backend(), [p])
    assert ok == 1 and errors == []


def test_apply_patches_records_errors():
    from paperful.metadata import Patch, apply_patches

    class Boom:
        def apply_patch(self, key, fields):
            raise RuntimeError("denied")

    p = Patch(itemKey="K", title="T", before={}, after={"doi": "10.1/x"}, source="swap")
    ok, errors = apply_patches(Boom(), [p])
    assert ok == 0
    assert errors and "K" in errors[0] and "denied" in errors[0]
