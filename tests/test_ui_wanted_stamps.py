"""Wanted stamps, miss-reason subtitle, and report-card parity (post-1.1 P0)."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available
from paperful.store import Manifest, Record, STATUS_OK
from paperful.ui import jobs
from paperful.ui.pages import wanted_rows
from paperful.ui.verify import stamp_for_state
from paperful.wanted_cards import (
    card_counts,
    render_markdown,
    render_misses_csv,
    report_cards,
)


class _Item:
    def __init__(self, key, title, doi, has_pdf, year=2024):
        self.key = key
        self.title = title
        self.doi = doi
        self.has_pdf = has_pdf
        self.year = year
        self.arxiv_id = None
        self.url = ""


def _cfg(tmp_path) -> Config:
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    return cfg


def _mixed(tmp_path):
    """One of every state: match, mismatch, unverified, snapshot, missing, no DOI."""
    cfg = _cfg(tmp_path)
    manifest = Manifest(cfg.manifest_path)
    items = [
        _Item("MATCH", "Matched", "10.1/a", True),
        _Item("MISM", "Mismatched", "10.1/b", True),
        _Item("UNVER", "Unverified", "10.1/c", True),
        _Item("SNAP", "Snapshot", "10.1/d", True),
        _Item("MISS", "Missing", "10.1/e", False),
        _Item("NODOI", "No identifier", None, False),
    ]
    for key, doi, pdf_doi, source in (
        ("MATCH", "10.1/a", "10.1/a", "unpaywall"),
        ("MISM", "10.1/b", "10.9/x", "unpaywall"),
        ("UNVER", "10.1/c", None, "unpaywall"),
        ("SNAP", "10.1/d", "10.1/d", "htmlpdf"),
    ):
        manifest.write(
            Record(
                itemKey=key,
                status=STATUS_OK,
                doi=doi,
                pdf_doi=pdf_doi,
                source=source,
                path=f"{key}.pdf",
            )
        )
    return cfg, items, manifest


def test_stamp_for_state_found_only_on_doi_match():
    assert stamp_for_state("doi_match") == "found"
    for state in ("doi_mismatch", "unverified", "snapshot"):
        assert stamp_for_state(state) == "check"
    assert stamp_for_state("missing") == ""
    assert stamp_for_state(None) == ""


def test_found_count_equals_doi_match_rows(tmp_path):
    cfg, items, manifest = _mixed(tmp_path)
    data = wanted_rows(cfg, items, manifest)
    states = [r["state"] for r in data["have"] + data["held"]]
    assert states.count("doi_match") == data["counts"]["found"] == 1
    assert data["counts"]["check"] == 3
    # Only doi_match lands in Have; everything with a file but unverified is Held.
    assert [r["key"] for r in data["have"]] == ["MATCH"]
    assert {r["key"] for r in data["held"]} == {"MISM", "UNVER", "SNAP"}


def test_card_counts_follow_stamps_not_buckets(tmp_path):
    cfg, items, manifest = _mixed(tmp_path)
    data = wanted_rows(cfg, items, manifest)
    counts = card_counts(data)
    assert counts == {"found": 1, "check": 3, "missing": 2, "total": 6}
    # A held row never counts as found, even if it is stamped found by mistake in the bucket.
    data["held"][0]["stamp"] = "check"
    assert card_counts(data)["found"] == 1


def test_report_markdown_and_csv_match_stamps(tmp_path):
    cfg, items, manifest = _mixed(tmp_path)
    report = report_cards(wanted_rows(cfg, items, manifest), collection="ocean")
    md = render_markdown(report)
    assert "1 found · 3 to check · 2 missing" in md
    assert md.count("| Found |") == report["counts"]["found"]
    assert "%" not in md
    rows = list(csv.DictReader(io.StringIO(render_misses_csv(report))))
    assert {r["key"] for r in rows} == {"MISM", "UNVER", "SNAP", "MISS", "NODOI"}
    assert all(r["reason"] for r in rows)


@pytest.fixture
def wanted_client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    cfg, items, manifest = _mixed(tmp_path)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_collection", "ocean")
    return client


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_have_tab_shows_found_stamp(wanted_client):
    page = wanted_client.get("/wanted?tab=have")
    assert page.status_code == 200
    assert page.text.count('data-stamp="found"') == 1
    assert 'data-stamp="check"' not in page.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_held_tab_shows_check_stamps_never_found(wanted_client):
    page = wanted_client.get("/wanted?tab=held")
    assert page.text.count('data-stamp="check"') == 3
    assert 'data-stamp="found"' not in page.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_missing_rows_have_visible_reason_line(wanted_client):
    page = wanted_client.get("/wanted?tab=missing")
    reasons = re.findall(r'<span class="miss-reason"[^>]*>([^<]+)</span>', page.text)
    assert len(reasons) == 2
    assert "No DOI or identifier to search" in reasons
    assert 'data-stamp=' not in page.text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_wanted_page_has_no_percent_complete(wanted_client):
    for tab in ("missing", "held", "have"):
        text = wanted_client.get(f"/wanted?tab={tab}").text.lower()
        assert "% complete" not in text
        assert "percent" not in text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_report_route_matches_page_stamps(wanted_client):
    body = wanted_client.get("/wanted/report?format=json").json()
    assert body["schema"] == "paperful.wanted_cards.v1"
    page = wanted_client.get("/wanted?tab=have")
    assert body["counts"]["found"] == page.text.count('data-stamp="found"')
    md = wanted_client.get("/wanted/report").text
    assert "1 found" in md
    csv_text = wanted_client.get("/wanted/report?format=csv").text
    assert "MATCH" not in csv_text


def test_no_percent_complete_in_shipped_copy():
    roots = [Path("paperful/ui/templates"), Path("website/cleaning-service.html")]
    files = [p for r in roots for p in (r.rglob("*.html") if r.is_dir() else [r])]
    for path in files:
        assert "% complete" not in path.read_text(encoding="utf-8").lower(), path
