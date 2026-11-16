"""Bibliography gap scan: cited in PDF, missing from library."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.identity import LibraryFingerprint
from paperful.refs_gap import (
    SCHEMA,
    aggregate_citations,
    scan_pdf_citations,
    write_pack,
)
from tests.conftest import make_item

BIBLIO = """
Intro.

References
[1] Ada. (2019). First paper title. Journal.
https://doi.org/10.1000/a
[2] Bea. (2020). Owned already title. Journal.
https://doi.org/10.1000/owned
"""


def test_scan_pdf_citations_needs_ocr(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr("paperful.refs_gap.text_from_pdf", lambda *_a, **_k: "")
    entries, finding = scan_pdf_citations(pdf)
    assert finding == "needs_ocr"
    assert entries == []


def test_aggregate_and_pack(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("paperful.refs_gap.text_from_pdf", lambda *_a, **_k: BIBLIO)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 text")
    entries, finding = scan_pdf_citations(pdf)
    assert finding == "ok"
    dois = {e["doi"] for e in entries}
    assert "10.1000/a" in dois
    fp = LibraryFingerprint.from_items(
        [
            make_item(
                key="OWN", doi="10.1000/owned", title="Owned already title", year=2020
            )
        ]
    )
    refs = aggregate_citations([("SEED", entries)], fp)
    missing = [r for r in refs if not r.already_exists]
    owned = [r for r in refs if r.already_exists]
    assert any(
        r.doi == "10.1000/a" and r.suggested_action == "ingest-dois" for r in missing
    )
    assert owned and owned[0].suggested_action == "skip"
    folder = write_pack(tmp_path, "BBNJ", refs, [])
    pack = folder / "pack.json"
    assert pack.is_file()
    text = pack.read_text(encoding="utf-8")
    assert SCHEMA in text
    data = json.loads(text)
    assert data["schema"] == SCHEMA
    row = next(r for r in data["rows"] if r["doi"] == "10.1000/a")
    assert row["cited_by_count_in_scope"] >= 1
    assert row["suggested_action"] == "ingest-dois"
    assert row["already_exists"] is False
    assert "citing_keys" in row
    assert "oa_hint" in row
    dois_txt = (folder / "dois.txt").read_text(encoding="utf-8")
    assert "10.1000/a" in dois_txt
    assert "10.1000/owned" not in dois_txt


def _refs(sources, owned=()):
    fp = LibraryFingerprint.from_items(
        [
            make_item(key=f"OWN{i}", doi=doi, title=f"Owned {i}")
            for i, doi in enumerate(owned)
        ]
    )
    return aggregate_citations(sources, fp)


def test_memory_rerun_is_still_missing_with_stable_first_seen(tmp_path: Path):
    from datetime import datetime, timezone

    from paperful.refs_gap import apply_memory, read_memory

    sources = [("SEED", [{"doi": "10.1000/a", "title": "A", "year": 2019}])]
    day1 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    first = _refs(sources)
    assert apply_memory(tmp_path, "BBNJ", first, now=day1) == []
    assert first[0].delta == "new"

    again = _refs(sources)
    apply_memory(
        tmp_path, "BBNJ", again, now=datetime(2026, 11, 15, tzinfo=timezone.utc)
    )
    assert again[0].delta == "still_missing"
    assert again[0].first_seen == day1.isoformat()
    row = read_memory(tmp_path, "BBNJ")["10.1000/a"]
    assert row["cited_by_count_in_scope"] == 1
    assert row["first_seen"] == day1.isoformat()
    # Another scope starts its own memory.
    assert read_memory(tmp_path, "other") == {}


def test_memory_now_owned_cite_count_up_and_gone(tmp_path: Path):
    from paperful.refs_gap import apply_memory, read_memory

    a = {"doi": "10.1000/a", "title": "A", "year": 2019}
    b = {"doi": "10.1000/b", "title": "B", "year": 2020}
    c = {"doi": "10.1000/c", "title": "C", "year": 2021}
    apply_memory(tmp_path, "S", _refs([("K1", [a, b, c])]))

    refs = _refs([("K1", [a, b]), ("K2", [b])], owned=["10.1000/a"])
    gone = apply_memory(tmp_path, "S", refs)
    by_doi = {r.doi: r for r in refs}
    assert by_doi["10.1000/a"].delta == "now_owned"
    assert by_doi["10.1000/a"].already_exists
    assert by_doi["10.1000/b"].delta == "cite_count_up"
    assert [g["doi"] for g in gone] == ["10.1000/c"]
    memory = read_memory(tmp_path, "S")
    assert memory["10.1000/a"]["delta"] == "now_owned"
    assert memory["10.1000/c"]["delta"] == "gone_from_drafts"

    folder = write_pack(tmp_path, "S", refs, [], gone=gone)
    data = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    assert data["memory"]["now_owned"] == 1
    assert data["memory"]["gone_from_drafts"] == [{"doi": "10.1000/c", "title": "C"}]
    assert "10.1000/a" not in (folder / "dois.txt").read_text(encoding="utf-8")

    # An owned work stays quiet on later runs, and a returning cite keeps its date.
    later = _refs([("K1", [a, c])], owned=["10.1000/a"])
    apply_memory(tmp_path, "S", later)
    by_doi = {r.doi: r for r in later}
    assert by_doi["10.1000/a"].delta == ""
    assert by_doi["10.1000/c"].delta == "still_missing"
    assert by_doi["10.1000/c"].first_seen == memory["10.1000/c"]["first_seen"]


def test_debt_score_puts_draft_cites_first_then_age(tmp_path: Path):
    from datetime import datetime, timezone

    from paperful.refs_gap import CiteRef, debt_score

    now = datetime(2026, 11, 29, tzinfo=timezone.utc)
    old = CiteRef(
        doi="10.1/old", citing_keys=["K1"], first_seen="2026-11-01T00:00:00+00:00"
    )
    fresh = CiteRef(
        doi="10.1/new", citing_keys=["K1", "K2"], first_seen=now.isoformat()
    )
    draft = CiteRef(doi="10.1/draft", citing_keys=["pdf:draft.pdf"])
    ranked = sorted(
        [fresh, old, draft], key=lambda r: debt_score(r, now=now), reverse=True
    )
    assert [r.doi for r in ranked] == ["10.1/draft", "10.1/old", "10.1/new"]
