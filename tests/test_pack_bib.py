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
