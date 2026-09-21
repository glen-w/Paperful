"""Provenance stamp taxonomy."""

from paperful.provenance import provenance_label, provenance_stamp


def test_oa_campus_pirate_and_web_labels():
    assert provenance_label("unpaywall") == "oa:unpaywall"
    assert provenance_label("openalex") == "oa:openalex"
    assert provenance_label("ezproxy") == "campus:ezproxy"
    assert provenance_label("scihub") == "pirate:scihub"
    assert provenance_label("htmlpdf") == "web:htmlpdf"
    assert provenance_label("scholar") == "web:scholar"
    assert provenance_label("browser_agent") == "web:browser_agent"
    assert provenance_label("direct") == "web:direct"
    assert provenance_label("direct", playbook="undocs-unga-vme") == "grey:undocs-unga-vme"
    assert provenance_label(None) == "web:unknown"


def test_stamp_note_includes_mismatch_warning():
    assert provenance_stamp("unpaywall") == "paperful oa:unpaywall"
    assert (
        provenance_stamp("unpaywall", pdf_doi_mismatch=True)
        == "paperful oa:unpaywall warn:pdf_doi_mismatch"
    )
