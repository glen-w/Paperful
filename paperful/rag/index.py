"""The vector store. Every LanceDB call in Paperful lives in this module.

One folder per embedding model under ``state_dir/rag``: the table, the ingest
ledger and a ``meta.json`` naming the model that produced the vectors. Vectors
from two models are never mixed; a new model gets a new folder.
"""

from __future__ import annotations

import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from ..config import Config
from ..llm.embed import embed_fingerprint, task_prefixes
from ..store import load_json, write_json

META_SCHEMA = "paperful.rag.index.v1"
INDEX_VERSION = 1
TABLE = "chunks"
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._-]+$")
_COLUMNS = (
    "chunk_id",
    "item_key",
    "chunk_index",
    "source",
    "section",
    "page_start",
    "page_end",
    "text",
)


class RagUnavailable(Exception):
    """``paperful[rag]`` is not installed."""


class IndexMissing(Exception):
    """Nothing has been ingested for the configured embedding model."""


class IndexMismatch(Exception):
    """The index on disk was built with different embedding settings."""


def index_dir(cfg: Config) -> Path:
    return cfg.rag_dir / embed_fingerprint(cfg.rag_embed_provider, cfg.rag_embed_model)


def ledger_path(cfg: Config) -> Path:
    return index_dir(cfg) / "ingest.jsonl"


def meta_path(cfg: Config) -> Path:
    return index_dir(cfg) / "meta.json"


def load_meta(cfg: Config) -> dict[str, Any] | None:
    return load_json(meta_path(cfg))


def _lancedb() -> Any:
    try:
        import lancedb
    except ImportError as exc:
        raise RagUnavailable(
            "lancedb is not installed; pip install 'paperful[rag]'"
        ) from exc
    return lancedb


def _key_filter(keys: set[str]) -> str:
    for key in keys:
        if not _SAFE_KEY.match(key):
            raise ValueError(f"unsafe item key {key!r}")
    quoted = ", ".join(f"'{key}'" for key in sorted(keys))
    return f"item_key IN ({quoted})"


def _expected_meta(cfg: Config, dim: int) -> dict[str, Any]:
    doc_prefix, query_prefix = task_prefixes(cfg.rag_embed_model)
    return {
        "schema": META_SCHEMA,
        "index_version": INDEX_VERSION,
        "provider": cfg.rag_embed_provider,
        "model": cfg.rag_embed_model.strip(),
        "dim": dim,
        "doc_prefix": doc_prefix,
        "query_prefix": query_prefix,
    }


class Index:
    def __init__(self, table: Any, meta: dict[str, Any], path: Path):
        self._table = table
        self.meta = meta
        self.path = path

    @property
    def dim(self) -> int:
        return int(self.meta["dim"])

    @classmethod
    def open(cls, cfg: Config, *, dim: int | None = None, create: bool = False) -> Index:
        """Open the index for the configured embedding model.

        ``create`` makes it when absent and needs ``dim``. ``meta.json`` is
        written before the table, so vectors on disk always have a named model.
        """
        lancedb = _lancedb()
        folder = index_dir(cfg)
        meta = load_meta(cfg)
        if meta is None:
            if not create:
                raise IndexMissing(
                    f"no index for {cfg.rag_embed_model!r} yet; run `paperful rag ingest`"
                )
            if dim is None:
                raise ValueError("dim is required to create an index")
            meta = {**_expected_meta(cfg, dim), "created": time.time()}
            write_json(meta_path(cfg), meta)
        want = _expected_meta(cfg, int(meta.get("dim") or 0))
        if dim is not None:
            want["dim"] = dim
        for name, value in want.items():
            if meta.get(name) != value:
                raise IndexMismatch(
                    f"index at {folder} has {name} = {meta.get(name)!r}, "
                    f"but the configuration gives {value!r}. "
                    "Delete that folder and run `paperful rag ingest` to rebuild it."
                )
        db = lancedb.connect(str(folder / "lancedb"))
        if TABLE in db.list_tables().tables:
            table = db.open_table(TABLE)
        elif create:
            table = db.create_table(TABLE, schema=_schema(int(meta["dim"])))
        else:
            raise IndexMissing(
                f"no index for {cfg.rag_embed_model!r} yet; run `paperful rag ingest`"
            )
        return cls(table, meta, folder)

    def replace_item(self, key: str, rows: list[dict[str, Any]]) -> None:
        """Swap an item's passages for ``rows``. An empty list removes the item."""
        for row in rows:
            if len(row["vector"]) != self.dim:
                raise IndexMismatch(
                    f"embedding has {len(row['vector'])} dimensions; "
                    f"the index holds {self.dim}"
                )
        self._table.delete(_key_filter({key}))
        if rows:
            self._table.add(rows)

    def delete_items(self, keys: set[str]) -> None:
        if keys:
            self._table.delete(_key_filter(keys))

    def count(self) -> int:
        return int(self._table.count_rows())

    def search(
        self,
        vector: list[float],
        text: str,
        *,
        k: int,
        keys: set[str] | None = None,
        hybrid: bool = True,
    ) -> list[dict[str, Any]]:
        """Nearest passages, best first. Each row gets a ``score`` (higher is closer).

        ``hybrid`` blends vector and full-text ranks; it needs the full-text
        index that ``finish`` builds and quietly degrades to vector-only without it.
        """
        if keys is not None and not keys:
            return []
        where = _key_filter(keys) if keys is not None else None
        if hybrid and text.strip():
            try:
                query = self._table.search(query_type="hybrid").vector(vector).text(text)
                if where:
                    query = query.where(where)
                rows = query.limit(k).to_list()
                return [_hit(row, row.get("_relevance_score")) for row in rows]
            except Exception:
                pass
        query = self._table.search(vector)
        if where:
            query = query.where(where)
        rows = query.limit(k).to_list()
        # Unit vectors: squared L2 distance d gives cosine similarity 1 - d / 2.
        return [_hit(row, 1.0 - float(row.get("_distance") or 0.0) / 2.0) for row in rows]

    def finish(self) -> None:
        """Compact what an ingest run wrote and bring the full-text index up to date."""
        from lancedb.index import FTS

        if self.count() == 0:
            return
        if not any(
            getattr(index, "index_type", "") == "FTS"
            for index in self._table.list_indices()
        ):
            self._table.create_index("text", config=FTS())
        self._table.optimize(cleanup_older_than=timedelta(0))


def _hit(row: dict[str, Any], score: Any) -> dict[str, Any]:
    hit = {name: row.get(name) for name in _COLUMNS}
    hit["score"] = float(score or 0.0)
    return hit


def _schema(dim: int) -> Any:
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("chunk_id", pa.string()),
            pa.field("item_key", pa.string()),
            pa.field("chunk_index", pa.int32()),
            pa.field("source", pa.string()),
            pa.field("section", pa.string()),
            pa.field("page_start", pa.int32()),
            pa.field("page_end", pa.int32()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
        ]
    )
