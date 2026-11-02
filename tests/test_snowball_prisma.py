"""PRISMA counts and watch drift hashes. Additive; no recall percentage."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from rich.console import Console

from paperful.runreport import RUN_REPORT_SUMMARY_KEYS
from paperful.snowball.candidate import Candidate
from paperful.snowball.openalex import OpenAlexClient
from paperful.snowball.prisma import prisma_counts, prisma_from_stop
from paperful.snowball.queue import write_queue
from paperful.snowball.response_cache import (
    DRIFT_METADATA,
    DRIFT_NEW,
    DRIFT_REASSIGNED,
    DRIFT_UNCHANGED,
    SCHEMA,
    candidate_hash,
    classify_row,
    classify_rows,
    load_cache,
)
from paperful.config import load_config


def _cfg(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n[snowball]\nenabled = true\n'
    )
    return load_config(path)


def _row(
    *,
    doi: str = "10.1000/a",
    title: str = "Alpha",
    year: int = 2020,
    oa: str = "W1",
    cites: int = 1,
    keep: bool | None = None,
) -> Candidate:
    return Candidate(
        "r",
        {"type": "doi", "value": doi},
        0,
        "search",
        {"doi": doi, "openalex": f"https://openalex.org/{oa}"},
        {
            "title": title,
            "year": year,
            "type": "article",
            "cited_by_count": cites,
        },
        "hit",
        "new",
        {"backend": "openalex"},
        "dry-run",
        keep=keep,
    )


def test_prisma_keys_are_not_frozen_run_report_keys():
    assert "prisma" not in RUN_REPORT_SUMMARY_KEYS
    assert "watch_drift" not in RUN_REPORT_SUMMARY_KEYS


def test_prisma_counts_identified_screened_kept_added():
    rows = [
        _row(doi="10.1000/a", keep=True),
        _row(doi="10.1000/b", keep=False, oa="W2"),
        _row(doi="10.1000/c", keep=None, oa="W3"),
    ]
    assert prisma_counts(rows, added=2) == {
        "identified": 3,
        "screened": 3,
        "kept": 1,
        "added": 2,
    }
    assert prisma_counts(rows, added=0, screened=10)["screened"] == 10


def test_prisma_from_stop_reads_stop_json(tmp_path: Path):
    dest = tmp_path / "run"
    dest.mkdir()
    (dest / "stop.json").write_text(
        json.dumps(
            {
                "schema": "paperful.snowball.stop.v1",
                "history": [
                    {"iteration": 1, "screened": 4, "included": 1},
                    {"iteration": 2, "screened": 3, "included": 0},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert prisma_from_stop(dest=dest) == 7
    assert prisma_from_stop({"stop": {"history": [{"screened": 2}]}}) == 2


def test_write_queue_adds_prisma(tmp_path: Path):
    cfg = _cfg(tmp_path)
    client = OpenAlexClient(email="t@example.org", sleep_s=0)
    dest = write_queue(
        cfg.state_dir,
        "runp",
        [_row(keep=True), _row(doi="10.1000/b", oa="W2")],
        client,
        library_unread=False,
    )
    summary = json.loads((dest / "summary.json").read_text(encoding="utf-8"))
    assert summary["prisma"] == {
        "identified": 2,
        "screened": 2,
        "kept": 1,
        "added": 0,
    }


def test_classify_row_new_unchanged_metadata_reassigned():
    row = _row()
    digest = candidate_hash(row)
    assert classify_row(None, row, digest) == DRIFT_NEW
    assert (
        classify_row({"sha256": digest, "openalex_id": row.ids["openalex"]}, row, digest)
        == DRIFT_UNCHANGED
    )
    retitled = _row(title="Alpha (revised)")
    other = candidate_hash(retitled)
    assert (
        classify_row(
            {"sha256": digest, "openalex_id": row.ids["openalex"]},
            retitled,
            other,
        )
        == DRIFT_METADATA
    )
    moved = _row(oa="W9")
    moved_hash = candidate_hash(moved)
    assert (
        classify_row(
            {"sha256": digest, "openalex_id": row.ids["openalex"]},
            moved,
            moved_hash,
        )
        == DRIFT_REASSIGNED
    )


def test_classify_rows_persists_responses_json(tmp_path: Path):
    folder = tmp_path / "watch"
    first = classify_rows(folder, [_row(), _row(doi="10.1000/b", oa="W2")])
    assert first[DRIFT_NEW] == 2
    cache = load_cache(folder)
    assert cache["schema"] == SCHEMA
    assert len(cache["entries"]) == 2
    second = classify_rows(folder, [_row(), _row(doi="10.1000/b", oa="W2")])
    assert second[DRIFT_UNCHANGED] == 2
    assert second[DRIFT_NEW] == 0
    third = classify_rows(
        folder,
        [_row(title="Alpha renamed"), _row(doi="10.1000/b", oa="W2")],
    )
    assert third[DRIFT_METADATA] == 1
    assert third[DRIFT_UNCHANGED] == 1


def test_watch_run_writes_prisma_and_drift(tmp_path: Path):
    from paperful.snowball.profile import save_profile
    from paperful.snowball.watch import run_watch, save_watch, watch_dir

    cfg = _cfg(tmp_path)
    (tmp_path / "profiles").mkdir()
    save_profile(
        cfg,
        "keyword-scout",
        {"mode": "search", "query": "bbnj", "gate": "dry-run"},
        force=False,
    )
    save_watch(cfg, "bbnj", "keyword-scout")

    def work(oa: str, doi: str, title: str, year: int, cites: int) -> dict:
        return {
            "id": f"https://openalex.org/{oa}",
            "doi": f"https://doi.org/{doi}",
            "display_name": title,
            "publication_year": year,
            "type": "article",
            "cited_by_count": cites,
            "referenced_works": [],
            "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
            "primary_location": {"source": {"display_name": "Marine Policy"}},
        }

    works = {
        "W1": work("W1", "10.1000/a", "Alpha", 2020, 1),
        "W2": work("W2", "10.1000/b", "Beta", 2021, 2),
    }

    def getter(path: str, params: dict) -> dict:
        if "search" in params:
            return {"results": list(works.values())}
        return {"results": []}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    console = Console(file=StringIO(), highlight=False, width=120)
    first = run_watch(
        cfg,
        "bbnj",
        console=console,
        client=client,
        lookup=lambda doi, title: None,
    )
    assert first.prisma == {
        "identified": 2,
        "screened": 2,
        "kept": 0,
        "added": 0,
    }
    assert first.watch_drift[DRIFT_NEW] == 2
    summary = json.loads((first.run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["prisma"]["identified"] == 2
    assert summary["watch_drift"][DRIFT_NEW] == 2
    cache = json.loads(
        (watch_dir(cfg, "bbnj") / "responses.json").read_text(encoding="utf-8")
    )
    assert cache["schema"] == SCHEMA
    assert len(cache["entries"]) == 2

    works["W3"] = work("W3", "10.1000/c", "Gamma", 2022, 3)
    second = run_watch(
        cfg,
        "bbnj",
        console=console,
        client=client,
        lookup=lambda doi, title: None,
    )
    assert second.prisma["identified"] == 3
    assert second.prisma["kept"] == 1
    assert second.watch_drift[DRIFT_NEW] == 1
    assert second.watch_drift[DRIFT_UNCHANGED] == 2


def test_watch_refresh_skips_from_created_date(tmp_path: Path):
    from paperful.snowball.profile import save_profile
    from paperful.snowball.watch import run_watch, save_watch

    cfg = _cfg(tmp_path)
    (tmp_path / "profiles").mkdir()
    save_profile(
        cfg,
        "scout",
        {"mode": "search", "query": "bbnj", "gate": "dry-run"},
        force=False,
    )
    save_watch(cfg, "w", "scout")
    works = {
        "W1": {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1000/a",
            "display_name": "Alpha",
            "publication_year": 2020,
            "type": "article",
            "cited_by_count": 1,
            "referenced_works": [],
            "authorships": [],
            "primary_location": {},
        }
    }
    filters: list[str] = []

    def getter(path: str, params: dict) -> dict:
        filt = str(params.get("filter") or "")
        if "search" in params or filt:
            filters.append(filt)
        if "search" in params:
            return {"results": list(works.values())}
        return {"results": []}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    console = Console(file=StringIO(), highlight=False, width=120)
    run_watch(cfg, "w", console=console, client=client, lookup=lambda doi, title: None)
    filters.clear()
    run_watch(
        cfg,
        "w",
        console=console,
        client=client,
        lookup=lambda doi, title: None,
        refresh=True,
    )
    assert all("from_created_date:" not in f for f in filters)
