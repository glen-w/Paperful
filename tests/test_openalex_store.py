"""OpenAlex snapshot store: SQL helpers, SSH runner, client merge with API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from paperful.config import Config, load_config
from paperful.snowball.local_openalex import (
    OpenAlexStoreError,
    SshDuckDbStore,
    build_works_sql,
    columns_for_select,
    normalize_store_doi,
    normalize_store_id,
    parse_duckdb_json,
    store_from_config,
)
from paperful.snowball.openalex import OpenAlexClient


class FakeStore:
    def __init__(self, works: list[dict[str, Any]] | None = None, *, fail: bool = False):
        self.works = list(works or [])
        self.fail = fail
        self.doi_calls: list[list[str]] = []
        self.id_calls: list[list[str]] = []

    def work_by_doi(self, doi: str) -> dict[str, Any] | None:
        rows = self.works_by_dois([doi])
        return rows[0] if rows else None

    def works_by_dois(
        self, dois: list[str], *, select: str = "id,doi,referenced_works"
    ) -> list[dict[str, Any]]:
        if self.fail:
            raise RuntimeError("store down")
        self.doi_calls.append(list(dois))
        want = {normalize_store_doi(d) for d in dois}
        return [
            row
            for row in self.works
            if normalize_store_doi(str(row.get("doi") or "")) in want
        ]

    def works_by_ids(self, openalex_ids: list[str]) -> list[dict[str, Any]]:
        if self.fail:
            raise RuntimeError("store down")
        self.id_calls.append(list(openalex_ids))
        want = {normalize_store_id(i) for i in openalex_ids}
        return [
            row
            for row in self.works
            if normalize_store_id(str(row.get("id") or "")) in want
        ]


def test_columns_for_select_rejects_unknown():
    assert columns_for_select("id,doi") == ["id", "doi"]
    with pytest.raises(OpenAlexStoreError):
        columns_for_select("id,not_a_column")


def test_build_works_sql_doi_and_id():
    sql = build_works_sql(
        parquet_glob="/data/**/*.parquet",
        columns=["id", "doi"],
        dois=["10.1234/Abc", "https://doi.org/10.5678/x"],
    )
    assert "read_parquet('/data/**/*.parquet'" in sql
    assert "10.1234/abc" in sql
    assert "10.5678/x" in sql
    assert "IN (" in sql

    sql_ids = build_works_sql(
        parquet_glob="/data/**/*.parquet",
        columns=["id", "doi"],
        openalex_ids=["https://openalex.org/W1", "W2"],
    )
    assert "'W1'" in sql_ids
    assert "'W2'" in sql_ids

    with pytest.raises(OpenAlexStoreError):
        build_works_sql(parquet_glob="/x", columns=["id"], dois=["a"], openalex_ids=["W1"])


def test_parse_duckdb_json():
    assert parse_duckdb_json("") == []
    assert parse_duckdb_json('[{"id":"W1"}]') == [{"id": "W1"}]
    assert parse_duckdb_json('{"id":"W1"}') == [{"id": "W1"}]


def test_ssh_store_uses_runner(monkeypatch):
    seen: dict[str, Any] = {}

    def runner(**kwargs: Any) -> str:
        seen.update(kwargs)
        return '[{"id":"https://openalex.org/W9","doi":"https://doi.org/10.1234/x"}]'

    store = SshDuckDbStore(
        ssh_host="nuc",
        ssh_user="me",
        parquet_glob="/mnt/files/openalex/data/parquet/**/*.parquet",
        runner=runner,
    )
    rows = store.works_by_ids(["W9"])
    assert rows[0]["id"].endswith("W9")
    assert seen["host"] == "nuc"
    assert seen["user"] == "me"
    assert "read_parquet" in seen["sql"]
    assert "W9" in seen["sql"]


def test_store_from_config_off_and_ssh(tmp_path: Path, monkeypatch):
    assert store_from_config(Config()) is None

    path = tmp_path / "config.toml"
    path.write_text(
        'email = "t@example.org"\n'
        f'out_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
        "[openalex_store]\n"
        'backend = "ssh_duckdb"\n'
        'ssh_host = "nuc"\n'
        'parquet_glob = "/data/**/*.parquet"\n'
    )
    cfg = load_config(path)
    store = store_from_config(cfg)
    assert isinstance(store, SshDuckDbStore)
    assert store.ssh_host == "nuc"

    monkeypatch.setenv("OPENALEX_STORE_SSH_HOST", "from-env")
    monkeypatch.setenv("OPENALEX_STORE_PARQUET_GLOB", "/env/**/*.parquet")
    bare = Config()
    bare.openalex_store_backend = "ssh_duckdb"
    env_store = store_from_config(bare)
    assert isinstance(env_store, SshDuckDbStore)
    assert env_store.ssh_host == "from-env"

    with pytest.raises(OpenAlexStoreError):
        bad = Config()
        bad.openalex_store_backend = "http"
        store_from_config(bad)


def test_client_store_hit_skips_http():
    http_calls: list[tuple[str, dict[str, Any]]] = []

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        http_calls.append((path, params))
        return {"results": []}

    store = FakeStore(
        [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1234/a",
                "display_name": "A",
                "referenced_works": [],
            }
        ]
    )
    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    rows = client.works_by_ids(["W1"])
    assert len(rows) == 1
    assert rows[0]["id"].endswith("W1")
    assert http_calls == []
    assert store.id_calls == [["W1"]]


def test_client_partial_miss_hits_api_for_remainder():
    http_calls: list[tuple[str, dict[str, Any]]] = []

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        http_calls.append((path, params))
        return {
            "results": [
                {
                    "id": "https://openalex.org/W2",
                    "doi": "https://doi.org/10.1234/b",
                    "display_name": "B",
                    "referenced_works": [],
                }
            ]
        }

    store = FakeStore(
        [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1234/a",
                "display_name": "A",
                "referenced_works": [],
            }
        ]
    )
    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    rows = client.works_by_ids(["W1", "W2"])
    assert [r["id"].endswith("W1") or r["id"].endswith("W2") for r in rows] == [True, True]
    assert len(http_calls) == 1
    assert "W2" in http_calls[0][1]["filter"]
    assert "W1" not in http_calls[0][1]["filter"]


def test_client_store_failure_falls_back_to_api():
    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": "https://doi.org/10.1234/a",
                    "display_name": "A",
                }
            ]
        }

    client = OpenAlexClient(
        email="t@example.org",
        api_key="",
        sleep_s=0,
        getter=getter,
        store=FakeStore(fail=True),
    )
    notes: list[str] = []
    client.progress = notes.append
    rows = client.works_by_ids(["W1"])
    assert len(rows) == 1
    assert any("store failed" in n for n in notes)


def test_client_no_store_unchanged():
    http_calls: list[str] = []

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        http_calls.append(path)
        return {
            "results": [
                {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1234/a"}
            ]
        }

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    assert client.store is None
    rows = client.works_by_ids(["W1"])
    assert len(rows) == 1
    assert http_calls == ["/works"]


def test_works_by_dois_store_then_api():
    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "results": [
                {
                    "id": "https://openalex.org/W2",
                    "doi": "https://doi.org/10.1234/b",
                    "referenced_works": ["W9"],
                }
            ]
        }

    store = FakeStore(
        [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1234/a",
                "referenced_works": [],
            }
        ]
    )
    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    rows = client.works_by_dois(["10.1234/a", "10.1234/b"])
    assert normalize_store_doi(rows[0]["doi"]) == "10.1234/a"
    assert normalize_store_doi(rows[1]["doi"]) == "10.1234/b"


def test_works_by_ids_with_search_skips_store():
    store = FakeStore(
        [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1234/a"}]
    )

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        assert params.get("search") == "degrowth"
        return {"results": []}

    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    client.works_by_ids(["W1"], search="degrowth")
    assert store.id_calls == []


def test_work_by_doi_store_hit():
    store = FakeStore(
        [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1234/a",
                "display_name": "A",
            }
        ]
    )

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("HTTP should not run")

    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    hit = client.work_by_doi("10.1234/a")
    assert hit is not None
    assert hit["display_name"] == "A"
