"""Metadata propose_patch semantics: fill, overwrite, PDF DOI, dates, title hygiene."""

from __future__ import annotations

import json

import httpx

from paperful.lint import lint_item
from paperful.metadata import (
    Patch,
    apply_patches,
    collect_patches,
    dedupe_patches,
    propose_patch,
)
from paperful.resolve import date_precision, format_date_parts, strip_title_markup
from tests.conftest import make_item, mock_client


def _json(payload, status=200):
    return httpx.Response(
        status,
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )


def _work_handler(doi: str, title: str, *, year=2019, month=None, day=None, venue=None):
    parts = [year]
    if month is not None:
        parts.append(month)
    if day is not None:
        parts.append(day)

    def handler(req):
        host = req.url.host or ""
        path = req.url.path
        if "crossref.org" in host and "/works/" in path and not path.endswith("/works"):
            msg = {
                "DOI": doi,
                "title": [title],
                "issued": {"date-parts": [parts]},
            }
            if venue:
                msg["container-title"] = [venue]
            return _json({"message": msg})
        return httpx.Response(404)

    return handler


def test_format_date_parts_and_precision():
    assert format_date_parts([2019]) == "2019"
    assert format_date_parts([2019, 5]) == "2019-05"
    assert format_date_parts([2019, 5, 3]) == "2019-05-03"
    assert date_precision(None) == 0
    assert date_precision("n.d.") == 0
    assert date_precision("2019") == 1
    assert date_precision("2019-05") == 2
    assert date_precision("2019-05-03") == 3
    assert date_precision("May 3, 1998") == 2


def test_strip_title_markup():
    assert strip_title_markup("<i>Hello</i> &amp; world") == "Hello & world"


def test_propose_fills_empty_venue_date_when_doi_ok(cfg):
    title = "A sufficiently long test title about marine governance"
    item = make_item(
        doi="10.9/ok",
        title=title,
        url=None,
        publication_title=None,
        date=None,
    )
    client = mock_client(
        _work_handler("10.9/ok", title, venue="Marine Policy", year=2019, month=5)
    )
    findings = lint_item(client, cfg, item)
    patch = propose_patch(client, cfg, item, findings, prepared=True)
    assert patch is not None
    assert "doi" not in patch.after  # library DOI already correct
    assert patch.after["publicationTitle"] == "Marine Policy"
    assert patch.after["date"] == "2019-05"
    assert "title" not in patch.after


def test_propose_overwrite_replaces_title_date_venue(cfg, monkeypatch):
    title = "A sufficiently long test title about marine governance"
    item = make_item(
        doi="10.9/ok",
        title=title,
        url=None,
        publication_title="Old Venue",
        date="2010",
    )
    client = mock_client(_work_handler("10.9/ok", title, venue="New Venue", year=2019))
    findings = lint_item(client, cfg, item)
    assert item.doi_verified == "ok"

    from paperful.resolve import WorkMeta

    monkeypatch.setattr(
        "paperful.metadata.work_by_doi",
        lambda *a, **k: WorkMeta(
            doi="10.9/ok",
            title="Cleaner Title From Crossref About Marine Governance",
            year=2019,
            date="2019-06",
            venue="New Venue",
            source="crossref",
        ),
    )
    patch = propose_patch(
        client, cfg, item, findings, overwrite=True, prepared=True
    )
    assert patch is not None
    assert patch.after["publicationTitle"] == "New Venue"
    assert patch.after["date"] == "2019-06"
    assert patch.after["title"] == "Cleaner Title From Crossref About Marine Governance"


def test_propose_no_title_without_overwrite(cfg):
    title = "A sufficiently long test title about marine governance"
    item = make_item(
        doi="10.9/ok", title=title, url=None, publication_title="V", date="2019"
    )
    client = mock_client(_work_handler("10.9/ok", title, venue="Other", year=2020))
    findings = lint_item(client, cfg, item)
    patch = propose_patch(client, cfg, item, findings, prepared=True)
    # venue/date already set → no-op without overwrite
    assert patch is None


def test_propose_fills_doi_when_library_empty(cfg):
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        host = req.url.host or ""
        path = req.url.path
        if "crossref.org" in host and "/works/" in path and not path.endswith("/works"):
            return _json(
                {
                    "message": {
                        "DOI": "10.9/found",
                        "title": [title],
                        "issued": {"date-parts": [[2019, 3]]},
                        "container-title": ["Marine Policy"],
                    }
                }
            )
        if "crossref.org" in host:
            return _json(
                {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.9/found",
                                "title": [title],
                                "issued": {"date-parts": [[2019, 3]]},
                            }
                        ]
                    }
                }
            )
        return httpx.Response(404)

    item = make_item(
        doi=None,
        title=title,
        url=None,
        publication_title=None,
        date=None,
    )
    client = mock_client(handler)
    findings = lint_item(client, cfg, item)
    assert item.doi == "10.9/found"
    assert not item.library_doi
    patch = propose_patch(client, cfg, item, findings, prepared=True)
    assert patch is not None
    assert patch.after["doi"] == "10.9/found"
    assert patch.after.get("publicationTitle") == "Marine Policy"
    assert patch.after.get("date") == "2019-03"


def test_propose_suspect_doi_no_venue_patch(cfg):
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        host = req.url.host or ""
        path = req.url.path
        if "crossref.org" in host and "/works/" in path and not path.endswith("/works"):
            return _json(
                {
                    "message": {
                        "DOI": "10.1/wrong",
                        "title": ["Totally different unrelated work"],
                        "issued": {"date-parts": [[2010]]},
                        "container-title": ["Wrong Venue"],
                    }
                }
            )
        return _json({"message": {"items": []}})

    item = make_item(
        doi="10.1/wrong",
        title=title,
        url=None,
        publication_title=None,
        date=None,
    )
    client = mock_client(handler)
    findings = lint_item(client, cfg, item)
    assert item.doi_verified == "suspect"
    assert any(f.code == "suspect_doi" for f in findings)
    patch = propose_patch(client, cfg, item, findings, prepared=True)
    assert patch is None or (
        "doi" not in patch.after
        and "publicationTitle" not in patch.after
        and "date" not in patch.after
    )


def test_propose_unknown_doi_no_patch(cfg):
    title = "A sufficiently long test title about marine governance"

    def handler(req):
        return httpx.Response(500)

    item = make_item(doi="10.9/x", title=title, url=None, publication_title=None)
    client = mock_client(handler)
    findings = lint_item(client, cfg, item)
    assert item.doi_verified == "unknown"
    patch = propose_patch(client, cfg, item, findings, prepared=True)
    assert patch is None or "doi" not in (patch.after if patch else {})


def test_propose_skips_prepare_when_prepared(cfg, monkeypatch):
    title = "A sufficiently long test title about marine governance"
    item = make_item(doi="10.9/ok", title=title, url=None)
    item.doi_verified = "ok"
    item.library_doi = "10.9/ok"
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("prepare should not run")

    monkeypatch.setattr("paperful.metadata.prepare_identifiers", boom)
    monkeypatch.setattr(
        "paperful.metadata.work_by_doi",
        lambda *a, **k: None,
    )
    propose_patch(
        mock_client(lambda r: httpx.Response(500)),
        cfg,
        item,
        [],
        prepared=True,
    )
    assert calls["n"] == 0


def test_date_precision_guard_no_shorten(cfg, monkeypatch):
    title = "A sufficiently long test title about marine governance"
    item = make_item(
        doi="10.9/ok",
        title=title,
        url=None,
        publication_title="V",
        date="2019-05",
    )
    item.doi_verified = "ok"
    item.library_doi = "10.9/ok"
    from paperful.resolve import WorkMeta

    monkeypatch.setattr(
        "paperful.metadata.work_by_doi",
        lambda *a, **k: WorkMeta(
            doi="10.9/ok",
            title=title,
            year=2019,
            date="2019",
            venue="V",
            source="crossref",
        ),
    )
    patch = propose_patch(
        mock_client(lambda r: httpx.Response(500)),
        cfg,
        item,
        [],
        overwrite=True,
        prepared=True,
    )
    assert patch is None or "date" not in patch.after


def test_date_precision_overwrite_enrich(cfg, monkeypatch):
    title = "A sufficiently long test title about marine governance"
    item = make_item(
        doi="10.9/ok",
        title=title,
        url=None,
        publication_title="V",
        date="2019",
    )
    item.doi_verified = "ok"
    item.library_doi = "10.9/ok"
    from paperful.resolve import WorkMeta

    monkeypatch.setattr(
        "paperful.metadata.work_by_doi",
        lambda *a, **k: WorkMeta(
            doi="10.9/ok",
            title=title,
            year=2019,
            date="2019-05",
            venue="V",
            source="crossref",
        ),
    )
    patch = propose_patch(
        mock_client(lambda r: httpx.Response(500)),
        cfg,
        item,
        [],
        overwrite=True,
        prepared=True,
    )
    assert patch is not None
    assert patch.after["date"] == "2019-05"


def test_html_title_cleanup_patch(cfg):
    title = "<i>A sufficiently long test title about marine governance</i>"
    item = make_item(doi=None, title=title, url=None, arxiv_id=None)
    findings = lint_item(mock_client(lambda r: httpx.Response(500)), cfg, item)
    assert any(f.code == "title_html" for f in findings)
    patch = propose_patch(
        mock_client(lambda r: httpx.Response(500)),
        cfg,
        item,
        findings,
        prepared=True,
    )
    assert patch is not None
    assert patch.after["title"] == "A sufficiently long test title about marine governance"
    assert patch.source == "title_html"


def test_title_all_caps_and_filename_findings_only(cfg):
    caps = make_item(
        doi=None,
        url=None,
        arxiv_id=None,
        title="A SUFFICIENTLY LONG TEST TITLE ABOUT MARINE GOVERNANCE",
    )
    findings = lint_item(mock_client(lambda r: httpx.Response(500)), cfg, caps)
    assert any(f.code == "title_all_caps" for f in findings)
    patch = propose_patch(
        mock_client(lambda r: httpx.Response(500)), cfg, caps, findings, prepared=True
    )
    # ALL CAPS is findings-only (no invented title case)
    assert patch is None or "title" not in patch.after

    fn = make_item(
        doi=None,
        url=None,
        arxiv_id=None,
        title="smith_2019_marine_governance.pdf",
    )
    findings2 = lint_item(mock_client(lambda r: httpx.Response(500)), cfg, fn)
    assert any(f.code == "title_filename" for f in findings2)


def test_pdf_doi_adopted_when_verified(cfg, tmp_path, monkeypatch):
    from pypdf import PdfWriter

    title = "A sufficiently long test title about marine governance"
    pdf = tmp_path / "item.pdf"
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.add_metadata({"/Title": "doi:10.5555/from-pdf"})
    w.write(pdf)
    monkeypatch.setattr("paperful.pdfid._PDFTOTEXT", None)
    monkeypatch.setattr("paperful.pdfid.shutil.which", lambda name: None)

    def handler(req):
        host = req.url.host or ""
        path = req.url.path
        if "crossref.org" in host and "/works/" in path and not path.endswith("/works"):
            doi = path.split("/works/", 1)[1]
            if "from-pdf" in doi or "5555" in doi:
                return _json(
                    {
                        "message": {
                            "DOI": "10.5555/from-pdf",
                            "title": [title],
                            "issued": {"date-parts": [[2019]]},
                            "container-title": ["Ocean Studies"],
                        }
                    }
                )
            # library DOI work — unrelated title so verify fails / unknown
            return _json(
                {
                    "message": {
                        "DOI": "10.1000/wrong",
                        "title": ["Unrelated paper title here"],
                        "issued": {"date-parts": [[2010]]},
                    }
                }
            )
        return _json({"message": {"items": []}})

    item = make_item(
        doi="10.1000/wrong",
        title=title,
        url=None,
        pdf_path=str(pdf),
        has_pdf=True,
        publication_title=None,
        date=None,
    )
    client = mock_client(handler)
    findings = lint_item(client, cfg, item)
    assert any(f.code == "pdf_doi_mismatch" for f in findings)
    patch = propose_patch(client, cfg, item, findings, prepared=True)
    assert patch is not None
    assert patch.after.get("doi") == "10.5555/from-pdf"
    assert patch.source == "pdf"


def test_pdf_doi_not_adopted_when_library_ok(cfg, tmp_path, monkeypatch):
    from pypdf import PdfWriter

    title = "A sufficiently long test title about marine governance"
    pdf = tmp_path / "item.pdf"
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.add_metadata({"/Title": "doi:10.5555/other"})
    w.write(pdf)
    monkeypatch.setattr("paperful.pdfid._PDFTOTEXT", None)
    monkeypatch.setattr("paperful.pdfid.shutil.which", lambda name: None)

    def handler(req):
        host = req.url.host or ""
        path = req.url.path
        if "crossref.org" in host and "/works/" in path and not path.endswith("/works"):
            doi = path.split("/works/", 1)[1]
            if "other" in doi:
                return _json(
                    {
                        "message": {
                            "DOI": "10.5555/other",
                            "title": [title],
                            "issued": {"date-parts": [[2019]]},
                        }
                    }
                )
            return _json(
                {
                    "message": {
                        "DOI": "10.1000/test.doi",
                        "title": [title],
                        "issued": {"date-parts": [[2019]]},
                        "container-title": ["Journal"],
                    }
                }
            )
        return httpx.Response(404)

    item = make_item(
        doi="10.1000/test.doi",
        title=title,
        url=None,
        pdf_path=str(pdf),
        has_pdf=True,
        publication_title="Journal",
        date="2019",
    )
    client = mock_client(handler)
    findings = lint_item(client, cfg, item)
    assert item.doi_verified == "ok"
    patch = propose_patch(client, cfg, item, findings, prepared=True)
    assert patch is None or patch.after.get("doi") != "10.5555/other"

    patch_ow = propose_patch(
        client, cfg, item, findings, overwrite=True, prepared=True
    )
    assert patch_ow is not None
    assert patch_ow.after.get("doi") == "10.5555/other"
    assert patch_ow.source == "pdf"


def test_dedupe_patches():
    a = Patch(itemKey="K", title="t", before={}, after={"doi": "10.1/a"}, source="a")
    b = Patch(itemKey="K", title="t", before={}, after={"doi": "10.1/b"}, source="b")
    out = dedupe_patches([a, b])
    assert len(out) == 1 and out[0].after["doi"] == "10.1/b"


def test_collect_patches_lints_then_proposes_with_one_cache(cfg, monkeypatch):
    linted: list[str] = []
    caches: list[object] = []

    def fake_lint(client, config, item, **kwargs):
        linted.append(item.key)
        caches.append(kwargs["cache"])
        return []

    def fake_propose(client, config, item, findings, **kwargs):
        assert kwargs["prepared"] is True
        assert kwargs["cache"] is caches[0]
        if item.key == "DROP":
            return None
        return Patch(
            itemKey=item.key,
            title=item.title,
            before={},
            after={"doi": "10.1/" + item.key.lower()},
            source="test",
        )

    monkeypatch.setattr("paperful.metadata.lint_item", fake_lint)
    monkeypatch.setattr("paperful.metadata.propose_patch", fake_propose)
    patches = collect_patches(
        mock_client(lambda r: None),
        cfg,
        [make_item(key="A"), make_item(key="DROP")],
    )
    assert linted == ["A", "DROP"]
    assert [p.itemKey for p in patches] == ["A"]
    assert patches[0].after["doi"] == "10.1/a"


def test_pdf_doi_rejected_when_title_mismatches(cfg, tmp_path, monkeypatch):
    from pypdf import PdfWriter

    title = "A sufficiently long test title about marine governance"
    pdf = tmp_path / "item.pdf"
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.add_metadata({"/Title": "doi:10.5555/unrelated-pdf"})
    w.write(pdf)
    monkeypatch.setattr("paperful.pdfid._PDFTOTEXT", None)
    monkeypatch.setattr("paperful.pdfid.shutil.which", lambda name: None)

    def handler(req):
        host = req.url.host or ""
        path = req.url.path
        if "crossref.org" in host and "/works/" in path and not path.endswith("/works"):
            doi = path.split("/works/", 1)[1]
            if "unrelated-pdf" in doi:
                return _json(
                    {
                        "message": {
                            "DOI": "10.5555/unrelated-pdf",
                            "title": ["Completely different chemistry paper"],
                            "issued": {"date-parts": [[1999]]},
                        }
                    }
                )
            return _json(
                {
                    "message": {
                        "DOI": "10.1000/wrong",
                        "title": ["Also unrelated"],
                        "issued": {"date-parts": [[2010]]},
                    }
                }
            )
        return _json({"message": {"items": []}})

    item = make_item(
        doi="10.1000/wrong",
        title=title,
        url=None,
        pdf_path=str(pdf),
        has_pdf=True,
        publication_title=None,
        date=None,
    )
    client = mock_client(handler)
    findings = lint_item(client, cfg, item)
    assert any(f.code == "pdf_doi_mismatch" for f in findings)
    patch = propose_patch(client, cfg, item, findings, prepared=True)
    assert patch is None or patch.after.get("doi") != "10.5555/unrelated-pdf"


def test_no_overwrite_keeps_existing_year_date(cfg, monkeypatch):
    title = "A sufficiently long test title about marine governance"
    item = make_item(
        doi="10.9/ok",
        title=title,
        url=None,
        publication_title=None,
        date="2019",
    )
    item.doi_verified = "ok"
    item.library_doi = "10.9/ok"
    from paperful.resolve import WorkMeta

    monkeypatch.setattr(
        "paperful.metadata.work_by_doi",
        lambda *a, **k: WorkMeta(
            doi="10.9/ok",
            title=title,
            year=2019,
            date="2019-05",
            venue="Marine Policy",
            source="crossref",
        ),
    )
    patch = propose_patch(
        mock_client(lambda r: httpx.Response(500)),
        cfg,
        item,
        [],
        prepared=True,
    )
    assert patch is not None
    assert patch.after.get("publicationTitle") == "Marine Policy"
    assert "date" not in patch.after


def test_junk_date_filled_without_overwrite(cfg, monkeypatch):
    title = "A sufficiently long test title about marine governance"
    item = make_item(
        doi="10.9/ok",
        title=title,
        url=None,
        publication_title="V",
        date="n.d.",
    )
    item.doi_verified = "ok"
    item.library_doi = "10.9/ok"
    from paperful.resolve import WorkMeta

    monkeypatch.setattr(
        "paperful.metadata.work_by_doi",
        lambda *a, **k: WorkMeta(
            doi="10.9/ok",
            title=title,
            year=2019,
            date="2019-05",
            venue="V",
            source="crossref",
        ),
    )
    patch = propose_patch(
        mock_client(lambda r: httpx.Response(500)),
        cfg,
        item,
        [],
        prepared=True,
    )
    assert patch is not None
    assert patch.after["date"] == "2019-05"


def test_openalex_work_date(cfg):
    from paperful.resolve import work_by_doi

    def handler(req):
        if "openalex.org" in (req.url.host or ""):
            return _json(
                {
                    "doi": "https://doi.org/10.9/oa",
                    "display_name": "A sufficiently long test title about marine governance",
                    "publication_year": 2018,
                    "publication_date": "2018-07-04",
                    "authorships": [],
                    "primary_location": {"source": {"display_name": "OA Journal"}},
                }
            )
        return httpx.Response(404)

    work = work_by_doi(mock_client(handler), "10.9/oa", "a@b.c")
    assert work is not None
    assert work.date == "2018-07-04"
    assert work.year == 2018
    assert work.venue == "OA Journal"


def test_apply_patches_e2e_with_propose(cfg):
    title = "A sufficiently long test title about marine governance"
    item = make_item(
        doi="10.9/ok", title=title, url=None, publication_title=None, date=None
    )
    client = mock_client(
        _work_handler("10.9/ok", title, venue="Marine Policy", year=2019)
    )
    findings = lint_item(client, cfg, item)
    patch = propose_patch(client, cfg, item, findings, prepared=True)
    assert patch is not None

    class Backend:
        def __init__(self):
            self.calls = []

        def apply_patch(self, key, fields):
            self.calls.append((key, dict(fields)))

    backend = Backend()
    ok, errors = apply_patches(backend, [patch])
    assert ok == 1 and not errors
    assert backend.calls[0][1].get("publicationTitle") == "Marine Policy"
