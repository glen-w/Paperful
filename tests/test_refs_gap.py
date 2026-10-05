"""Bibliography gap scan: cited in PDF, missing from library."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.identity import LibraryFingerprint
from paperful.refs_gap import SCHEMA, aggregate_citations, scan_pdf_citations, write_pack
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
        [make_item(key="OWN", doi="10.1000/owned", title="Owned already title", year=2020)]
    )
    refs = aggregate_citations([("SEED", entries)], fp)
    missing = [r for r in refs if not r.already_exists]
    owned = [r for r in refs if r.already_exists]
    assert any(r.doi == "10.1000/a" and r.suggested_action == "ingest-dois" for r in missing)
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
