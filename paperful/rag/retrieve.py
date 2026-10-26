"""Find the passages closest to a question. No chat model is involved."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from ..config import Config
from ..llm.embed import Embedder, get_embedder
from .index import Index, ledger_path
from .ledger import Ledger

# Defaults; search uses [rag].max_chunks_per_item and [rag].overfetch.
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
    publication_title: str = ""
    doi: str = ""
    item_type: str = ""
    vector: list[float] | None = None
    summary: str | None = None
    relevance_score: int | None = None

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


def _hit_from_row(row: dict, meta) -> Hit:
    vector = row.get("vector")
    return Hit(
        item_key=str(row["item_key"]),
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
        publication_title=(meta.publication_title if meta else "") or "",
        doi=(meta.doi if meta else "") or "",
        item_type=(meta.item_type if meta else "") or "",
        vector=[float(x) for x in vector] if vector is not None else None,
    )


def _cap_hits(hits: list[Hit], *, k: int, per_item: int) -> list[Hit]:
    out: list[Hit] = []
    counts: dict[str, int] = {}
    for hit in hits:
        if counts.get(hit.item_key, 0) >= per_item:
            continue
        counts[hit.item_key] = counts.get(hit.item_key, 0) + 1
        out.append(hit)
        if len(out) >= k:
            break
    return out


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def mmr_select(hits: list[Hit], k: int, lambda_: float) -> list[Hit]:
    """Diversity rerank. ``lambda_`` 1.0 is pure relevance and is skipped."""
    if lambda_ >= 1.0 or k <= 0 or len(hits) <= 1:
        return hits[:k]
    usable = [h for h in hits if h.vector]
    if not usable:
        return hits[:k]
    selected = [usable.pop(0)]
    while usable and len(selected) < k:
        best_i = 0
        best_val = -1e9
        for i, cand in enumerate(usable):
            sim_sel = max(_cos(cand.vector or [], s.vector or []) for s in selected)
            val = lambda_ * cand.score - (1.0 - lambda_) * sim_sel
            if val > best_val:
                best_val = val
                best_i = i
        selected.append(usable.pop(best_i))
    return selected


def rrf_merge(rankings: list[list[Hit]], k: int) -> list[Hit]:
    """Reciprocal rank fusion. Higher fused score first."""
    scores: dict[tuple[str, int], float] = {}
    by_id: dict[tuple[str, int], Hit] = {}
    k_rrf = 60
    for ranking in rankings:
        for rank, hit in enumerate(ranking, 1):
            key = (hit.item_key, hit.chunk_index)
            by_id[key] = hit
            scores[key] = scores.get(key, 0.0) + 1.0 / (k_rrf + rank)
    ordered = sorted(scores, key=lambda key: -scores[key])
    return [by_id[key] for key in ordered[:k]]


def attach_neighbors(cfg: Config, hits: list[Hit], index: Index) -> list[Hit]:
    """Append the next stored chunk's text onto each hit. Default n is 0."""
    n = cfg.rag_context_neighbors
    if n <= 0 or not hits:
        return hits
    out: list[Hit] = []
    for hit in hits:
        extra: list[str] = []
        for offset in range(1, n + 1):
            row = index.fetch_chunk(hit.item_key, hit.chunk_index + offset)
            if not row or not row.get("text"):
                break
            extra.append(str(row["text"]))
        if extra:
            hit = replace(hit, text=hit.text + "\n\n" + "\n\n".join(extra))
        out.append(hit)
    return out


def search(
    cfg: Config,
    query: str,
    *,
    k: int | None = None,
    keys: set[str] | None = None,
    embedder: Embedder | None = None,
    index: Index | None = None,
    ledger: Ledger | None = None,
    include_vector: bool = False,
) -> list[Hit]:
    """The ``k`` best passages for ``query``, best first, with their paper's details."""
    k = k or cfg.rag_top_k
    if not query.strip() or (keys is not None and not keys):
        return []
    index = index or Index.open(cfg)
    embedder = embedder or get_embedder(cfg)
    ledger = ledger or Ledger(ledger_path(cfg))
    per_item = cfg.rag_max_chunks_per_item
    overfetch = cfg.rag_overfetch
    rows = index.search(
        embedder.embed_query(query),
        query,
        k=k * overfetch,
        keys=keys,
        hybrid=cfg.rag_hybrid,
        include_vector=include_vector,
    )
    hits = [_hit_from_row(row, ledger.get(str(row["item_key"]))) for row in rows]
    return _cap_hits(hits, k=k, per_item=per_item)


def search_fused(
    cfg: Config,
    queries: list[str],
    *,
    k: int,
    keys: set[str] | None = None,
    embedder: Embedder | None = None,
    index: Index | None = None,
    ledger: Ledger | None = None,
) -> list[Hit]:
    """Hybrid-search each query and merge with reciprocal rank fusion."""
    cleaned = [q.strip() for q in queries if q and q.strip()]
    if not cleaned:
        return []
    want_mmr = cfg.rag_mmr_lambda < 1.0
    if len(cleaned) == 1:
        hits = search(
            cfg,
            cleaned[0],
            k=k,
            keys=keys,
            embedder=embedder,
            index=index,
            ledger=ledger,
            include_vector=want_mmr,
        )
    else:
        rankings = [
            search(
                cfg,
                q,
                k=k,
                keys=keys,
                embedder=embedder,
                index=index,
                ledger=ledger,
                include_vector=want_mmr,
            )
            for q in cleaned
        ]
        fused = rrf_merge(rankings, k * cfg.rag_overfetch)
        hits = _cap_hits(fused, k=k, per_item=cfg.rag_max_chunks_per_item)
    if want_mmr:
        hits = mmr_select(hits, k, cfg.rag_mmr_lambda)
    index = index or Index.open(cfg)
    return attach_neighbors(cfg, hits, index)
