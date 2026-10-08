"""Opt-in OpenAlex works store (snapshot behind a transport).

Most installs leave this unset and use the live OpenAlex API only. When
configured, Paperful asks a remote DuckDB process (SSH) to scan a parquet
snapshot on the data host and returns small JSON result rows. Later backends
(local DuckDB, HTTP) share the same ``WorksStore`` protocol.

v1 covers DOI and OpenAlex-id lookups only. Cited-by, text search, keywords,
and ORCID stay on the API.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any, Protocol, runtime_checkable

from ..resolve import normalize_doi

#: Full work projection used by snowball (keep in sync with openalex.SELECT).
STORE_COLUMNS = (
    "id",
    "doi",
    "display_name",
    "publication_year",
    "type",
    "cited_by_count",
    "language",
    "referenced_works",
    "authorships",
    "primary_location",
    "open_access",
    "keywords",
    "study_designs",
)

_ALLOWED_COLUMNS = frozenset(STORE_COLUMNS)

#: Env overrides (optional; config wins when set).
SSH_HOST_ENV = "OPENALEX_STORE_SSH_HOST"
PARQUET_GLOB_ENV = "OPENALEX_STORE_PARQUET_GLOB"


class OpenAlexStoreError(RuntimeError):
    """Misconfigured or failed OpenAlex store backend."""


@runtime_checkable
class WorksStore(Protocol):
    """OpenAlex-shaped work reads from a snapshot."""

    def work_by_doi(self, doi: str) -> dict[str, Any] | None: ...

    def works_by_dois(
        self, dois: list[str], *, select: str = "id,doi,referenced_works"
    ) -> list[dict[str, Any]]: ...

    def works_by_ids(self, openalex_ids: list[str]) -> list[dict[str, Any]]: ...


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_str_list(values: list[str]) -> str:
    return ", ".join(_sql_str(v) for v in values)


def columns_for_select(select: str) -> list[str]:
    """Parse an OpenAlex-style select list; reject unknown names."""
    text = (select or "").strip()
    if not text:
        return list(STORE_COLUMNS)
    out: list[str] = []
    for part in text.split(","):
        name = part.strip()
        if not name:
            continue
        if name not in _ALLOWED_COLUMNS:
            raise OpenAlexStoreError(f"openalex store select column not allowed: {name!r}")
        if name not in out:
            out.append(name)
    return out or list(STORE_COLUMNS)


def normalize_store_doi(doi: str) -> str:
    """Bare lowercase DOI for store matching."""
    return (normalize_doi(doi) or "").strip().lower()


def _short_id(url: str) -> str:
    return (url or "").rstrip("/").split("/")[-1]


def normalize_store_id(openalex_id: str) -> str:
    """Short OpenAlex id (e.g. W123) for store matching."""
    return _short_id(openalex_id).strip()


def doi_sql_expr(column: str = "doi") -> str:
    """SQL expression that yields a bare lowercase DOI from a snapshot column."""
    return (
        f"lower(regexp_replace(coalesce({column}, ''), "
        f"'^https?://(dx\\.)?doi\\.org/', ''))"
    )


def id_sql_expr(column: str = "id") -> str:
    """SQL expression that yields a short OpenAlex id from a snapshot column."""
    return f"regexp_extract(coalesce({column}, ''), '([^/]+)$', 1)"


def build_works_sql(
    *,
    parquet_glob: str,
    columns: list[str],
    dois: list[str] | None = None,
    openalex_ids: list[str] | None = None,
) -> str:
    """Build a DuckDB SELECT over ``read_parquet`` for DOI or id batches."""
    if bool(dois) == bool(openalex_ids):
        raise OpenAlexStoreError("build_works_sql needs exactly one of dois or openalex_ids")
    cols = ", ".join(columns)
    source = (
        f"read_parquet({_sql_str(parquet_glob)}, union_by_name := true)"
    )
    if dois is not None:
        cleaned = [normalize_store_doi(d) for d in dois if normalize_store_doi(d)]
        if not cleaned:
            return f"SELECT {cols} FROM {source} WHERE 1 = 0"
        where = f"{doi_sql_expr()} IN ({_sql_str_list(cleaned)})"
    else:
        assert openalex_ids is not None
        cleaned = [normalize_store_id(i) for i in openalex_ids if normalize_store_id(i)]
        if not cleaned:
            return f"SELECT {cols} FROM {source} WHERE 1 = 0"
        where = f"{id_sql_expr()} IN ({_sql_str_list(cleaned)})"
    return f"SELECT {cols} FROM {source} WHERE {where}"


def parse_duckdb_json(stdout: str) -> list[dict[str, Any]]:
    """Parse DuckDB ``-json`` stdout into a list of work dicts."""
    text = (stdout or "").strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    raise OpenAlexStoreError("openalex store returned non-object JSON")


class SshDuckDbStore:
    """Run DuckDB over SSH on the host that holds the parquet snapshot."""

    def __init__(
        self,
        *,
        ssh_host: str,
        parquet_glob: str,
        ssh_user: str = "",
        duckdb_bin: str = "duckdb",
        timeout_s: float = 120.0,
        runner: Any = None,
    ):
        self.ssh_host = ssh_host.strip()
        self.ssh_user = (ssh_user or "").strip()
        self.parquet_glob = parquet_glob.strip()
        self.duckdb_bin = (duckdb_bin or "duckdb").strip() or "duckdb"
        self.timeout_s = float(timeout_s)
        self._runner = runner or _run_ssh_duckdb
        if not self.ssh_host:
            raise OpenAlexStoreError("openalex_store.ssh_host is required")
        if not self.parquet_glob:
            raise OpenAlexStoreError("openalex_store.parquet_glob is required")

    def work_by_doi(self, doi: str) -> dict[str, Any] | None:
        rows = self.works_by_dois([doi], select=",".join(STORE_COLUMNS))
        return rows[0] if rows else None

    def works_by_dois(
        self, dois: list[str], *, select: str = "id,doi,referenced_works"
    ) -> list[dict[str, Any]]:
        cleaned = [d for d in dois if normalize_store_doi(d)]
        if not cleaned:
            return []
        sql = build_works_sql(
            parquet_glob=self.parquet_glob,
            columns=columns_for_select(select),
            dois=cleaned,
        )
        return self._query(sql)

    def works_by_ids(self, openalex_ids: list[str]) -> list[dict[str, Any]]:
        cleaned = [i for i in openalex_ids if normalize_store_id(i)]
        if not cleaned:
            return []
        sql = build_works_sql(
            parquet_glob=self.parquet_glob,
            columns=list(STORE_COLUMNS),
            openalex_ids=cleaned,
        )
        return self._query(sql)

    def _query(self, sql: str) -> list[dict[str, Any]]:
        stdout = self._runner(
            host=self.ssh_host,
            user=self.ssh_user,
            duckdb_bin=self.duckdb_bin,
            sql=sql,
            timeout_s=self.timeout_s,
        )
        return parse_duckdb_json(stdout)


def _run_ssh_duckdb(
    *,
    host: str,
    user: str,
    duckdb_bin: str,
    sql: str,
    timeout_s: float,
) -> str:
    target = f"{user}@{host}" if user else host
    # Pass SQL on stdin so shell quoting does not mangle the query.
    remote = f"{shlex.quote(duckdb_bin)} -json"
    cmd = ["ssh", "-o", "BatchMode=yes", target, remote]
    try:
        proc = subprocess.run(
            cmd,
            input=sql + "\n",
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenAlexStoreError(
            f"openalex store SSH timed out after {timeout_s:.0f}s"
        ) from exc
    except OSError as exc:
        raise OpenAlexStoreError(f"openalex store SSH failed: {exc}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise OpenAlexStoreError(f"openalex store DuckDB failed: {err}")
    return proc.stdout or ""


def store_from_config(cfg: Any) -> WorksStore | None:
    """Build a works store from config, or None when unset / incomplete."""
    backend = str(getattr(cfg, "openalex_store_backend", "") or "").strip().lower()
    if not backend:
        return None
    if backend != "ssh_duckdb":
        raise OpenAlexStoreError(
            f"openalex_store.backend {backend!r} is not supported yet "
            "(v1: ssh_duckdb; later: local_duckdb, http)"
        )

    host = str(getattr(cfg, "openalex_store_ssh_host", "") or "").strip()
    if not host:
        host = os.environ.get(SSH_HOST_ENV, "").strip()
    user = str(getattr(cfg, "openalex_store_ssh_user", "") or "").strip()
    parquet_glob = str(getattr(cfg, "openalex_store_parquet_glob", "") or "").strip()
    if not parquet_glob:
        parquet_glob = os.environ.get(PARQUET_GLOB_ENV, "").strip()
    duckdb_bin = str(getattr(cfg, "openalex_store_duckdb_bin", "") or "").strip() or "duckdb"
    timeout_s = float(getattr(cfg, "openalex_store_timeout_s", 120.0) or 120.0)

    if not host or not parquet_glob:
        raise OpenAlexStoreError(
            "openalex_store backend ssh_duckdb needs ssh_host and parquet_glob "
            f"(or {SSH_HOST_ENV} / {PARQUET_GLOB_ENV})"
        )
    return SshDuckDbStore(
        ssh_host=host,
        ssh_user=user,
        parquet_glob=parquet_glob,
        duckdb_bin=duckdb_bin,
        timeout_s=timeout_s,
    )
