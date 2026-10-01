"""Find the passages closest to a question. No chat model is involved."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..config import Config
from ..llm.embed import Embedder, get_embedder
from .index import Index, ledger_path
from .ledger import Ledger

# Ask the index for more than k, so the per-item cap still leaves k passages.
_OVERFETCH = 3
# One long paper should not crowd every other source out of the context.
MAX_CHUNKS_PER_ITEM = 3


@dataclass
class Hit:
    item_key: str
    chunk_index: int
    text: str
    score: float
    source: str = "pdf"  # pdf | ocr | abstract
    section: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None

    @property
    def pages(self) -> str:
        """``p. 3``, ``pp. 3-4``, or ``abstract`` when the passage has no page."""
        if self.page_start is None:
            return "abstract" if self.source == "abstract" else ""
        if self.page_end is None or self.page_end == self.page_start:
            return f"p. {self.page_start}"
        return f"pp. {self.page_start}-{self.page_end}"


def scope_keys(
    ledger: Ledger,
    *,
    collections: Iterable[str] | None = None,
    item_keys: Iterable[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    item_types: frozenset[str] | None = None,
) -> set[str] | None:
    """Indexed items inside a scope, or None when no filter was given.

    A collection is a folder path prefix under ``out_dir``, read from the
    ledger, so this never walks the mirror.
    """
    prefixes = [p.strip("/") for p in (collections or []) if p and p.strip("/")]
    wanted = set(item_keys or [])
    if not prefixes and not wanted and year_from is None and year_to is None and not item_types:
        return None
    keys: set[str] = set()
    for row in ledger.rows():
        if wanted and row.key not in wanted:
            continue
        if prefixes:
            parents = [d.rsplit("/", 1)[0] if "/" in d else "" for d in row.dirs]
            if not any(
                c == pre or c.startswith(pre + "/") for c in parents for pre in prefixes
            ):
                continue
        if year_from is not None or year_to is not None:
            if row.year is None:
                continue
            if year_from is not None and row.year < year_from:
                continue
            if year_to is not None and row.year > year_to:
                continue
        if item_types and row.item_type not in item_types:
            continue
        keys.add(row.key)
    return keys


def search(
    cfg: Config,
    query: str,
    *,
    k: int | None = None,
    keys: set[str] | None = None,
    embedder: Embedder | None = None,
    index: Index | None = None,
    ledger: Ledger | None = None,
) -> list[Hit]:
    """The ``k`` best passages for ``query``, best first, with their paper's details."""
    k = k or cfg.rag_top_k
    if not query.strip() or (keys is not None and not keys):
        return []
    index = index or Index.open(cfg)
    embedder = embedder or get_embedder(cfg)
    ledger = ledger or Ledger(ledger_path(cfg))
    rows = index.search(
        embedder.embed_query(query),
        query,
        k=k * _OVERFETCH,
        keys=keys,
        hybrid=cfg.rag_hybrid,
    )
    hits: list[Hit] = []
    per_item: dict[str, int] = {}
    for row in rows:
        key = str(row["item_key"])
        if per_item.get(key, 0) >= MAX_CHUNKS_PER_ITEM:
            continue
        per_item[key] = per_item.get(key, 0) + 1
        meta = ledger.get(key)
        hits.append(
            Hit(
                item_key=key,
                chunk_index=int(row["chunk_index"] or 0),
                text=str(row["text"] or ""),
                score=float(row["score"]),
                source=str(row["source"] or "pdf"),
                section=row["section"] or None,
                page_start=row["page_start"],
                page_end=row["page_end"],
                title=meta.title if meta else "",
                authors=list(meta.authors) if meta else [],
                year=meta.year if meta else None,
            )
        )
        if len(hits) >= k:
            break
    return hits
