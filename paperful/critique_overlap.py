"""Distinctive n-gram overlap vs library text already on disk."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from .config import Config
from .critique_extract import ExtractedDoc

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")
_STOP = frozenset(
    """
    a an the and or but if of to in on for with from by as at is are was were
    be been being this that those these it its they them their we our you your
    not no nor so than then also into over after before about than such using
    used use between among within without through per via vs versus et al
    """.split()
)
_BIBLIO_HEAD = re.compile(
    r"(?im)^(?:\d+\.?\s*)?(references?|bibliography|acknowledgements?|literature cited)\s*$"
)


@dataclass
class OverlapHit:
    other_key: str
    ngram: str
    n_words: int
    source: str  # phrase | rag_hybrid
    other_loc: str = ""


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def _drop_biblio(text: str) -> str:
    lines = (text or "").splitlines()
    kept: list[str] = []
    for line in lines:
        if _BIBLIO_HEAD.match(line.strip()):
            break
        kept.append(line)
    return "\n".join(kept)


def _ngrams(tokens: list[str], n_min: int, n_max: int) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for n in range(n_min, n_max + 1):
        if len(tokens) < n:
            continue
        for i in range(0, len(tokens) - n + 1):
            gram = tuple(tokens[i : i + n])
            if all(t in _STOP for t in gram):
                continue
            out.append(gram)
    return out


def load_library_texts(
    cfg: Config,
    *,
    exclude_key: str = "",
    keys: Iterable[str] | None = None,
) -> dict[str, str]:
    """``state/rag/text/<key>.json`` pages joined. No ingest side effect."""
    from .store import load_json

    root = cfg.rag_dir / "text"
    if not root.is_dir():
        return {}
    wanted = set(keys) if keys is not None else None
    out: dict[str, str] = {}
    for path in root.glob("*.json"):
        key = path.stem
        if key == exclude_key:
            continue
        if wanted is not None and key not in wanted:
            continue
        stored = load_json(path)
        if not isinstance(stored, dict):
            continue
        pages = stored.get("pages")
        if not isinstance(pages, list):
            continue
        text = _drop_biblio("\n".join(str(p) for p in pages))
        if text.strip():
            out[key] = text
    return out


def rank_phrases(
    target: str,
    corpus: dict[str, str],
    *,
    n_min: int = 6,
    n_max: int = 12,
    top_k: int = 40,
    df_max: int | None = None,
) -> list[tuple[str, float, int]]:
    """Return (phrase, tfidf, df) distinctive in this library."""
    target_tokens = _tokens(_drop_biblio(target))
    grams = _ngrams(target_tokens, n_min, n_max)
    if not grams:
        return []
    tf = Counter(grams)
    n_docs = max(1, len(corpus))
    folded = {k: " ".join(_tokens(v)) for k, v in corpus.items()}
    scored: list[tuple[str, float, int]] = []
    seen: set[str] = set()
    df_cap = df_max if df_max is not None else max(2, n_docs // 4 or 1)
    for gram, count in tf.items():
        phrase = " ".join(gram)
        if phrase in seen:
            continue
        seen.add(phrase)
        df = sum(1 for body in folded.values() if phrase in body)
        if df < 1 or df >= df_cap:
            continue
        idf = math.log((n_docs + 1) / (df + 1))
        scored.append((phrase, count * idf, df))
    scored.sort(key=lambda row: (-row[1], -len(row[0].split()), row[0]))
    return scored[: max(1, top_k)]


def match_phrases(
    phrases: list[tuple[str, float, int]],
    corpus: dict[str, str],
    *,
    n_min: int = 6,
) -> list[OverlapHit]:
    hits: list[OverlapHit] = []
    for phrase, _score, _df in phrases:
        words = phrase.split()
        if len(words) < n_min:
            continue
        for key, body in corpus.items():
            hay = " ".join(_tokens(body))
            if phrase not in hay:
                continue
            hits.append(
                OverlapHit(
                    other_key=key,
                    ngram=phrase,
                    n_words=len(words),
                    source="phrase",
                )
            )
    return hits


def rag_hybrid_boost(
    cfg: Config,
    phrases: list[tuple[str, float, int]],
    *,
    exclude_key: str,
    scope_keys: set[str] | None,
) -> list[OverlapHit]:
    """Optional paraphrase recall. Needs ``[rag].enabled`` and an index."""
    if not cfg.rag_enabled:
        return []
    try:
        from .rag.index import Index
        from .rag.retrieve import search
    except Exception:
        return []
    hits: list[OverlapHit] = []
    try:
        index = Index.open(cfg)
    except Exception:
        return []
    keys = None if scope_keys is None else {k for k in scope_keys if k != exclude_key}
    for phrase, _score, _df in phrases[:12]:
        try:
            rows = search(cfg, phrase, k=5, keys=keys, index=index)
        except Exception:
            continue
        for row in rows:
            if row.item_key == exclude_key:
                continue
            window = " ".join(_tokens(row.text or ""))
            if len(phrase.split()) < 6:
                continue
            ratio = SequenceMatcher(None, phrase, window[: len(phrase) + 40]).ratio()
            if phrase not in window and ratio < 0.9:
                continue
            hits.append(
                OverlapHit(
                    other_key=row.item_key,
                    ngram=phrase,
                    n_words=len(phrase.split()),
                    source="rag_hybrid",
                    other_loc=row.pages,
                )
            )
    return hits


def overlap_findings(
    cfg: Config,
    doc: ExtractedDoc,
    *,
    exclude_key: str = "",
    scope_keys: Iterable[str] | None = None,
) -> tuple[list[OverlapHit], str]:
    """Hits plus a skip reason (empty when the checker ran)."""
    corpus = load_library_texts(cfg, exclude_key=exclude_key, keys=scope_keys)
    if not corpus:
        return [], "overlap_skipped_no_text"
    ranked = rank_phrases(
        doc.text,
        corpus,
        n_min=cfg.critique_overlap_n_min,
        n_max=cfg.critique_overlap_n_max,
        top_k=cfg.critique_overlap_top_k,
        df_max=cfg.critique_overlap_df_max or None,
    )
    hits = match_phrases(ranked, corpus, n_min=cfg.critique_overlap_n_min)
    extra = rag_hybrid_boost(
        cfg,
        ranked,
        exclude_key=exclude_key,
        scope_keys=set(scope_keys) if scope_keys is not None else None,
    )
    seen = {(h.other_key, h.ngram, h.source) for h in hits}
    for h in extra:
        ident = (h.other_key, h.ngram, h.source)
        if ident not in seen:
            hits.append(h)
            seen.add(ident)
    return collapse_nested_hits(hits, target_text=doc.text), ""


def _span_in(hay: str, phrase: str) -> tuple[int, int] | None:
    needle = " ".join(_tokens(phrase))
    if not needle or not hay:
        return None
    i = hay.find(needle)
    if i < 0:
        return None
    return i, i + len(needle)


def collapse_nested_hits(
    hits: list[OverlapHit], *, target_text: str = ""
) -> list[OverlapHit]:
    """Keep the longest span per other item; drop nested or overlapping windows."""
    hay = " ".join(_tokens(target_text)) if target_text else ""
    by_other: dict[tuple[str, str], list[OverlapHit]] = {}
    for h in hits:
        by_other.setdefault((h.other_key, h.source), []).append(h)
    out: list[OverlapHit] = []
    for group in by_other.values():
        kept: list[tuple[OverlapHit, tuple[int, int] | None]] = []
        for h in sorted(group, key=lambda row: (-row.n_words, row.ngram)):
            span = _span_in(hay, h.ngram)
            drop = False
            for k, kspan in kept:
                if h.ngram != k.ngram and h.ngram in k.ngram:
                    drop = True
                    break
                if span and kspan and span[0] < kspan[1] and kspan[0] < span[1]:
                    drop = True
                    break
            if drop:
                continue
            kept.append((h, span))
        out.extend(h for h, _span in kept)
    return out
