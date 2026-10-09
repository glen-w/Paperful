"""Proposal pack → BibTeX / RIS (roadmap 22 wave 1)."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.pack_bib import dump_candidates, export_pack_text, resolve_candidate_jsonl
from paperful.snowball.candidate import Candidate


def _sample_candidate() -> Candidate:
    return Candidate(
        run_id="run1",
        seed={"kind": "keyword", "value": "bbnj"},
        hop=0,
        direction="keywords",
        ids={"doi": "10.1234/example"},
        biblio={
            "title": "Marine biodiversity treaty",
            "year": 2024,
            "authors": ["Ada Lovelace", "Alan Turing"],
            "type": "article",
            "venue": "Ocean Policy",
        },
        why="keyword hit",
        status="new",
        provenance={"backend": "openalex"},
        gate="dry-run",
    )


def test_dump_candidates_bibtex():
    text = dump_candidates([_sample_candidate()], "bibtex")
    assert "10.1234/example" in text
    assert "Marine biodiversity" in text


def test_resolve_and_export_pack(tmp_path: Path):
    run_dir = tmp_path / "snowball" / "20260101-test"
    run_dir.mkdir(parents=True)
    line = json.dumps(_sample_candidate().to_dict())
    (run_dir / "candidates.jsonl").write_text(line + "\n", encoding="utf-8")
    assert resolve_candidate_jsonl(run_dir).name == "candidates.jsonl"
    text, jsonl, n = export_pack_text(run_dir, "ris")
    assert n == 1
    assert jsonl.is_file()
    assert "TY  -" in text


def test_authorwatch_inbox_jsonl(tmp_path: Path):
    watch_dir = tmp_path / "authorwatch" / "voices"
    watch_dir.mkdir(parents=True)
    line = json.dumps(_sample_candidate().to_dict())
    (watch_dir / "inbox.jsonl").write_text(line + "\n", encoding="utf-8")
    assert resolve_candidate_jsonl(watch_dir).name == "inbox.jsonl"


def test_resolve_rejects_missing_pack_and_non_jsonl(tmp_path: Path):
    empty = tmp_path / "empty-pack"
    empty.mkdir()
    try:
        resolve_candidate_jsonl(empty)
    except FileNotFoundError as exc:
        assert "candidates.jsonl" in str(exc)
    else:
        raise AssertionError("empty pack should fail")
    missing = tmp_path / "no-such"
    try:
        resolve_candidate_jsonl(missing)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing pack should fail")
    note = tmp_path / "notes.txt"
    note.write_text("not jsonl", encoding="utf-8")
    try:
        resolve_candidate_jsonl(note)
    except FileNotFoundError as exc:
        assert ".jsonl" in str(exc)
    else:
        raise AssertionError("non-jsonl file should fail")


def test_candidate_mapping_types_authors_and_empty_rows():
    from paperful.pack_bib import candidate_to_record, dump_candidates

    preprint = _sample_candidate()
    preprint.biblio = {
        "title": "A preprint",
        "year": 2020,
        "authors": ["FAO"],
        "type": "posted-content",
    }
    preprint.ids = {"openalex": "W123"}
    rec = candidate_to_record(preprint)
    assert rec is not None
    assert rec["item_type"] == "preprint"
    assert rec["creators"] == [{"creatorType": "author", "name": "FAO"}]
    assert rec["url"] == "https://openalex.org/W123"

    book = _sample_candidate()
    book.biblio = {"title": "A book", "type": "book", "authors": []}
    assert candidate_to_record(book)["item_type"] == "book"
    chapter = _sample_candidate()
    chapter.biblio = {"title": "A chapter", "type": "book-chapter", "authors": []}
    assert candidate_to_record(chapter)["item_type"] == "bookSection"
    other = _sample_candidate()
    other.biblio = {"title": "A talk", "type": "speech", "authors": []}
    assert candidate_to_record(other)["item_type"] == "document"

    empty = _sample_candidate()
    empty.biblio = {"title": "  ", "authors": []}
    empty.ids = {}
    assert candidate_to_record(empty) is None
    try:
        dump_candidates([empty], "bibtex")
    except ValueError as exc:
        assert "title or DOI" in str(exc)
    else:
        raise AssertionError("empty rows should not export")
