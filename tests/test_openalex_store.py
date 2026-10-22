"""OpenAlex snapshot store: SQL helpers, SSH runner, client merge with API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from paperful.config import Config, load_config
from paperful.snowball.local_openalex import (
    LocalDuckDbStore,
    OpenAlexStoreError,
    SshDuckDbStore,
    build_cites_index_sql,
    build_citing_sql,
    build_works_sql,
    columns_for_select,
    normalize_store_doi,
    normalize_store_id,
    normalize_store_row,
    parse_duckdb_json,
    ssh_argv,
    store_from_config,
    store_status,
    title_matches,
)
from paperful.snowball.openalex import (
    STORE_FAIL_THRESHOLD,
    OpenAlexBudgetExceeded,
    OpenAlexClient,
)


class FakeStore:
    def __init__(
        self,
        works: list[dict[str, Any]] | None = None,
        *,
        fail: bool = False,
        cites: dict[str, list[str]] | None = None,
        has_cites_index: bool = False,
    ):
        self.works = list(works or [])
        self.fail = fail
        self.doi_calls: list[list[str]] = []
        self.id_calls: list[list[str]] = []
        self.cite_calls: list[str] = []
        # cited_id -> list of citer short ids
        self.cites = {normalize_store_id(k): list(v) for k, v in (cites or {}).items()}
        self.has_cites_index = bool(has_cites_index or self.cites)

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

    def works_citing(
        self,
        openalex_id: str,
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
        sort: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.fail:
            raise RuntimeError("store down")
        if not self.has_cites_index:
            raise OpenAlexStoreError("openalex store cites index is not configured")
        cited = normalize_store_id(openalex_id)
        self.cite_calls.append(cited)
        citer_ids = self.cites.get(cited, [])
        by_id = {normalize_store_id(str(row.get("id") or "")): row for row in self.works}
        rows = [by_id[i] for i in citer_ids if i in by_id]
        if year_from is not None:
            rows = [r for r in rows if int(r.get("publication_year") or 0) >= year_from]
        if year_to is not None:
            rows = [r for r in rows if int(r.get("publication_year") or 0) <= year_to]
        if search:
            rows = [
                r
                for r in rows
                if title_matches(str(r.get("display_name") or ""), search)
            ]
        if (sort or "").startswith("cited_by_count"):
            rev = not str(sort).endswith(":asc")
            rows.sort(key=lambda r: int(r.get("cited_by_count") or 0), reverse=rev)
        return rows[: max(0, int(limit))] if limit > 0 else rows


def test_store_columns_match_openalex_select():
    from paperful.snowball.local_openalex import STORE_COLUMNS
    from paperful.snowball.openalex import SELECT

    assert list(STORE_COLUMNS) == [part.strip() for part in SELECT.split(",") if part.strip()]


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


def test_normalize_store_row_decodes_nested_json_strings():
    row = normalize_store_row(
        {
            "id": "https://openalex.org/W1",
            "referenced_works": '["https://openalex.org/W2"]',
            "authorships": '[{"author":{"display_name":"Ada"}}]',
            "primary_location": '{"source":{"display_name":"Journal"}}',
            "open_access": '{"is_oa":true}',
            "keywords": "not-json",
            "display_name": "Title",
        }
    )
    assert row["referenced_works"] == ["https://openalex.org/W2"]
    assert row["authorships"][0]["author"]["display_name"] == "Ada"
    assert row["primary_location"]["source"]["display_name"] == "Journal"
    assert row["open_access"]["is_oa"] is True
    assert row["keywords"] == "not-json"


def test_parse_duckdb_json_normalizes_nested_strings():
    rows = parse_duckdb_json(
        '[{"id":"W1","referenced_works":"[\\"W2\\"]","authorships":[]}]'
    )
    assert rows[0]["referenced_works"] == ["W2"]
    assert rows[0]["authorships"] == []


def test_ssh_argv_includes_connect_timeout_and_keepalive():
    cmd = ssh_argv(
        "me@nuc",
        "duckdb -json",
        connect_timeout_s=12,
        port=2222,
        identity_file="/tmp/id_ed25519",
    )
    assert cmd[:3] == ["ssh", "-o", "BatchMode=yes"]
    assert "ConnectTimeout=12" in cmd
    assert "ServerAliveInterval=30" in cmd
    assert cmd[cmd.index("-p") + 1] == "2222"
    assert cmd[cmd.index("-i") + 1] == "/tmp/id_ed25519"
    assert cmd[-2:] == ["me@nuc", "duckdb -json"]


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


def test_store_from_config_local_duckdb(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(
        'email = "t@example.org"\n'
        f'out_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
        "[openalex_store]\n"
        'backend = "local_duckdb"\n'
        'parquet_glob = "/data/openalex/**/*.parquet"\n'
        'duckdb_bin = "duckdb"\n'
    )
    cfg = load_config(path)
    store = store_from_config(cfg)
    assert isinstance(store, LocalDuckDbStore)
    assert store.parquet_glob == "/data/openalex/**/*.parquet"

    monkeypatch.setenv("OPENALEX_STORE_PARQUET_GLOB", "/env/works/**/*.parquet")
    bare = Config()
    bare.openalex_store_backend = "local_duckdb"
    env_store = store_from_config(bare)
    assert isinstance(env_store, LocalDuckDbStore)
    assert env_store.parquet_glob == "/env/works/**/*.parquet"

    with pytest.raises(OpenAlexStoreError, match="parquet_glob"):
        incomplete = Config()
        incomplete.openalex_store_backend = "local_duckdb"
        monkeypatch.delenv("OPENALEX_STORE_PARQUET_GLOB", raising=False)
        store_from_config(incomplete)


def test_local_store_uses_runner():
    seen: dict[str, Any] = {}

    def runner(**kwargs: Any) -> str:
        seen.update(kwargs)
        return '[{"id":"https://openalex.org/W3","doi":"https://doi.org/10.1234/x"}]'

    store = LocalDuckDbStore(
        parquet_glob="/data/**/*.parquet",
        runner=runner,
    )
    rows = store.works_by_dois(["10.1234/x"])
    assert normalize_store_doi(rows[0]["doi"]) == "10.1234/x"
    assert "read_parquet" in seen["sql"]
    assert "10.1234/x" in seen["sql"]
    assert "host" not in seen


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


def test_budget_then_store_serves_doi_and_ids():
    """After the API budget latches, DOI/id reads keep using the snapshot."""
    http_calls: list[str] = []

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        http_calls.append(path)
        raise OpenAlexBudgetExceeded("OpenAlex daily budget is spent", reset_in_s=3600)

    store = FakeStore(
        [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1234/a",
                "display_name": "A",
                "referenced_works": [],
            },
            {
                "id": "https://openalex.org/W2",
                "doi": "https://doi.org/10.1234/b",
                "display_name": "B",
                "referenced_works": [],
            },
        ]
    )
    notes: list[str] = []
    client = OpenAlexClient(
        email="t@example.org",
        api_key="",
        sleep_s=0,
        getter=getter,
        store=store,
        progress=notes.append,
    )
    with pytest.raises(OpenAlexBudgetExceeded):
        client.get("/works", {"search": "anything"})
    assert client._store_only
    assert any("local snapshot" in n for n in notes)

    hit = client.work_by_doi("10.1234/a")
    assert hit is not None
    assert hit["display_name"] == "A"
    rows = client.works_by_ids(["W2"])
    assert len(rows) == 1
    assert rows[0]["id"].endswith("W2")
    # Only the search that burned the budget hit HTTP.
    assert http_calls == ["/works"]


def test_budget_mid_id_fill_returns_store_partial_without_raise():
    store = FakeStore(
        [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1234/a",
                "referenced_works": [],
            }
        ]
    )

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        raise OpenAlexBudgetExceeded("OpenAlex daily budget is spent")

    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    rows = client.works_by_ids(["W1", "W2"])
    assert len(rows) == 1
    assert rows[0]["id"].endswith("W1")
    assert client._store_only


def test_budget_with_search_falls_back_to_store_title_match():
    store = FakeStore(
        [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1234/a",
                "display_name": "Degrowth pathways",
            },
            {
                "id": "https://openalex.org/W2",
                "doi": "https://doi.org/10.1234/b",
                "display_name": "Other topic",
            },
        ]
    )

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        raise OpenAlexBudgetExceeded("OpenAlex daily budget is spent")

    notes: list[str] = []
    client = OpenAlexClient(
        email="t@example.org",
        api_key="",
        sleep_s=0,
        getter=getter,
        store=store,
        progress=notes.append,
    )
    rows = client.works_by_ids(["W1", "W2"], search="degrowth")
    assert len(rows) == 1
    assert rows[0]["id"].endswith("W1")
    assert any("title match" in n for n in notes)


def test_budget_without_store_still_raises():
    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        raise OpenAlexBudgetExceeded("OpenAlex daily budget is spent")

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    with pytest.raises(OpenAlexBudgetExceeded):
        client.works_by_ids(["W1"])


def test_budget_mid_doi_fill_returns_store_partial_without_raise():
    store = FakeStore(
        [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1234/a",
                "referenced_works": [],
            }
        ]
    )

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        raise OpenAlexBudgetExceeded("OpenAlex daily budget is spent")

    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    rows = client.works_by_dois(["10.1234/a", "10.1234/b"])
    assert len(rows) == 1
    assert normalize_store_doi(rows[0]["doi"]) == "10.1234/a"
    assert client._store_only


def test_after_budget_store_miss_returns_none_not_raise():
    store = FakeStore([])

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        raise OpenAlexBudgetExceeded("OpenAlex daily budget is spent")

    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    with pytest.raises(OpenAlexBudgetExceeded):
        client.get("/works", {"search": "burn"})
    assert client.work_by_doi("10.1234/missing") is None


def test_after_budget_search_still_raises_even_with_store():
    store = FakeStore(
        [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1234/a"}]
    )

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        raise OpenAlexBudgetExceeded("OpenAlex daily budget is spent")

    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    with pytest.raises(OpenAlexBudgetExceeded):
        client.get("/works", {"search": "burn"})
    with pytest.raises(OpenAlexBudgetExceeded):
        client.search("ocean", limit=5, year_from=None, year_to=None)


def test_defer_notes_snapshot_when_store_configured():
    from paperful.snowball.crawl import _defer

    notes: list[str] = []
    client = OpenAlexClient(
        email="t@example.org",
        api_key="",
        sleep_s=0,
        store=FakeStore([]),
        progress=notes.append,
    )
    _defer(
        client,
        OpenAlexBudgetExceeded("spent", reset_at="2099-01-01T00:00:00+00:00"),
        kind="search",
    )
    assert client.deferred is not None
    assert any("Snapshot store is configured" in n for n in notes)


def test_local_store_runner_failure_surfaces():
    def runner(**kwargs: Any) -> str:
        raise OpenAlexStoreError("duckdb missing")

    store = LocalDuckDbStore(parquet_glob="/data/**/*.parquet", runner=runner)
    with pytest.raises(OpenAlexStoreError, match="duckdb missing"):
        store.works_by_ids(["W1"])


def test_works_by_dois_after_budget_skips_api():
    http_calls: list[str] = []

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        http_calls.append(path)
        raise OpenAlexBudgetExceeded("OpenAlex daily budget is spent")

    store = FakeStore(
        [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1234/a",
                "referenced_works": ["W9"],
            }
        ]
    )
    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    with pytest.raises(OpenAlexBudgetExceeded):
        client.get("/works", {"search": "burn"})
    http_calls.clear()
    rows = client.works_by_dois(["10.1234/a", "10.1234/missing"])
    assert len(rows) == 1
    assert normalize_store_doi(rows[0]["doi"]) == "10.1234/a"
    assert http_calls == []


def test_build_citing_sql_join_limit_sort_title():
    sql = build_citing_sql(
        works_glob="/works/**/*.parquet",
        cites_index_glob="/cites/**/*.parquet",
        openalex_id="https://openalex.org/Wseed",
        limit=25,
        year_from=2020,
        year_to=2024,
        sort="cited_by_count:desc",
        search="BBNJ",
    )
    assert "cited_id = 'Wseed'" in sql
    assert "citer_id" in sql
    assert "publication_year >= 2020" in sql
    assert "publication_year <= 2024" in sql
    assert "ORDER BY w.cited_by_count DESC" in sql
    assert "LIMIT 25" in sql
    assert "contains(lower(coalesce(w.display_name, '')), 'bbnj')" in sql


def test_build_cites_index_sql():
    sql = build_cites_index_sql(
        works_glob="/works/**/*.parquet", output_dir="/data/openalex/cites"
    )
    assert "UNNEST" in sql
    assert "referenced_works" in sql
    assert "PARTITION_BY (cited_prefix)" in sql
    assert "/data/openalex/cites" in sql


def test_works_root_and_partition_helpers():
    from paperful.snowball.local_openalex import (
        build_cites_partition_sql,
        cites_done_marker,
        cites_partition_outdir,
        updated_date_from_dirname,
        works_root_from_glob,
    )

    assert works_root_from_glob("/data/works/**/*.parquet") == "/data/works"
    assert updated_date_from_dirname("updated_date=2024-01-02") == "2024-01-02"
    assert cites_done_marker("/cites", "2024-01-02") == "/cites/.done/2024-01-02"
    assert cites_partition_outdir("/cites", "2024-01-02") == "/cites/source_date=2024-01-02"
    sql = build_cites_partition_sql(
        works_root="/data/works", date="2024-01-02", output_dir="/cites"
    )
    assert "updated_date=2024-01-02/*.parquet" in sql
    assert "source_date=2024-01-02" in sql


def test_build_cites_index_resumable_skips_done(tmp_path: Path):
    works = tmp_path / "works"
    for day in ("2024-01-01", "2024-01-02", "2024-01-03"):
        day_dir = works / f"updated_date={day}"
        day_dir.mkdir(parents=True)
        (day_dir / "part_0000.parquet").write_bytes(b"")
        if day == "2024-01-02":
            (day_dir / "part_0001.parquet").write_bytes(b"")
    out = tmp_path / "cites"
    done = out / ".done"
    done.mkdir(parents=True)
    (done / "2024-01-01").write_text("2024-01-01\n", encoding="utf-8")
    # Incomplete leftover from a crash — must be removed before rebuild.
    stale = out / "source_date=2024-01-02" / "file=part_0000"
    stale.mkdir(parents=True)
    (stale / "partial.parquet").write_text("x", encoding="utf-8")

    seen: list[str] = []

    def exec_runner(**kwargs: Any) -> None:
        seen.append(kwargs["sql"])

    store = LocalDuckDbStore(
        parquet_glob=str(works / "**" / "*.parquet"),
        runner=lambda **kwargs: "[]",
        exec_runner=exec_runner,
    )
    counts = store.build_cites_index(str(out), timeout_s=30.0)
    assert counts == {"total": 3, "built": 2, "skipped": 1}
    # 2024-01-02 has 2 files; 2024-01-03 has 1.
    assert len(seen) == 3
    assert "part_0000" in seen[0]
    assert "SET memory_limit" in seen[0]
    assert "file=part_0000" in seen[0]
    assert not (stale / "partial.parquet").exists()
    assert (done / "2024-01-02").is_file()
    assert (done / "2024-01-03").is_file()
    assert (done / "2024-01-02.parts" / "part_0000").is_file()
    # Second run skips everything.
    seen.clear()
    counts2 = store.build_cites_index(str(out), timeout_s=30.0)
    assert counts2 == {"total": 3, "built": 0, "skipped": 3}
    assert seen == []


def test_write_resumable_cites_build_script(tmp_path: Path):
    from paperful.snowball.local_openalex import write_resumable_cites_build_script

    script = tmp_path / "build_cites.sh"
    path = write_resumable_cites_build_script(
        works_root="/mnt/works",
        output_dir="/mnt/cites",
        duckdb_bin="/usr/bin/duckdb",
        script_path=str(script),
    )
    text = Path(path).read_text(encoding="utf-8")
    assert "updated_date=*" in text
    assert ".done" in text
    assert ".parts" in text
    assert "memory_limit" in text
    assert "file=" in text
    assert "/mnt/works" in text
    assert "/mnt/cites" in text
    assert Path(path).stat().st_mode & 0o111


def test_store_from_config_cites_index_glob(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        'email = "t@example.org"\n'
        f'out_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
        "[openalex_store]\n"
        'backend = "local_duckdb"\n'
        'parquet_glob = "/data/works/**/*.parquet"\n'
        'cites_index_glob = "/data/cites/**/*.parquet"\n'
    )
    store = store_from_config(load_config(path))
    assert isinstance(store, LocalDuckDbStore)
    assert store.has_cites_index
    assert store.cites_index_glob == "/data/cites/**/*.parquet"


def test_works_citing_store_first_skips_http():
    http_calls: list[str] = []

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        http_calls.append(path)
        return {"results": []}

    store = FakeStore(
        [
            {
                "id": "https://openalex.org/Wciter",
                "doi": "https://doi.org/10.1/c",
                "display_name": "Citer",
                "cited_by_count": 9,
                "publication_year": 2022,
            }
        ],
        cites={"Wseed": ["Wciter"]},
    )
    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    rows = client.works_citing("Wseed", limit=25, sort="cited_by_count:desc")
    assert len(rows) == 1
    assert rows[0]["id"].endswith("Wciter")
    assert http_calls == []
    assert store.cite_calls == ["Wseed"]


def test_works_citing_budget_uses_store():
    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        raise OpenAlexBudgetExceeded("OpenAlex daily budget is spent")

    store = FakeStore(
        [
            {
                "id": "https://openalex.org/Wciter",
                "display_name": "High seas governance",
                "cited_by_count": 3,
            }
        ],
        cites={"Wseed": ["Wciter"]},
    )
    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    with pytest.raises(OpenAlexBudgetExceeded):
        client.get("/works", {"search": "burn"})
    rows = client.works_citing("Wseed", limit=10, search="high seas")
    assert len(rows) == 1
    assert "High seas" in rows[0]["display_name"]


def test_works_citing_without_index_hits_api():
    http_calls: list[tuple[str, dict[str, Any]]] = []

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        http_calls.append((path, params))
        return {
            "results": [
                {"id": "https://openalex.org/Wapi", "display_name": "From API"}
            ],
            "meta": {"count": 1},
        }

    store = FakeStore([{"id": "https://openalex.org/W1"}], has_cites_index=False)
    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store
    )
    rows = client.works_citing("Wseed", limit=5)
    assert rows[0]["id"].endswith("Wapi")
    assert "cites:Wseed" in http_calls[0][1]["filter"]


def test_local_store_citing_uses_runner():
    seen: dict[str, Any] = {}

    def runner(**kwargs: Any) -> str:
        seen.update(kwargs)
        return '[{"id":"https://openalex.org/Wc","display_name":"C"}]'

    store = LocalDuckDbStore(
        parquet_glob="/works/**/*.parquet",
        cites_index_glob="/cites/**/*.parquet",
        runner=runner,
    )
    rows = store.works_citing("W1", limit=10, sort="cited_by_count:desc")
    assert rows[0]["id"].endswith("Wc")
    assert "cited_id = 'W1'" in seen["sql"]
    assert "LIMIT 10" in seen["sql"]


def test_title_matches_helper():
    assert title_matches("Degrowth Now", "degrowth")
    assert not title_matches("Other", "degrowth")
    assert title_matches("Anything", "")


def test_store_skips_missing_parquet_columns():
    """Older OpenAlex dumps lack study_designs; store must not require it."""

    def runner(**kwargs: Any) -> str:
        sql = kwargs.get("sql") or ""
        if sql.startswith("DESCRIBE"):
            return (
                '[{"column_name":"id"},{"column_name":"doi"},'
                '{"column_name":"display_name"},{"column_name":"referenced_works"}]'
            )
        assert "study_designs" not in sql
        assert "display_name" in sql
        return '[{"id":"https://openalex.org/W1","doi":"https://doi.org/10.1/a"}]'

    store = LocalDuckDbStore(parquet_glob="/data/**/*.parquet", runner=runner)
    rows = store.works_by_ids(["W1"])
    assert rows[0]["id"].endswith("W1")
    assert "study_designs" not in store._probe_parquet_columns()


def test_build_cites_index_from_config_uses_exec(tmp_path: Path):
    from paperful.snowball.local_openalex import build_cites_index_from_config

    works = tmp_path / "works"
    day_dir = works / "updated_date=2024-06-01"
    day_dir.mkdir(parents=True)
    (day_dir / "part_0000.parquet").write_bytes(b"")
    seen: dict[str, Any] = {}

    def runner(**kwargs: Any) -> str:
        return "[]"

    def exec_runner(**kwargs: Any) -> None:
        seen.update(kwargs)

    store = LocalDuckDbStore(
        parquet_glob=str(works / "**" / "*.parquet"),
        cites_index_glob=str(tmp_path / "cites" / "**" / "*.parquet"),
        runner=runner,
        exec_runner=exec_runner,
    )
    out = str(tmp_path / "cites")
    counts = store.build_cites_index(out, timeout_s=90.0)
    assert counts["built"] == 1
    assert "COPY" in seen["sql"]
    assert "UNNEST" in seen["sql"]
    assert "source_date=2024-06-01" in seen["sql"]
    assert "file=part_0000" in seen["sql"]
    assert "SET memory_limit" in seen["sql"]
    assert seen["timeout_s"] == 90.0

    # Config helper derives out dir from cites_index_glob ending in /**/*.parquet
    cites_root = tmp_path / "cites_from_cfg"
    cfg2 = Config()
    cfg2.openalex_store_backend = "local_duckdb"
    cfg2.openalex_store_parquet_glob = str(works / "**" / "*.parquet")
    cfg2.openalex_store_cites_index_glob = str(cites_root / "**" / "*.parquet")
    cfg2.openalex_store_build_timeout_s = 120.0
    import paperful.snowball.local_openalex as lo

    def fake_store_from_config(c):
        return LocalDuckDbStore(
            parquet_glob=str(works / "**" / "*.parquet"),
            runner=runner,
            exec_runner=exec_runner,
        )

    original = lo.store_from_config
    lo.store_from_config = fake_store_from_config  # type: ignore[assignment]
    try:
        written, cfg_counts = build_cites_index_from_config(cfg2)
    finally:
        lo.store_from_config = original  # type: ignore[assignment]
    assert written == str(cites_root)
    assert cfg_counts["total"] == 1
    assert str(cites_root) in seen["sql"]


def test_doctor_openalex_store_amber_without_cites_index():
    from paperful.doctor import _openalex_store_check

    off = Config()
    assert _openalex_store_check(off).status == "green"
    assert "off" in _openalex_store_check(off).detail

    cfg = Config()
    cfg.openalex_store_backend = "local_duckdb"
    cfg.openalex_store_parquet_glob = "/works/**/*.parquet"
    check = _openalex_store_check(cfg)
    assert check.status == "amber"
    assert "build-cites" in check.detail

    cfg.openalex_store_cites_index_glob = "/cites/**/*.parquet"
    cfg.openalex_store_duckdb_bin = "/bin/true"
    ok = _openalex_store_check(cfg)
    assert ok.status == "green"
    assert "cites index set" in ok.detail

    cfg.openalex_store_duckdb_bin = "duckdb-not-on-path-xyz"
    duck_amber = _openalex_store_check(cfg)
    assert duck_amber.status == "amber"
    assert "not on PATH" in duck_amber.detail

    missing = Config()
    missing.openalex_store_backend = "local_duckdb"
    red = _openalex_store_check(missing)
    assert red.status == "red"
    assert "parquet_glob" in red.detail

    bad = Config()
    bad.openalex_store_backend = "http"
    assert _openalex_store_check(bad).status == "red"

    ssh = Config()
    ssh.openalex_store_backend = "ssh_duckdb"
    ssh.openalex_store_parquet_glob = "/works/**/*.parquet"
    assert _openalex_store_check(ssh).status == "red"
    assert "ssh_host" in _openalex_store_check(ssh).detail


def test_store_status_reports_backend():
    off = store_status(Config())
    assert off["backend"] == "off"
    assert off["ok"] is True

    cfg = Config()
    cfg.openalex_store_backend = "local_duckdb"
    cfg.openalex_store_parquet_glob = "/works/**/*.parquet"
    status = store_status(cfg)
    assert status["backend"] == "local_duckdb"
    assert status["ok"] is True
    assert status["has_cites_index"] is False


def test_store_circuit_breaker_trips_after_threshold():
    http_calls: list[str] = []

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        http_calls.append(path)
        return {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": "https://doi.org/10.1234/a",
                    "display_name": "From API",
                }
            ]
        }

    store = FakeStore(fail=True)
    notes: list[str] = []
    client = OpenAlexClient(
        email="t@example.org",
        api_key="",
        sleep_s=0,
        getter=getter,
        store=store,
        progress=notes.append,
    )
    for _ in range(STORE_FAIL_THRESHOLD):
        client.works_by_ids(["W1"])
    assert client._store_tripped
    assert any("disabled for this client" in n for n in notes)
    before = len(store.id_calls)
    client.works_by_ids(["W1"])
    assert len(store.id_calls) == before  # tripped — no more store calls
    assert http_calls  # API still used


def test_works_citing_api_budget_falls_back_to_store_mid_call():
    calls = {"n": 0}

    def getter(path: str, params: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        raise OpenAlexBudgetExceeded("OpenAlex daily budget is spent")

    store = FakeStore(
        [
            {
                "id": "https://openalex.org/Wciter",
                "display_name": "From store after budget",
                "cited_by_count": 1,
            }
        ],
        cites={"Wseed": ["Wciter"]},
    )
    notes: list[str] = []
    client = OpenAlexClient(
        email="t@example.org",
        api_key="",
        sleep_s=0,
        getter=getter,
        store=store,
        progress=notes.append,
    )
    # No prior latch: works_citing tries store first, gets hit, never calls API.
    rows = client.works_citing("Wseed", limit=5)
    assert len(rows) == 1
    assert calls["n"] == 0

    # Empty store for this id → API → budget → store empty → []
    store2 = FakeStore(
        [{"id": "https://openalex.org/Wother", "display_name": "Other"}],
        cites={},
        has_cites_index=True,
    )
    client2 = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=getter, store=store2
    )
    rows2 = client2.works_citing("Wmissing", limit=5)
    assert rows2 == []
    assert client2._store_only
