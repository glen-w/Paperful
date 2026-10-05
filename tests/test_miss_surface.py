"""Miss-surface enum and OA stamp honesty."""

from __future__ import annotations

from paperful.miss_surface import (
    MISS_SURFACE_CODES,
    import_ok_honest,
    project_miss_surface,
    row_from_item,
)
from paperful.oa_locations import rank_unpaywall_locations
from paperful.store import Record, STATUS_NOT_FOUND, STATUS_OK


def test_frozen_enum_codes():
    assert MISS_SURFACE_CODES == frozenset(
        {
            "no_doi",
            "paywalled",
            "no_oa",
            "fetch_failed",
            "license_blocked",
            "import_ok",
        }
    )


def test_project_no_doi_without_identifier():
    assert project_miss_surface(doi=None, arxiv_id=None, url=None) == "no_doi"


def test_project_no_oa_from_unpaywall_miss():
    code = project_miss_surface(
        doi="10.1/x",
        status=STATUS_NOT_FOUND,
        attempts=["unpaywall:not_found(no OA location)"],
    )
    assert code == "no_oa"


def test_project_paywalled_from_attempt():
    code = project_miss_surface(
        doi="10.1/x",
        status="retryable",
        attempts=["ezproxy:browser-failed(paywall on publisher)"],
    )
    assert code == "paywalled"


def test_import_ok_requires_persisted_stamp_when_api_supplied():
    supplied = {"oa_status": "gold", "license": "cc-by"}
    assert import_ok_honest(
        source="unpaywall",
        oa_stamp={"oa_status": "gold", "license": "cc-by"},
        stamp_fields=("license", "oa_status", "version"),
        supplied_stamp=supplied,
    )
    assert not import_ok_honest(
        source="unpaywall",
        oa_stamp={"oa_status": "gold"},
        stamp_fields=("license", "oa_status", "version"),
        supplied_stamp=supplied,
    )


def test_row_from_record_manifest():
    rec = Record(
        itemKey="ABC",
        status=STATUS_OK,
        source="unpaywall",
        oa_status="green",
        oa_license="cc-by-4.0",
        attempts=["unpaywall:found"],
    )
    row = row_from_item(
        doi="10.1/x",
        has_pdf=True,
        status=rec.status,
        source=rec.source,
        attempts=rec.attempts,
        oa_stamp={"oa_status": "green", "license": "cc-by-4.0"},
    )
    assert row["miss_surface"] == "import_ok"
    assert row["oa_status"] == "green"
    assert row["license"] == "cc-by-4.0"


def test_unpaywall_prefers_repository_pdf():
    data = {
        "oa_status": "green",
        "best_oa_location": {
            "url_for_pdf": "https://pub.test/bronze.pdf",
            "host_type": "publisher",
            "version": "publishedVersion",
        },
        "oa_locations": [
            {
                "url_for_pdf": "https://repo.test/green.pdf",
                "host_type": "repository",
                "license": "cc-by-4.0",
                "version": "publishedVersion",
            }
        ],
    }
    ranked = rank_unpaywall_locations(data)
    assert ranked[0]["url_for_pdf"] == "https://repo.test/green.pdf"
