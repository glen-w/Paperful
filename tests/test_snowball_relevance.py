"""Snowball relevance gates (hop overlap, cites query inheritance, ORCID seed map)."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.e2e_nba import extract_orcid_seed_map, extract_orcids_from_candidates
from paperful.snowball.candidate import Candidate
from paperful.snowball.command import _inherit_cites_query
from paperful.snowball.relevance import filter_hop_neighbors, hop_overlap


def test_inherit_cites_query_from_keyword_seed():
    q = _inherit_cites_query(
        '("mCDR" OR geoengineering)',
        "",
        "refs+keywords",
        depth=1,
    )
    assert "mCDR" in q


def test_hop_overlap_uses_max_of_seed_keyword_and_ref():
    row = Candidate(
        run_id="r",
        seed={"type": "keyword", "value": "mcdr"},
        hop=1,
        direction="refs",
        ids={},
        biblio={"keyword_overlap": 2, "ref_overlap": 1, "seed_keys": ["a"]},
        why="",
        status="new",
        provenance={},
        gate="dry-run",
    )
    assert hop_overlap(row) == 2


def test_hop_overlap_empty_biblio_is_zero():
    row = Candidate(
        run_id="r",
        seed={"type": "keyword", "value": "x"},
        hop=1,
        direction="refs",
        ids={},
        biblio={},
        why="",
        status="new",
        provenance={},
        gate="dry-run",
    )
    assert hop_overlap(row) == 0


def test_filter_hop_neighbors_without_overlap():
    rows = [
        Candidate(
            run_id="r",
            seed={"type": "keyword", "value": "mcdr"},
            hop=1,
            direction="refs",
            ids={"openalex": "W1"},
            biblio={},
            why="refs",
            status="new",
            provenance={},
            gate="dry-run",
        )
    ]
    filter_hop_neighbors(rows, min_overlap=1)
    assert rows[0].status == "filtered"
    assert "hop_overlap" in (rows[0].why or "")


def _keyword_hop1(**biblio) -> Candidate:
    return Candidate(
        run_id="r",
        seed={"type": "keyword", "value": "mcdr"},
        hop=1,
        direction="refs",
        ids={"openalex": "W1"},
        biblio=biblio,
        why="refs",
        status="new",
        provenance={},
        gate="dry-run",
    )


def test_filter_hop_neighbors_disabled_when_min_overlap_zero():
    rows = [_keyword_hop1()]
    filter_hop_neighbors(rows, min_overlap=0)
    assert rows[0].status == "new"


def test_filter_hop_neighbors_skips_when_cites_query_set():
    rows = [_keyword_hop1()]
    filter_hop_neighbors(rows, min_overlap=1, cites_query="mcdr")
    assert rows[0].status == "new"


def test_filter_hop_neighbors_keeps_hop_zero():
    row = _keyword_hop1()
    row.hop = 0
    filter_hop_neighbors([row], min_overlap=1)
    assert row.status == "new"


def test_filter_hop_neighbors_skips_non_keyword_seed_when_keyword_seed_true():
    row = _keyword_hop1()
    row.seed = {"type": "doi", "value": "10.1/seed"}
    filter_hop_neighbors([row], min_overlap=1, keyword_seed=True)
    assert row.status == "new"


def test_filter_hop_neighbors_keeps_row_with_sufficient_overlap():
    row = _keyword_hop1(keyword_overlap=1)
    filter_hop_neighbors([row], min_overlap=1)
    assert row.status == "new"


def test_filter_hop_neighbors_appends_why_once():
    row = _keyword_hop1()
    row.why = "refs (hop_overlap)"
    filter_hop_neighbors([row], min_overlap=1)
    assert row.status == "filtered"
    assert row.why.count("hop_overlap") == 1


def test_extract_orcids_ignores_hop1_regex_leak(tmp_path: Path):
    queue = tmp_path / "candidates.jsonl"
    hop0 = {
        "hop": 0,
        "status": "new",
        "seed": {"type": "keyword", "value": "mcdr"},
        "ids": {"doi": "10.1000/seed"},
        "biblio": {
            "author_records": [
                {"orcid": "0000-0001-2345-6789", "display_name": "On Seed"}
            ]
        },
    }
    hop1 = {
        "hop": 1,
        "status": "new",
        "seed": {"type": "keyword", "value": "mcdr"},
        "biblio": {
            "author_records": [
                {"orcid": "0000-0002-9999-9999", "display_name": "Random Cited"}
            ]
        },
    }
    queue.write_text(
        json.dumps(hop0) + "\n" + json.dumps(hop1) + "\n", encoding="utf-8"
    )
    got = extract_orcids_from_candidates(queue, limit=5)
    assert got == ["0000-0001-2345-6789"]
    smap = extract_orcid_seed_map(queue, limit=5)
    assert smap["0000-0001-2345-6789"] == ["10.1000/seed"]
