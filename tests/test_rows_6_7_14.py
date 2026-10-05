"""Linked-URL health, grey fingerprint, and HTML snapshot tier."""

from __future__ import annotations

from paperful.greyid import grey_key, is_snapshot_note, registrable_host
from paperful.identity import LibraryFingerprint
from paperful.miss_surface import project_miss_surface
from paperful.page_signals import print_page_refusal
from paperful.provenance import provenance_label, provenance_stamp
from paperful.routing import place_academic_htmlpdf, source_applicable
from paperful.sources.htmlpdf import academic_mode, find
from paperful.sources.base import Outcome
from paperful.store import STATUS_ATTACHED
from paperful.urls import classify_probe, planned_rewrite
from paperful.zot import items_without_stored_pdf
from paperful.dedupe import classify
from tests.conftest import PDF_BYTES, make_item


def test_registrable_host_skips_publisher_platforms():
    assert registrable_host("https://www.fao.org/3/ca1234en/ca1234en.pdf") == "fao.org"
    assert registrable_host("https://doi.org/10.1000/x") == ""
    assert registrable_host("https://link.springer.com/article/1") == ""


def test_fingerprint_host_mismatch_is_not_exists():
    lib = make_item(
        key="LIB",
        doi=None,
        title="Mesopelagic harvest rules for the high seas",
        year=2024,
        url="https://www.fao.org/docs/report",
    )
    fp = LibraryFingerprint.from_items([lib])
    assert fp.find(None, lib.title, 2024, url="https://www.oecd.org/other") is None
    hit = fp.find(None, lib.title, 2024, url="https://www.fao.org/3/abc.pdf")
    assert hit is not None and hit.kind == "grey"
    assert grey_key(lib.title, 2024, url=lib.url) == (
        "mesopelagic harvest rules for the high seas",
        2024,
        "fao.org",
    )


def test_fingerprint_isbn_before_title():
    lib = make_item(key="B", doi=None, title="Ocean book", year=2020, isbn="9780306406157")
    fp = LibraryFingerprint.from_items([lib])
    hit = fp.find(None, "Different title", 1999, isbn="978-0-306-40615-7")
    assert hit is not None and hit.kind == "isbn" and hit.item_key == "B"


def test_dedupe_does_not_merge_conflicting_hosts():
    items = [
        make_item(key="A", doi=None, title="Shared grey title about fisheries", year=2022, url="https://www.fao.org/a"),
        make_item(key="B", doi=None, title="Shared grey title about fisheries", year=2022, url="https://www.oecd.org/b"),
    ]
    assert classify(items, "all") == []


def test_dedupe_isbn_is_actionable_like_doi():
    items = [
        make_item(key="A", doi=None, title="Same book title here", year=2020, isbn="9780306406157", has_pdf=True),
        make_item(key="B", doi=None, title="Same book title here", year=2020, isbn="9780306406157"),
    ]
    groups = classify(items, "all")
    assert len(groups) == 1
    assert groups[0].phase == "grey_id"
    assert groups[0].needs_review is False
    assert groups[0].keep == "A"


def test_url_findings_cover_each_code():
    assert classify_probe(status=200, url="https://example.org/a", final_url="https://example.org/a", content_type="application/pdf") == "ok"
    assert classify_probe(status=200, url="https://example.org/old", final_url="https://example.org/new", content_type="application/pdf") == "redirect"
    assert classify_probe(status=200, url="https://example.org/gone", content_type="text/html", body="<html>page not found</html>") == "soft_404"
    assert classify_probe(status=404, url="https://example.org/a") == "hard_dead"
    assert classify_probe(status=None, url="https://example.org/a", error="ConnectError") == "hard_dead"
    assert classify_probe(status=410, url="https://example.org/a") == "hard_dead"
    wall = "Please subscribe to continue reading this article. " * 5
    assert classify_probe(status=200, url="https://example.org/pay", content_type="text/html", body=wall) == "paywall_html"
    assert planned_rewrite("https://example.org/not-a-playbook") is None


def test_url_findings_and_rewrite_refusal():
    assert classify_probe(status=404, url="https://example.org/a") == "hard_dead"
    assert classify_probe(status=None, url="https://example.org/a", error="ConnectError") == "hard_dead"
    assert (
        classify_probe(
            status=200,
            url="https://example.org/a",
            content_type="text/html",
            body="Please subscribe to continue reading this article. " * 5,
        )
        == "paywall_html"
    )
    assert (
        classify_probe(
            status=200,
            url="https://example.org/old",
            final_url="https://example.org/new",
            content_type="application/pdf",
        )
        == "redirect"
    )
    assert planned_rewrite("https://example.org/not-a-playbook") is None


def test_print_refusal_blocks_landing_pages():
    article = "Mesopelagic harvest rules for the high seas. " * 80
    assert print_page_refusal("https://pub.test/a", article) is None
    assert print_page_refusal("https://pub.test/a", "Download PDF\n" + article) == "native-pdf-offered"
    assert print_page_refusal("https://pub.test/login", "Central Authentication Service password") == "login"
    assert print_page_refusal("https://pub.test/c", "We use cookies. Accept all cookies.") == "cookie-wall"
    assert print_page_refusal("https://pub.test/a", "subscribe to continue " * 20) == "paywall"
    assert (
        print_page_refusal(
            "https://pub.test/a",
            "short",
            title="Mesopelagic harvest rules for the high seas",
            require_article=True,
        )
        == "short-page"
    )


def test_academic_htmlpdf_off_skips_journal(ctx_factory):
    ctx = ctx_factory(lambda r: None)
    cand = find(make_item(item_type="journalArticle", url="https://pub.test/a"), ctx)
    assert cand.outcome is Outcome.SKIPPED
    assert academic_mode(make_item(), ctx.config) == "off"


def test_academic_gated_writes_proposal(ctx_factory, monkeypatch, tmp_path):
    from paperful.sources import htmlpdf

    monkeypatch.setattr(htmlpdf, "playwright_available", lambda: True)
    monkeypatch.setattr(
        htmlpdf,
        "_render_pdf",
        lambda url, ua, title="", require_article=False, **_k: (PDF_BYTES, url, "chromium print"),
    )
    ctx = ctx_factory(lambda r: None)
    ctx.config.state_dir = tmp_path
    ctx.config.htmlpdf_academic = "gated"
    item = make_item(key="J1", item_type="journalArticle", url="https://pub.test/article")
    cand = find(item, ctx)
    assert cand.outcome is Outcome.SKIPPED
    assert "proposal" in cand.note
    assert (tmp_path / "htmlpdf" / "proposals" / "J1.json").is_file()


def test_snapshot_is_not_import_ok_and_upgrade_selects_it():
    assert provenance_label("htmlpdf") == "snapshot:htmlpdf"
    assert provenance_stamp("htmlpdf") == "paperful snapshot:htmlpdf"
    assert is_snapshot_note(provenance_stamp("htmlpdf"))
    assert project_miss_surface(doi="10.1/x", has_pdf=True, status=STATUS_ATTACHED, source="htmlpdf") == "snapshot"
    snap = make_item(key="S", has_pdf=True, pdf_tier="snapshot")
    native = make_item(key="N", has_pdf=True, pdf_tier="native")
    assert items_without_stored_pdf([snap, native]) == []
    assert items_without_stored_pdf([snap, native], upgrade_snapshot=True) == [snap]


def test_academic_htmlpdf_moves_after_browser_agent():
    from paperful.config import Config

    cfg = Config()
    cfg.htmlpdf_academic = "auto"
    journal = make_item(url="https://pub.test/a")
    web = make_item(key="W", doi=None, item_type="webpage", url="https://news.test/a")
    base = ["unpaywall", "ezproxy", "htmlpdf", "browser_agent", "scihub"]
    assert place_academic_htmlpdf(base, cfg, journal) == [
        "unpaywall",
        "ezproxy",
        "browser_agent",
        "htmlpdf",
        "scihub",
    ]
    assert place_academic_htmlpdf(base, cfg, web) == base
    journal = make_item(url="https://pub.test/a")
    cfg.htmlpdf_academic = "off"
    assert source_applicable(journal, cfg, "htmlpdf") is False
    cfg.htmlpdf_academic = "auto"
    assert source_applicable(journal, cfg, "htmlpdf") is True
    journal.pdf_tier = "snapshot"
    assert source_applicable(journal, cfg, "htmlpdf") is False


def test_proposal_gate_rechecks_saved_page():
    from paperful.sources.htmlpdf import proposal_gate

    title = "Mesopelagic harvest rules for the high seas"
    assert proposal_gate({"title": title, "url": "https://pub.test/a", "body": ""}) == "no page text"
    assert proposal_gate({"title": title, "url": "https://pub.test/a", "body": "Download PDF"}) == "native-pdf-offered"
    article = f"{title}. " + ("The fishery stayed open through the season. " * 40)
    assert proposal_gate({"title": title, "url": "https://pub.test/a", "body": article}) is None


def test_native_attach_trashes_snapshot_child():
    from paperful.pipeline import _drop_snapshot_attachments
    from paperful.provenance import provenance_stamp

    trashed: list[str] = []

    class Attacher:
        def children(self, key: str) -> list[dict]:
            assert key == "ITEM"
            return [
                {"key": "SNAP", "data": {"linkMode": "imported_file", "contentType": "application/pdf", "note": provenance_stamp("htmlpdf")}},
                {"key": "REAL", "data": {"linkMode": "imported_file", "contentType": "application/pdf", "note": "paperful oa:unpaywall"}},
            ]

        def trash_attachment(self, key: str) -> None:
            trashed.append(key)

    notes: list[str] = []
    _drop_snapshot_attachments(Attacher(), "ITEM", notes.append)
    assert trashed == ["SNAP"]
    assert any("replaced snapshot" in line for line in notes)


def test_ambiguous_grey_fingerprint_does_not_attach(monkeypatch, tmp_path):
    from paperful.config import Config
    from paperful.inbox_match import match_ladder

    title = "Shared grey title about fisheries management"
    monkeypatch.setattr("paperful.inbox_match.text_from_pdf", lambda *_a, **_k: "copy at https://www.fao.org/doc")
    monkeypatch.setattr("paperful.inbox_match.doi_from_pdf", lambda *_a, **_k: None)
    monkeypatch.setattr("paperful.inbox_match.pdf_title_year", lambda *_a, **_k: (title, 2022))
    items = [
        make_item(key="A", doi=None, title=title, year=2022, url="https://www.fao.org/a", has_pdf=False),
        make_item(key="B", doi=None, title=title, year=2022, url="https://www.fao.org/b", has_pdf=False),
    ]
    cfg = Config()
    cfg.inbox_match = "doi+title"
    pdf = tmp_path / "drop.pdf"
    pdf.write_bytes(b"%PDF")
    result = match_ladder(pdf, cfg=cfg, doi_index={}, title_index={}, missing_items=items)
    assert result.item is None
    assert result.reason == "ambiguous grey fingerprint"


def test_handoff_prefers_dead_url_health(tmp_path):
    import json

    from paperful.handoff import MissingPdf
    from paperful.handoff_rank import rank_missing

    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "20260101T000000Z-urls.json").write_text(
        json.dumps(
            {
                "items": [
                    {"item_key": "DEAD", "code": "hard_dead"},
                    {"item_key": "OK", "code": "ok"},
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = [
        MissingPdf(key="OK", title="Aaa", doi="", url="https://ok.test", hint="doi_only", attempts=[]),
        MissingPdf(key="DEAD", title="Zzz", doi="", url="https://dead.test", hint="doi_only", attempts=[]),
    ]
    assert [row.key for row in rank_missing(rows, tmp_path)] == ["DEAD", "OK"]
