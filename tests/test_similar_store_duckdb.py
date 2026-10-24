"""Similar map against a real local DuckDB parquet store (skipped without duckdb)."""

from __future__ import annotations

import shutil

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

DUCKDB = shutil.which("duckdb")
pytestmark = pytest.mark.skipif(DUCKDB is None, reason="duckdb CLI not on PATH")


def _u(oa: str) -> str:
    return f"https://openalex.org/{oa}"


def test_similar_map_from_local_store_without_api(tmp_path, monkeypatch):
    from paperful.config import Config
    from paperful.snowball.local_openalex import store_from_config
    from paperful.snowball.similar_explore import start_similar_explore
    from paperful.snowball.similar_settings import from_mapping

    refs = [f"W{100 + i}" for i in range(12)]
    rows = [
        dict(id=_u("W1"), doi="https://doi.org/10.1000/seed", display_name="Seed",
             publication_year=2015, type="article", cited_by_count=50,
             referenced_works=[_u(r) for r in refs[:8]]),
    ]
    for r in refs:
        rows.append(dict(id=_u(r), doi=None, display_name=f"Ref {r}", publication_year=2005,
                         type="article", cited_by_count=10, referenced_works=[_u("W999")]))
    for i in range(20):
        cited = refs[i % 6 : i % 6 + 5] + (["W1"] if i % 2 else [])
        rows.append(dict(id=_u(f"W{300 + i}"), doi=f"https://doi.org/10.1000/p{i}",
                         display_name=f"Paper {i}", publication_year=2018 + i % 5,
                         type="article", cited_by_count=i,
                         referenced_works=[_u(r) for r in cited]))
    works = tmp_path / "works" / "updated_date=2025-01-01"
    works.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), works / "part_000.parquet")

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.openalex_store_backend = "local_duckdb"
    cfg.openalex_store_duckdb_bin = DUCKDB
    cfg.openalex_store_parquet_glob = str(tmp_path / "works" / "**" / "*.parquet")
    store = store_from_config(cfg)
    store.build_cites_index(str(tmp_path / "cites"), memory_limit="1GB")
    cfg.openalex_store_cites_index_glob = str(tmp_path / "cites" / "**" / "*.parquet")
    cfg.similar_map = from_mapping({"source": "store", "nodes": 10})
    monkeypatch.setattr("paperful.snowball.command.get_backend", lambda _c: None)

    _, graph = start_similar_explore(cfg, query="10.1000/seed")
    report = graph["similar"]
    assert report["api_calls"] == 0
    assert report["source"] == "store"
    assert report["pool_steps"]["references"] > 0
    assert report["pool_steps"]["citers"] > 0
    assert 5 < len(graph["nodes"]) <= 11
    assert graph["edges"]
