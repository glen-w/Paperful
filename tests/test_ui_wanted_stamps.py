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


# --- Discover -> Wanted pending-fill feed -------------------------------------


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _seed_discover_state(cfg: Config) -> None:
    import json

    snow = cfg.state_dir / "snowball"
    _write_jsonl(
        snow / "run1" / "candidates.jsonl",
        [
            {"ids": {"doi": "10.5/kept"}, "biblio": {"title": "Kept paper"}, "keep": True, "status": "new", "why": "cited by 2 of your seeds"},
            {"ids": {"doi": "10.5/skipped"}, "biblio": {"title": "Skipped"}, "keep": False, "status": "new"},
            {"ids": {"doi": "10.5/undecided"}, "biblio": {"title": "Undecided"}, "status": "new"},
            {"ids": {"doi": "10.1/e"}, "biblio": {"title": "Already here"}, "keep": True, "status": "new"},
        ],
    )
    _write_jsonl(
        snow / "watches" / "w1" / "inbox.jsonl",
        [
            {"ids": {"doi": "10.5/watch"}, "biblio": {"title": "Watch hit"}},
            {"ids": {"doi": "10.5/KEPT"}, "biblio": {"title": "Same as kept, other case"}},
        ],
    )
    _write_jsonl(
        cfg.state_dir / "keepup" / "j1" / "inbox.jsonl",
        [
            {"ids": {"doi": "10.5/up"}, "biblio": {"title": "Keepup hit"}},
            {"ids": {"doi": "10.5/muted"}, "biblio": {"title": "Muted"}},
        ],
    )
    (cfg.state_dir / "keepup" / "j1" / "muted.json").write_text(
        json.dumps({"identities": ["doi:10.5/muted"]}), encoding="utf-8"
    )
    _write_jsonl(
        cfg.state_dir / "authorwatch" / "lab" / "inbox.jsonl",
        [{"ids": {"doi": "10.5/person"}, "biblio": {"title": "Person hit"}}],
    )


def test_pending_fill_collects_dedupes_and_skips_library(tmp_path):
    from paperful.pending_fill import pending_fill

    cfg = _cfg(tmp_path)
    _seed_discover_state(cfg)
    out = pending_fill(cfg, {"10.1/e"})
    dois = sorted(r["doi"].lower() for r in out["rows"])
    assert dois == ["10.5/kept", "10.5/person", "10.5/up", "10.5/watch"]
    assert out["total"] == 4
    assert out["by_source"] == {"kept": 1, "watch": 1, "keepup": 1, "authorwatch": 1}


def test_pending_fill_empty_state(tmp_path):
    from paperful.pending_fill import pending_fill

    assert pending_fill(_cfg(tmp_path))["total"] == 0


def test_pending_fill_tolerates_corrupt_ledgers_and_skips_blank_rows(tmp_path):
    """Corrupt jsonl / muted.json and empty rows must not hide good candidates."""
    import json

    from paperful.pending_fill import pending_fill

    cfg = _cfg(tmp_path)
    run = cfg.state_dir / "snowball" / "r1"
    run.mkdir(parents=True)
    (run / "candidates.jsonl").write_text(
        "\n"
        "{not-json}\n"
        + json.dumps(
            {"ids": {"doi": "10.9/ok"}, "biblio": {"title": "Good"}, "keep": True, "status": "new"}
        )
        + "\n"
        + json.dumps({"keep": True, "status": "new"})  # no title, no DOI
        + "\n"
        + json.dumps(
            {"biblio": {"title": "Title only"}, "keep": True, "status": "new"}
        )
        + "\n",
        encoding="utf-8",
    )
    keep = cfg.state_dir / "keepup" / "j1"
    keep.mkdir(parents=True)
    (keep / "muted.json").write_text("{broken", encoding="utf-8")
    (keep / "inbox.jsonl").write_text(
        json.dumps({"ids": {"doi": "10.9/up"}, "biblio": {"title": "Up"}}) + "\n",
        encoding="utf-8",
    )
    out = pending_fill(cfg)
    by_title = {r["title"]: r["doi"] for r in out["rows"]}
    assert by_title == {"Good": "10.9/ok", "Title only": "", "Up": "10.9/up"}
    assert out["total"] == 3


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_wanted_page_lists_pending_fill_without_second_desk(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg, items, manifest = _mixed(tmp_path)
    _seed_discover_state(cfg)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _cfg: {"ok": True, "collections": []}
    )
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_collection", "ocean")
    text = client.get("/wanted").text
    assert 'id="pending-fill"' in text
    assert text.count("data-pending-source=") == 4
    assert "Kept paper" in text and "Skipped" not in text.split('id="pending-fill"')[1].split("</section>")[0]
    # The feed adds no write controls: no extra Grab/Attach forms in the panel.
    panel = text.split('id="pending-fill"')[1].split("</section>")[0]
    assert "<form" not in panel and "<button" not in panel
    assert "Why suggested: cited by 2 of your seeds" in panel


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_hand_ticks_on_missing_and_held_are_enabled(wanted_client):
    for tab, expect in (("missing", 2), ("held", 3)):
        text = wanted_client.get(f"/wanted?tab={tab}").text
        boxes = re.findall(r'<input type="checkbox" name="keys"[^>]*>', text)
        assert len(boxes) == expect
        assert all("disabled" not in b for b in boxes)
        assert all("checked" not in b for b in boxes)  # hand-ticks start unticked
    have = re.findall(
        r'<input type="checkbox" name="keys"[^>]*>', wanted_client.get("/wanted?tab=have").text
    )
    assert len(have) == 1 and "checked" in have[0]


# --- Miss reasons, Check tooltips, report reason codes, hand-tick scope --------


def _miss_cases(tmp_path):
    """One missing item per miss-surface code, plus a library-only item."""
    from paperful.store import STATUS_NOT_FOUND, STATUS_RETRYABLE

    cfg = _cfg(tmp_path)
    manifest = Manifest(cfg.manifest_path)
    items = [
        _Item("PAYW", "Paywalled one", "10.2/p", False),
        _Item("NOOA", "No OA one", "10.2/n", False),
        _Item("FAIL", "Failed one", "10.2/f", False),
        _Item("LICN", "License blocked", "10.2/l", False),
        _Item("NOID", "No identifier", None, False),
    ]
    for rec in (
        Record(
            itemKey="PAYW",
            status=STATUS_NOT_FOUND,
            doi="10.2/p",
            attempts=["ezproxy:login required"],
        ),
        Record(
            itemKey="NOOA",
            status=STATUS_NOT_FOUND,
            doi="10.2/n",
            attempts=["unpaywall:not_found", "openalex:not_found"],
        ),
        Record(
            itemKey="FAIL",
            status=STATUS_RETRYABLE,
            doi="10.2/f",
            attempts=["direct:download-failed"],
        ),
        Record(
            itemKey="LICN",
            status=STATUS_NOT_FOUND,
            doi="10.2/l",
            attempts=["unpaywall:license_blocked"],
        ),
    ):
        manifest.write(rec)
    return cfg, items, manifest


def test_every_miss_code_has_a_one_line_reason(tmp_path):
    from paperful.miss_surface import MISS_SURFACE_PLAIN

    cfg, items, manifest = _miss_cases(tmp_path)
    data = wanted_rows(cfg, items, manifest)
    by_key = {r["key"]: r for r in data["missing"]}
    assert {k: r["miss_surface"] for k, r in by_key.items()} == {
        "PAYW": "paywalled",
        "NOOA": "no_oa",
        "FAIL": "fetch_failed",
        "LICN": "license_blocked",
        "NOID": "no_doi",
    }
    for row in by_key.values():
        assert row["miss_plain"] == MISS_SURFACE_PLAIN[row["miss_surface"]]
        assert "\n" not in row["miss_plain"]
    assert data["counts"]["found"] == data["counts"]["check"] == 0


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_missing_tab_renders_each_reason_line(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg, items, manifest = _miss_cases(tmp_path)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _cfg: {"ok": True, "collections": []}
    )
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_collection", "ocean")
    text = client.get("/wanted?tab=missing").text
    found = dict(
        re.findall(r'<span class="miss-reason" data-miss-surface="([a-z_]+)">([^<]+)</span>', text)
    )
    assert found == {
        "paywalled": "Paywalled or login required",
        "no_oa": "No open-access copy found",
        "fetch_failed": "Fetch failed or incomplete",
        "license_blocked": "Blocked by license policy",
        "no_doi": "No DOI or identifier to search",
    }
    assert 'data-stamp="found"' not in text and 'data-stamp="check"' not in text


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_check_stamp_tooltips_name_the_reason(wanted_client):
    text = wanted_client.get("/wanted?tab=held").text
    for tip in (
        "Embedded DOI differs from the library item",  # doi_mismatch
        "No DOI found inside the PDF",  # unverified
        "Saved from HTML conversion",  # snapshot
    ):
        assert tip in text, tip
    for plain in (
        "PDF on disk but DOI does not match the library",
        "PDF on disk, identity not verified",
        "HTML page snapshot, not a publisher PDF",
    ):
        assert plain in text, plain


def test_misses_csv_carries_reason_codes_for_checks_and_misses(tmp_path):
    cfg, items, manifest = _mixed(tmp_path)
    report = report_cards(wanted_rows(cfg, items, manifest), collection="ocean")
    rows = {r["key"]: r for r in csv.DictReader(io.StringIO(render_misses_csv(report)))}
    assert rows["MISM"]["stamp"] == "check" and rows["MISM"]["reason_code"] == "doi_differs"
    assert rows["UNVER"]["stamp"] == "check" and rows["UNVER"]["reason_code"] == "no_doi_in_file"
    assert rows["SNAP"]["stamp"] == "check" and rows["SNAP"]["reason_code"] == "htmlpdf"
    assert rows["NODOI"]["stamp"] == "missing" and rows["NODOI"]["reason_code"] == "no_doi"
    # Never attempted: no code yet, but the one-line reason is still present.
    assert rows["MISS"]["stamp"] == "missing"
    assert rows["MISS"]["reason"] == "No stored PDF"
    assert "MATCH" not in rows
    assert all(r["reason"] for r in rows.values())


def test_report_counts_agree_across_json_markdown_and_csv(tmp_path):
    cfg, items, manifest = _mixed(tmp_path)
    data = wanted_rows(cfg, items, manifest)
    report = report_cards(data, collection="ocean")
    counts = card_counts(data)
    assert report["counts"] == counts
    assert counts["found"] == sum(1 for c in report["cards"] if c["stamp"] == "found") == 1
    assert counts["check"] == sum(1 for c in report["cards"] if c["stamp"] == "check") == 3
    csv_rows = list(csv.DictReader(io.StringIO(render_misses_csv(report))))
    assert len(csv_rows) == counts["total"] - counts["found"]
    assert f"{counts['found']} found" in render_markdown(report)


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_report_route_400_without_collection_and_502_on_loader_error(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = _cfg(tmp_path)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _cfg: {"ok": True, "collections": []}
    )
    client = TestClient(create_app(cfg))
    for fmt in ("md", "json", "csv"):
        res = client.get(f"/wanted/report?format={fmt}")
        assert res.status_code == 400
        assert "Pick a collection" in res.text

    def boom(_cfg, _collection):
        raise RuntimeError("library unreachable")

    monkeypatch.setattr("paperful.ui.wanted_routes._load_wanted", boom)
    client.cookies.set("pf_collection", "ocean")
    res = client.get("/wanted/report?format=json")
    assert res.status_code == 502
    assert "library unreachable" in res.text


def test_held_mismatch_needs_explicit_override_to_attach(tmp_path, monkeypatch):
    from paperful.store import REASON_SHORT_PDF, REASON_STRICT_PDF_DOI

    cfg = _cfg(tmp_path)
    manifest = Manifest(cfg.manifest_path)
    for key, reason in (("OK", ""), ("MISM", REASON_STRICT_PDF_DOI), ("SHORT", REASON_SHORT_PDF)):
        manifest.write(
            Record(
                itemKey=key,
                status=STATUS_OK,
                doi="10.1/a",
                pdf_doi="10.9/x" if key == "MISM" else "10.1/a",
                source="unpaywall",
                path=f"{key}.pdf",
                reason=reason,
            )
        )
    assert {r.itemKey for r in manifest.pending_attach()} == {"OK"}
    assert {r.itemKey for r in manifest.pending_attach(allow_pdf_doi_mismatch=True)} == {"OK", "MISM"}
    assert {r.itemKey for r in manifest.pending_attach(allow_short_pdf=True)} == {"OK", "SHORT"}

    items = [_Item(k, k, "10.1/a", True) for k in ("OK", "MISM", "SHORT")]
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))
    written: list[list[str]] = []
    monkeypatch.setattr(jobs, "_attach_keys", lambda _c, keys: written.append(list(keys)) or len(keys))

    # Ticking a held mismatch and pressing the main Attach does nothing.
    ok, msg, n = jobs.attach_run(cfg, keys=["MISM"], collection="ocean")
    assert (ok, n) == (False, 0) and "no attachable" in msg
    assert written == []
    # Unticked main Attach writes only the clean row.
    ok, _msg, n = jobs.attach_run(cfg, keys=[], collection="ocean")
    assert ok and n == 1 and written == [["OK"]]


def test_advanced_override_attaches_ticked_mismatch(tmp_path, monkeypatch):
    from paperful.store import REASON_STRICT_PDF_DOI
    from paperful.ui import wanted_jobs

    cfg = _cfg(tmp_path)
    manifest = Manifest(cfg.manifest_path)
    manifest.write(
        Record(
            itemKey="MISM",
            status=STATUS_OK,
            doi="10.1/b",
            pdf_doi="10.9/x",
            source="unpaywall",
            path="MISM.pdf",
            reason=REASON_STRICT_PDF_DOI,
        )
    )
    items = [_Item("MISM", "Mismatched", "10.1/b", True)]
    monkeypatch.setattr(wanted_jobs, "_load_items", lambda _c, _col: (object(), items, manifest))
    calls: list[dict] = []
    monkeypatch.setattr(
        wanted_jobs,
        "attach_pending_fn",
        lambda _c, **kw: calls.append(kw) or {},
    )
    cmd_id = "adv1"
    import time

    commands_mod = __import__("paperful.ui.commands", fromlist=["x"])
    commands_mod.write_command(
        cfg,
        {"id": cmd_id, "verb": "attach", "status": "running", "review_token": "", "error": "",
         "report_path": "", "created": time.time()},
    )
    token = wanted_jobs.attach_preview(
        cfg, cmd_id, collection="ocean", keys=["MISM"], allow_mismatch=True, allow_short=False
    )
    review = commands_mod.load_review(cfg, token)
    assert review["keys"] == ["MISM"]
    assert review["flags"] == {"allow_mismatch": True, "allow_short": False}
    ok, msg = wanted_jobs.attach_apply(cfg, token=token)
    assert ok, msg
    assert calls and calls[0]["keys"] == ["MISM"] and calls[0]["allow_mismatch"] is True
    # Without the override the same tick previews no pending rows.
    plain = wanted_jobs.attach_preview(
        cfg, cmd_id, collection="ocean", keys=["MISM"], allow_mismatch=False, allow_short=False
    )
    assert commands_mod.load_review(cfg, plain)["flags"]["allow_mismatch"] is False


def test_ticked_missing_rows_scope_grab_and_unticked_uses_missing_list(tmp_path, monkeypatch):
    cfg, items, manifest = _mixed(tmp_path)
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))
    ticked, _ = jobs.scope_for_fetch(cfg, "ocean", ["MISS"], None)
    assert [it.key for it in ticked] == ["MISS"]
    held_tick, _ = jobs.scope_for_fetch(cfg, "ocean", ["MISM", "UNVER"], None)
    assert {it.key for it in held_tick} == {"MISM", "UNVER"}
    default, _ = jobs.scope_for_fetch(cfg, "ocean", None, None)
    assert {it.key for it in default} == {"MISS", "NODOI"}
