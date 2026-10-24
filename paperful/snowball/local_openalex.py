"""Opt-in OpenAlex works store (snapshot behind a transport).

Most installs leave this unset and use the live OpenAlex API only. When
configured, Paperful asks DuckDB to scan a parquet snapshot and returns small
JSON result rows. Backends: ``ssh_duckdb`` (DuckDB on a remote host) and
``local_duckdb`` (DuckDB on this machine). An ``http`` backend is later.

DOI and OpenAlex-id lookups use the works parquet. Cited-by needs a prebuilt
inverted cites index (``cites_index_glob`` from ``paperful openalex-store
build-cites``). Store cites-query / ``search=`` filtering is title-only
(``display_name``); abstract and fulltext stay on the live API (roadmap 2C).

When the live API daily budget is spent, the client keeps serving DOI/id and
citing reads from the store when configured.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
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

#: List / struct columns. The DuckDB CLI prints these as display strings
#: ("[a, b]") in -json mode, so they are selected through to_json().
NESTED_COLUMNS = frozenset(
    {
        "referenced_works",
        "authorships",
        "primary_location",
        "open_access",
        "keywords",
        "study_designs",
    }
)


def select_list(columns: list[str], prefix: str = "") -> str:
    """SELECT list with nested columns wrapped in to_json() and aliased back."""
    parts: list[str] = []
    for name in columns:
        ref = f"{prefix}{name}"
        parts.append(f"to_json({ref}) AS {name}" if name in NESTED_COLUMNS else ref)
    return ", ".join(parts)


def _decode_nested(row: dict[str, Any]) -> dict[str, Any]:
    """Undo string-encoded nested values (older output or a different runner)."""
    for name in NESTED_COLUMNS:
        value = row.get(name)
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            row[name] = None if name != "referenced_works" else []
            continue
        try:
            row[name] = json.loads(text)
            continue
        except ValueError:
            pass
        if name == "referenced_works" and text.startswith("[") and text.endswith("]"):
            # DuckDB display form: [https://openalex.org/W1, https://openalex.org/W2]
            inner = text[1:-1].strip()
            row[name] = [part.strip() for part in inner.split(",") if part.strip()] if inner else []
        else:
            row[name] = None
    return row

#: Env overrides (optional; config wins when set).
SSH_HOST_ENV = "OPENALEX_STORE_SSH_HOST"
PARQUET_GLOB_ENV = "OPENALEX_STORE_PARQUET_GLOB"
CITES_INDEX_GLOB_ENV = "OPENALEX_STORE_CITES_INDEX_GLOB"

#: Default build timeout for inverting referenced_works (full dumps are slow).
DEFAULT_BUILD_TIMEOUT_S = 7200.0


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

    def works_citing(
        self,
        openalex_id: str,
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
        sort: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]: ...


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


def title_matches(display_name: str, search: str) -> bool:
    """Case-insensitive substring match on a work title (store cites-query)."""
    needle = (search or "").strip().lower()
    if not needle:
        return True
    return needle in (display_name or "").lower()


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
    cols = select_list(columns)
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


def build_citing_sql(
    *,
    works_glob: str,
    cites_index_glob: str,
    openalex_id: str,
    limit: int,
    year_from: int | None = None,
    year_to: int | None = None,
    sort: str | None = None,
    search: str | None = None,
    columns: list[str] | None = None,
) -> str:
    """Join inverted cites index → works for citers of ``openalex_id``."""
    cols_list = list(columns or STORE_COLUMNS)
    cited = normalize_store_id(openalex_id)
    if not cited:
        cols = select_list(cols_list, "w.")
        return (
            f"SELECT {cols} FROM read_parquet({_sql_str(works_glob)}, "
            f"union_by_name := true) AS w WHERE 1 = 0"
        )
    cap = max(0, int(limit))
    cols = select_list(cols_list, "w.")
    cites = (
        f"read_parquet({_sql_str(cites_index_glob)}, union_by_name := true) AS c"
    )
    works = (
        f"read_parquet({_sql_str(works_glob)}, union_by_name := true) AS w"
    )
    where = [f"c.cited_id = {_sql_str(cited)}"]
    if year_from is not None:
        where.append(f"w.publication_year >= {int(year_from)}")
    if year_to is not None:
        where.append(f"w.publication_year <= {int(year_to)}")
    text = (search or "").strip()
    if text:
        where.append(
            f"contains(lower(coalesce(w.display_name, '')), {_sql_str(text.lower())})"
        )
    order = ""
    sort_key = (sort or "").strip().lower()
    if sort_key in ("cited_by_count:desc", "cited_by_count"):
        order = " ORDER BY w.cited_by_count DESC NULLS LAST"
    elif sort_key == "cited_by_count:asc":
        order = " ORDER BY w.cited_by_count ASC NULLS LAST"
    lim = f" LIMIT {cap}" if cap > 0 else ""
    return (
        f"SELECT {cols} FROM {cites} "
        f"INNER JOIN {works} ON {id_sql_expr('w.id')} = c.citer_id "
        f"WHERE {' AND '.join(where)}{order}{lim}"
    )


def works_root_from_glob(parquet_glob: str) -> str:
    """Derive the works directory from a parquet glob ending in ``**/*.parquet``."""
    text = (parquet_glob or "").strip().rstrip("/")
    for suffix in ("/**/*.parquet", "/*.parquet", "/**/*", "/*"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def updated_date_from_dirname(name: str) -> str:
    """``updated_date=2026-09-23`` → ``2026-09-23``."""
    text = (name or "").strip().rstrip("/")
    base = text.split("/")[-1]
    if base.startswith("updated_date="):
        return base.split("=", 1)[1]
    return base


def cites_done_marker(output_dir: str, date: str) -> str:
    return f"{output_dir.rstrip('/')}/.done/{date}"


def cites_file_done_marker(output_dir: str, date: str, file_stem: str) -> str:
    return f"{output_dir.rstrip('/')}/.done/{date}.parts/{file_stem}"


def cites_partition_outdir(output_dir: str, date: str) -> str:
    """Hive folder for one works ``updated_date`` slice."""
    return f"{output_dir.rstrip('/')}/source_date={date}"


def cites_file_outdir(output_dir: str, date: str, file_stem: str) -> str:
    """Hive folder for one works parquet file inside a day (avoids OOM on huge days)."""
    return f"{cites_partition_outdir(output_dir, date)}/file={file_stem}"


def build_cites_index_sql(
    *,
    works_glob: str,
    output_dir: str,
    memory_limit: str = "48GB",
    temp_directory: str = "",
) -> str:
    """DuckDB COPY for one works glob into ``output_dir`` (partitioned by cited_prefix)."""
    out = (output_dir or "").strip().rstrip("/")
    if not out:
        raise OpenAlexStoreError("cites index output directory is required")
    works = f"read_parquet({_sql_str(works_glob)}, union_by_name := true)"
    preamble: list[str] = []
    if memory_limit:
        preamble.append(f"SET memory_limit = {_sql_str(memory_limit)};")
    if temp_directory:
        preamble.append(f"SET temp_directory = {_sql_str(temp_directory)};")
    copy = (
        "COPY (\n"
        "  SELECT\n"
        "    regexp_extract(CAST(ref AS VARCHAR), '([^/]+)$', 1) AS cited_id,\n"
        "    regexp_extract(coalesce(CAST(id AS VARCHAR), ''), '([^/]+)$', 1) "
        "AS citer_id,\n"
        "    substr(\n"
        "      regexp_extract(CAST(ref AS VARCHAR), '([^/]+)$', 1),\n"
        "      1, 4\n"
        "    ) AS cited_prefix\n"
        f"  FROM {works} AS w,\n"
        "       UNNEST(w.referenced_works) AS u(ref)\n"
        "  WHERE cited_id IS NOT NULL AND cited_id <> ''\n"
        "    AND citer_id IS NOT NULL AND citer_id <> ''\n"
        f") TO {_sql_str(out)} "
        "(FORMAT PARQUET, PARTITION_BY (cited_prefix), OVERWRITE_OR_IGNORE)"
    )
    return "\n".join([*preamble, copy])


def build_cites_partition_sql(*, works_root: str, date: str, output_dir: str) -> str:
    """COPY one ``updated_date=…`` works slice into ``source_date=…`` under output."""
    day = (date or "").strip()
    if not day:
        raise OpenAlexStoreError("cites partition date is required")
    works_glob = f"{works_root.rstrip('/')}/updated_date={day}/*.parquet"
    part_out = cites_partition_outdir(output_dir, day)
    return build_cites_index_sql(works_glob=works_glob, output_dir=part_out)


def build_cites_file_sql(
    *,
    works_parquet: str,
    output_dir: str,
    memory_limit: str = "48GB",
    temp_directory: str = "",
) -> str:
    """COPY one works parquet file into a ``file=…`` hive folder."""
    path = (works_parquet or "").strip()
    if not path:
        raise OpenAlexStoreError("cites works parquet path is required")
    return build_cites_index_sql(
        works_glob=path,
        output_dir=output_dir,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
    )


def parse_duckdb_json(stdout: str) -> list[dict[str, Any]]:
    """Parse DuckDB ``-json`` stdout into a list of work dicts."""
    text = (stdout or "").strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, list):
        return [_decode_nested(row) for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [_decode_nested(data)]
    raise OpenAlexStoreError("openalex store returned non-object JSON")


class _DuckDbWorksStore:
    """Shared DOI/id/citing query path; subclasses supply how DuckDB is invoked."""

    def __init__(
        self,
        *,
        parquet_glob: str,
        duckdb_bin: str = "duckdb",
        timeout_s: float = 120.0,
        cites_index_glob: str = "",
    ):
        self.parquet_glob = parquet_glob.strip()
        self.duckdb_bin = (duckdb_bin or "duckdb").strip() or "duckdb"
        self.timeout_s = float(timeout_s)
        self.cites_index_glob = (cites_index_glob or "").strip()
        self._parquet_columns: frozenset[str] | None = None
        if not self.parquet_glob:
            raise OpenAlexStoreError("openalex_store.parquet_glob is required")

    @property
    def has_cites_index(self) -> bool:
        return bool(self.cites_index_glob)

    def _store_columns(self, wanted: list[str] | None = None) -> list[str]:
        """Intersect requested columns with what this dump actually has."""
        want = list(wanted or STORE_COLUMNS)
        present = self._probe_parquet_columns()
        if not present:
            return want
        return [name for name in want if name in present] or ["id"]

    def _probe_parquet_columns(self) -> frozenset[str]:
        if self._parquet_columns is not None:
            return self._parquet_columns
        sql = (
            "DESCRIBE SELECT * FROM "
            f"read_parquet({_sql_str(self.parquet_glob)}, union_by_name := true)"
        )
        try:
            rows = self._query(sql)
        except OpenAlexStoreError:
            self._parquet_columns = frozenset()
            return self._parquet_columns
        names = {
            str(row.get("column_name") or "").strip()
            for row in rows
            if isinstance(row, dict) and row.get("column_name")
        }
        self._parquet_columns = frozenset(names)
        return self._parquet_columns

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
            columns=self._store_columns(columns_for_select(select)),
            dois=cleaned,
        )
        return self._query(sql)

    def works_by_ids(self, openalex_ids: list[str]) -> list[dict[str, Any]]:
        cleaned = [i for i in openalex_ids if normalize_store_id(i)]
        if not cleaned:
            return []
        sql = build_works_sql(
            parquet_glob=self.parquet_glob,
            columns=self._store_columns(list(STORE_COLUMNS)),
            openalex_ids=cleaned,
        )
        return self._query(sql)

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
        if not self.has_cites_index:
            raise OpenAlexStoreError(
                "openalex store cites index is not configured "
                f"(set cites_index_glob or {CITES_INDEX_GLOB_ENV}; "
                "build with: paperful openalex-store build-cites)"
            )
        oa = normalize_store_id(openalex_id)
        if not oa:
            return []
        sql = build_citing_sql(
            works_glob=self.parquet_glob,
            cites_index_glob=self.cites_index_glob,
            openalex_id=oa,
            limit=limit,
            year_from=year_from,
            year_to=year_to,
            sort=sort,
            search=search,
            columns=self._store_columns(list(STORE_COLUMNS)),
        )
        return self._query(sql)

    def list_works_updated_dates(self) -> list[str]:
        """Sorted ``YYYY-MM-DD`` values under the works hive root."""
        root = works_root_from_glob(self.parquet_glob)
        return self._list_updated_dates(root)

    def build_cites_index(
        self,
        output_dir: str,
        *,
        timeout_s: float | None = None,
        progress: Any = None,
        memory_limit: str = "48GB",
    ) -> dict[str, int]:
        """Invert referenced_works per parquet file (resumable).

        Skips dates with a ``.done/<date>`` marker. Within a date, skips files
        with ``.done/<date>.parts/<stem>`` markers so huge days (100G+) can
        resume without reloading the whole hive folder. Returns counts.
        """
        out = (output_dir or "").strip().rstrip("/")
        if not out:
            raise OpenAlexStoreError("cites index output directory is required")
        works_root = works_root_from_glob(self.parquet_glob)
        dates = self._list_updated_dates(works_root)
        if not dates:
            raise OpenAlexStoreError(
                f"no updated_date=* partitions under {works_root}"
            )
        self._ensure_dir(f"{out}/.done")
        tmp = f"{out}/.duckdb_tmp"
        self._ensure_dir(tmp)
        wait = float(timeout_s) if timeout_s is not None else self.timeout_s
        skipped = built = 0
        for index, day in enumerate(dates, start=1):
            marker = cites_done_marker(out, day)
            if self._path_exists(marker):
                skipped += 1
                if progress is not None:
                    progress(f"cites build · skip {day} ({index}/{len(dates)})")
                continue
            files = self._list_works_parquet_files(works_root, day)
            if not files:
                raise OpenAlexStoreError(
                    f"no parquet files under {works_root}/updated_date={day}"
                )
            self._ensure_dir(f"{out}/.done/{day}.parts")
            for file_index, parquet_path in enumerate(files, start=1):
                stem = Path(parquet_path).stem
                file_marker = cites_file_done_marker(out, day, stem)
                file_out = cites_file_outdir(out, day, stem)
                if self._path_exists(file_marker):
                    continue
                self._remove_tree(file_out)
                # DuckDB's partitioned COPY does not create missing parent folders.
                self._ensure_dir(file_out.rsplit("/", 1)[0])
                sql = build_cites_file_sql(
                    works_parquet=parquet_path,
                    output_dir=file_out,
                    memory_limit=memory_limit,
                    temp_directory=tmp,
                )
                if progress is not None:
                    progress(
                        f"cites build · {day} {stem} "
                        f"({file_index}/{len(files)}; day {index}/{len(dates)})"
                    )
                self._exec(sql, timeout_s=wait)
                self._write_text(file_marker, f"{stem}\n")
            self._write_text(marker, f"{day}\n")
            built += 1
            if progress is not None:
                progress(f"cites build · done {day} ({index}/{len(dates)})")
        return {"total": len(dates), "built": built, "skipped": skipped}

    def _list_updated_dates(self, works_root: str) -> list[str]:
        raise NotImplementedError

    def _list_works_parquet_files(self, works_root: str, date: str) -> list[str]:
        raise NotImplementedError

    def _path_exists(self, path: str) -> bool:
        raise NotImplementedError

    def _ensure_dir(self, path: str) -> None:
        raise NotImplementedError

    def _remove_tree(self, path: str) -> None:
        raise NotImplementedError

    def _write_text(self, path: str, text: str) -> None:
        raise NotImplementedError

    def _query(self, sql: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _exec(self, sql: str, *, timeout_s: float | None = None) -> None:
        raise NotImplementedError


class SshDuckDbStore(_DuckDbWorksStore):
    """Run DuckDB over SSH on the host that holds the parquet snapshot."""

    def __init__(
        self,
        *,
        ssh_host: str,
        parquet_glob: str,
        ssh_user: str = "",
        duckdb_bin: str = "duckdb",
        timeout_s: float = 120.0,
        cites_index_glob: str = "",
        runner: Any = None,
        exec_runner: Any = None,
    ):
        super().__init__(
            parquet_glob=parquet_glob,
            duckdb_bin=duckdb_bin,
            timeout_s=timeout_s,
            cites_index_glob=cites_index_glob,
        )
        self.ssh_host = ssh_host.strip()
        self.ssh_user = (ssh_user or "").strip()
        self._runner = runner or _run_ssh_duckdb
        self._exec_runner = exec_runner or _run_ssh_duckdb_exec
        if not self.ssh_host:
            raise OpenAlexStoreError("openalex_store.ssh_host is required")

    def _ssh_target(self) -> str:
        return f"{self.ssh_user}@{self.ssh_host}" if self.ssh_user else self.ssh_host

    def _ssh_run(self, remote: str, *, timeout_s: float = 120.0) -> str:
        cmd = ["ssh", "-o", "BatchMode=yes", self._ssh_target(), remote]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise OpenAlexStoreError(f"openalex store SSH failed: {exc}") from exc
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise OpenAlexStoreError(f"openalex store SSH failed: {err}")
        return proc.stdout or ""

    def _list_updated_dates(self, works_root: str) -> list[str]:
        remote = (
            f"ls -1d {shlex.quote(works_root.rstrip('/') + '/updated_date=*')} "
            "2>/dev/null || true"
        )
        lines = [line.strip() for line in self._ssh_run(remote).splitlines() if line.strip()]
        dates = sorted({updated_date_from_dirname(line) for line in lines if line})
        return [d for d in dates if d]

    def _list_works_parquet_files(self, works_root: str, date: str) -> list[str]:
        remote = (
            f"ls -1 {shlex.quote(works_root.rstrip('/') + '/updated_date=' + date)}/"
            "*.parquet 2>/dev/null || true"
        )
        return sorted(
            line.strip()
            for line in self._ssh_run(remote).splitlines()
            if line.strip().endswith(".parquet")
        )

    def _path_exists(self, path: str) -> bool:
        remote = f"test -e {shlex.quote(path)} && echo yes || echo no"
        return self._ssh_run(remote).strip() == "yes"

    def _ensure_dir(self, path: str) -> None:
        self._ssh_run(f"mkdir -p {shlex.quote(path)}")

    def _remove_tree(self, path: str) -> None:
        self._ssh_run(f"rm -rf {shlex.quote(path)}")

    def _write_text(self, path: str, text: str) -> None:
        parent = str(Path(path).parent)
        self._ensure_dir(parent)
        # Base64 avoids nested-quote breakage in ssh -c.
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        code = (
            "import base64, pathlib\n"
            f"pathlib.Path({path!r}).write_bytes(base64.b64decode({b64!r}))\n"
        )
        self._ssh_run(f"python3 -c {shlex.quote(code)}")

    def _query(self, sql: str) -> list[dict[str, Any]]:
        stdout = self._runner(
            host=self.ssh_host,
            user=self.ssh_user,
            duckdb_bin=self.duckdb_bin,
            sql=sql,
            timeout_s=self.timeout_s,
        )
        return parse_duckdb_json(stdout)

    def _exec(self, sql: str, *, timeout_s: float | None = None) -> None:
        self._exec_runner(
            host=self.ssh_host,
            user=self.ssh_user,
            duckdb_bin=self.duckdb_bin,
            sql=sql,
            timeout_s=float(timeout_s) if timeout_s is not None else self.timeout_s,
        )


class LocalDuckDbStore(_DuckDbWorksStore):
    """Run DuckDB on this machine over a local parquet glob."""

    def __init__(
        self,
        *,
        parquet_glob: str,
        duckdb_bin: str = "duckdb",
        timeout_s: float = 120.0,
        cites_index_glob: str = "",
        runner: Any = None,
        exec_runner: Any = None,
    ):
        super().__init__(
            parquet_glob=parquet_glob,
            duckdb_bin=duckdb_bin,
            timeout_s=timeout_s,
            cites_index_glob=cites_index_glob,
        )
        self._runner = runner or _run_local_duckdb
        self._exec_runner = exec_runner or _run_local_duckdb_exec

    def _list_updated_dates(self, works_root: str) -> list[str]:
        root = Path(works_root)
        if not root.is_dir():
            return []
        dates = [
            updated_date_from_dirname(path.name)
            for path in root.glob("updated_date=*")
            if path.is_dir()
        ]
        return sorted({d for d in dates if d})

    def _list_works_parquet_files(self, works_root: str, date: str) -> list[str]:
        folder = Path(works_root) / f"updated_date={date}"
        if not folder.is_dir():
            return []
        return sorted(str(path) for path in folder.glob("*.parquet") if path.is_file())

    def _path_exists(self, path: str) -> bool:
        return Path(path).exists()

    def _ensure_dir(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    def _remove_tree(self, path: str) -> None:
        target = Path(path)
        if target.exists():
            shutil.rmtree(target)

    def _write_text(self, path: str, text: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def _query(self, sql: str) -> list[dict[str, Any]]:
        stdout = self._runner(
            duckdb_bin=self.duckdb_bin,
            sql=sql,
            timeout_s=self.timeout_s,
        )
        return parse_duckdb_json(stdout)

    def _exec(self, sql: str, *, timeout_s: float | None = None) -> None:
        self._exec_runner(
            duckdb_bin=self.duckdb_bin,
            sql=sql,
            timeout_s=float(timeout_s) if timeout_s is not None else self.timeout_s,
        )


def _run_local_duckdb(*, duckdb_bin: str, sql: str, timeout_s: float) -> str:
    return _run_duckdb_cmd(
        [duckdb_bin, "-json"], sql=sql, timeout_s=timeout_s, label="DuckDB"
    )


def _run_local_duckdb_exec(*, duckdb_bin: str, sql: str, timeout_s: float) -> None:
    _run_duckdb_cmd([duckdb_bin], sql=sql, timeout_s=timeout_s, label="DuckDB")


def _run_ssh_duckdb(
    *,
    host: str,
    user: str,
    duckdb_bin: str,
    sql: str,
    timeout_s: float,
) -> str:
    target = f"{user}@{host}" if user else host
    remote = f"{shlex.quote(duckdb_bin)} -json"
    return _run_duckdb_cmd(
        ["ssh", "-o", "BatchMode=yes", target, remote],
        sql=sql,
        timeout_s=timeout_s,
        label="SSH",
    )


def _run_ssh_duckdb_exec(
    *,
    host: str,
    user: str,
    duckdb_bin: str,
    sql: str,
    timeout_s: float,
) -> None:
    target = f"{user}@{host}" if user else host
    remote = shlex.quote(duckdb_bin)
    _run_duckdb_cmd(
        ["ssh", "-o", "BatchMode=yes", target, remote],
        sql=sql,
        timeout_s=timeout_s,
        label="SSH",
    )


def _run_duckdb_cmd(
    cmd: list[str], *, sql: str, timeout_s: float, label: str
) -> str:
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
            f"openalex store {label} timed out after {timeout_s:.0f}s"
        ) from exc
    except OSError as exc:
        raise OpenAlexStoreError(f"openalex store {label} failed: {exc}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise OpenAlexStoreError(f"openalex store DuckDB failed: {err}")
    return proc.stdout or ""


def _parquet_glob_from(cfg: Any) -> str:
    parquet_glob = str(getattr(cfg, "openalex_store_parquet_glob", "") or "").strip()
    if not parquet_glob:
        parquet_glob = os.environ.get(PARQUET_GLOB_ENV, "").strip()
    return parquet_glob


def _cites_index_glob_from(cfg: Any) -> str:
    cites = str(getattr(cfg, "openalex_store_cites_index_glob", "") or "").strip()
    if not cites:
        cites = os.environ.get(CITES_INDEX_GLOB_ENV, "").strip()
    return cites


def store_from_config(cfg: Any) -> WorksStore | None:
    """Build a works store from config, or None when unset / incomplete."""
    backend = str(getattr(cfg, "openalex_store_backend", "") or "").strip().lower()
    if not backend:
        return None

    duckdb_bin = str(getattr(cfg, "openalex_store_duckdb_bin", "") or "").strip() or "duckdb"
    timeout_s = float(getattr(cfg, "openalex_store_timeout_s", 120.0) or 120.0)
    parquet_glob = _parquet_glob_from(cfg)
    cites_index_glob = _cites_index_glob_from(cfg)

    if backend == "local_duckdb":
        if not parquet_glob:
            raise OpenAlexStoreError(
                "openalex_store backend local_duckdb needs parquet_glob "
                f"(or {PARQUET_GLOB_ENV})"
            )
        return LocalDuckDbStore(
            parquet_glob=parquet_glob,
            duckdb_bin=duckdb_bin,
            timeout_s=timeout_s,
            cites_index_glob=cites_index_glob,
        )

    if backend == "ssh_duckdb":
        host = str(getattr(cfg, "openalex_store_ssh_host", "") or "").strip()
        if not host:
            host = os.environ.get(SSH_HOST_ENV, "").strip()
        user = str(getattr(cfg, "openalex_store_ssh_user", "") or "").strip()
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
            cites_index_glob=cites_index_glob,
        )

    raise OpenAlexStoreError(
        f"openalex_store.backend {backend!r} is not supported yet "
        "(supported: ssh_duckdb, local_duckdb; later: http)"
    )


def build_cites_index_from_config(
    cfg: Any,
    *,
    output_dir: str = "",
    timeout_s: float | None = None,
    progress: Any = None,
) -> tuple[str, dict[str, int]]:
    """Build the inverted cites index; return ``(output_dir, counts)``.

    Counts keys: ``total``, ``built``, ``skipped`` (see ``build_cites_index``).
    Safe to re-run after a crash — completed ``updated_date`` partitions keep
    their ``.done/<date>`` markers.
    """
    store = store_from_config(cfg)
    if store is None:
        raise OpenAlexStoreError(
            "openalex_store.backend is unset — configure [openalex_store] first"
        )
    if not isinstance(store, _DuckDbWorksStore):
        raise OpenAlexStoreError("openalex store backend cannot build a cites index")
    out = (output_dir or "").strip()
    if not out:
        cites_glob = _cites_index_glob_from(cfg)
        # Derive a directory from a /**/*.parquet style glob when possible.
        if cites_glob.endswith("/**/*.parquet"):
            out = cites_glob[: -len("/**/*.parquet")]
        elif cites_glob.endswith("/*.parquet"):
            out = cites_glob[: -len("/*.parquet")]
        else:
            out = cites_glob.rstrip("/")
    if not out:
        raise OpenAlexStoreError(
            "pass --out or set openalex_store.cites_index_glob "
            f"(or {CITES_INDEX_GLOB_ENV})"
        )
    wait = (
        float(timeout_s)
        if timeout_s is not None
        else float(
            getattr(cfg, "openalex_store_build_timeout_s", 0) or DEFAULT_BUILD_TIMEOUT_S
        )
    )
    counts = store.build_cites_index(out, timeout_s=wait, progress=progress)
    return out, counts


def write_resumable_cites_build_script(
    *,
    works_root: str,
    output_dir: str,
    duckdb_bin: str,
    script_path: str,
    memory_limit: str = "48GB",
) -> str:
    """Write a bash script that builds cites one parquet file at a time.

    Safe to re-run after a crash: skips ``.done/<date>`` day markers and
    ``.done/<date>.parts/<stem>`` file markers. Huge ``updated_date`` folders
    (100G+) are processed file-by-file with a DuckDB memory limit + spill dir.
    Returns ``script_path``.
    """
    works = works_root.rstrip("/")
    out = output_dir.rstrip("/")
    duck = duckdb_bin.strip() or "duckdb"
    mem = (memory_limit or "48GB").strip() or "48GB"
    body = f"""#!/usr/bin/env bash
# Resumable OpenAlex cites index build (one works parquet file per DuckDB COPY).
set -euo pipefail
WORKS_ROOT={shlex.quote(works)}
OUT={shlex.quote(out)}
DUCKDB={shlex.quote(duck)}
MEM={shlex.quote(mem)}
LOG="${{OUT}}/build.log"
TMP="${{OUT}}/.duckdb_tmp"
mkdir -p "${{OUT}}/.done" "$TMP"
echo "$(date -Is) start resumable cites build (per-file, mem=$MEM)" | tee -a "$LOG"
shopt -s nullglob
days=("${{WORKS_ROOT}}"/updated_date=*)
total=${{#days[@]}}
if [[ "$total" -eq 0 ]]; then
  echo "no updated_date=* under $WORKS_ROOT" | tee -a "$LOG"
  exit 1
fi
i=0
for daydir in "${{days[@]}}"; do
  i=$((i + 1))
  day="${{daydir##*/updated_date=}}"
  marker="${{OUT}}/.done/${{day}}"
  if [[ -f "$marker" ]]; then
    echo "$(date -Is) skip ${{day}} (${{i}}/${{total}})" | tee -a "$LOG"
    continue
  fi
  files=("${{daydir}}"/*.parquet)
  nfiles=${{#files[@]}}
  if [[ "$nfiles" -eq 0 ]]; then
    echo "$(date -Is) no parquet under ${{day}} — marking done" | tee -a "$LOG"
    printf '%s\\n' "$day" > "$marker"
    continue
  fi
  mkdir -p "${{OUT}}/.done/${{day}}.parts"
  echo "$(date -Is) build ${{day}} (${{i}}/${{total}}, ${{nfiles}} files)" | tee -a "$LOG"
  f=0
  for parquet in "${{files[@]}}"; do
    f=$((f + 1))
    stem="${{parquet##*/}}"
    stem="${{stem%.parquet}}"
    fmarker="${{OUT}}/.done/${{day}}.parts/${{stem}}"
    dest="${{OUT}}/source_date=${{day}}/file=${{stem}}"
    if [[ -f "$fmarker" ]]; then
      echo "$(date -Is)   skip ${{stem}} (${{f}}/${{nfiles}})" | tee -a "$LOG"
      continue
    fi
    echo "$(date -Is)   build ${{stem}} (${{f}}/${{nfiles}})" | tee -a "$LOG"
    rm -rf "$dest"
    mkdir -p "$dest"
    sql=$(cat <<EOS
SET memory_limit = '{mem}';
SET temp_directory = '{out}/.duckdb_tmp';
COPY (
  SELECT
    regexp_extract(CAST(ref AS VARCHAR), '([^/]+)$', 1) AS cited_id,
    regexp_extract(coalesce(CAST(id AS VARCHAR), ''), '([^/]+)$', 1) AS citer_id,
    substr(
      regexp_extract(CAST(ref AS VARCHAR), '([^/]+)$', 1),
      1, 4
    ) AS cited_prefix
  FROM read_parquet('${{parquet}}', union_by_name := true) AS w,
       UNNEST(w.referenced_works) AS u(ref)
  WHERE cited_id IS NOT NULL AND cited_id <> ''
    AND citer_id IS NOT NULL AND citer_id <> ''
) TO '{out}/source_date=${{day}}/file=${{stem}}' (FORMAT PARQUET, PARTITION_BY (cited_prefix), OVERWRITE_OR_IGNORE);
EOS
)
    if ! printf '%s\\n' "$sql" | "$DUCKDB" >>"$LOG" 2>&1; then
      echo "$(date -Is) FAILED ${{day}}/${{stem}} — re-run script to resume" | tee -a "$LOG"
      rm -rf "$dest"
      exit 1
    fi
    printf '%s\\n' "$stem" > "$fmarker"
    echo "$(date -Is)   done ${{stem}} (${{f}}/${{nfiles}})" | tee -a "$LOG"
  done
  printf '%s\\n' "$day" > "$marker"
  echo "$(date -Is) done ${{day}} (${{i}}/${{total}})" | tee -a "$LOG"
done
echo "$(date -Is) all partitions complete ($total)" | tee -a "$LOG"
"""
    path = Path(script_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return str(path)
