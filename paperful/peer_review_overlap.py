"""Distinctive n-gram overlap vs library text already on disk."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from .config import Config
from .peer_review_extract import ExtractedDoc

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
    source_quote: str = ""


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


def load_library_pages(
    cfg: Config,
    *,
    exclude_key: str = "",
    keys: Iterable[str] | None = None,
) -> dict[str, list[tuple[int, str]]]:
    """``state/rag/text/<key>.json`` as 1-indexed page strings. No ingest."""
    from .store import load_json

    root = cfg.rag_dir / "text"
    if not root.is_dir():
        return {}
    wanted = set(keys) if keys is not None else None
    out: dict[str, list[tuple[int, str]]] = {}
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
        numbered: list[tuple[int, str]] = []
        for i, raw in enumerate(pages, start=1):
            text = _drop_biblio(str(raw) if raw is not None else "")
            if text.strip():
                numbered.append((i, text))
        if numbered:
            out[key] = numbered
    return out


def load_library_texts(
    cfg: Config,
    *,
    exclude_key: str = "",
    keys: Iterable[str] | None = None,
) -> dict[str, str]:
    """``state/rag/text/<key>.json`` pages joined. No ingest side effect."""
    pages = load_library_pages(cfg, exclude_key=exclude_key, keys=keys)
    out: dict[str, str] = {}
    for key, numbered in pages.items():
        text = "\n".join(chunk for _n, chunk in numbered)
        if text.strip():
            out[key] = text
    return out


def _prefix_postings(
    prefixes: set[tuple[str, ...]],
    tokenized: dict[str, list[str]],
    n_min: int,
) -> tuple[dict[tuple[str, ...], list[str]], dict[str, str]]:
    """One pass: n-min windows that hit ``prefixes``, plus joined token strings."""
    postings: dict[tuple[str, ...], list[str]] = {}
    joined: dict[str, str] = {}
    if n_min < 1 or not prefixes:
        for key, toks in tokenized.items():
            joined[key] = " ".join(toks)
        return postings, joined
    for key, toks in tokenized.items():
        joined[key] = " ".join(toks)
        if len(toks) < n_min:
            continue
        seen: set[tuple[str, ...]] = set()
        for i in range(0, len(toks) - n_min + 1):
            pref = tuple(toks[i : i + n_min])
            if pref not in prefixes or pref in seen:
                continue
            seen.add(pref)
            postings.setdefault(pref, []).append(key)
    return postings, joined


def _phrase_df(
    gram: tuple[str, ...],
    phrase: str,
    n_min: int,
    postings: dict[tuple[str, ...], list[str]],
    joined: dict[str, str],
) -> int:
    pref = gram[:n_min] if len(gram) >= n_min else gram
    candidates = postings.get(pref, ())
    if len(gram) == n_min:
        return len(candidates)
    return sum(1 for key in candidates if phrase in joined[key])


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
    prefixes = {gram[:n_min] if len(gram) >= n_min else gram for gram in tf}
    tokenized = {k: _tokens(v) for k, v in corpus.items()}
    postings, joined = _prefix_postings(prefixes, tokenized, n_min)
    scored: list[tuple[str, float, int]] = []
    seen: set[str] = set()
    df_cap = df_max if df_max is not None else max(2, n_docs // 4 or 1)
    for gram, count in tf.items():
        phrase = " ".join(gram)
        if phrase in seen:
            continue
        seen.add(phrase)
        df = _phrase_df(gram, phrase, n_min, postings, joined)
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
    needles: list[tuple[str, tuple[str, ...]]] = []
    prefixes: set[tuple[str, ...]] = set()
    for phrase, _score, _df in phrases:
        words = tuple(phrase.split())
        if len(words) < n_min:
            continue
        pref = words[:n_min]
        needles.append((phrase, pref))
        prefixes.add(pref)
    if not needles:
        return hits
    tokenized = {k: _tokens(v) for k, v in corpus.items()}
    postings, joined = _prefix_postings(prefixes, tokenized, n_min)
    for phrase, pref in needles:
        n_words = len(phrase.split())
        for key in postings.get(pref, ()):
            if phrase not in joined[key]:
                continue
            hits.append(
                OverlapHit(
                    other_key=key,
                    ngram=phrase,
                    n_words=n_words,
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
        except Exception:  # noqa: S112 -- best-effort loop; intentionally continues
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
        n_min=cfg.peer_review_overlap_n_min,
        n_max=cfg.peer_review_overlap_n_max,
        top_k=cfg.peer_review_overlap_top_k,
        df_max=cfg.peer_review_overlap_df_max or None,
    )
    hits = match_phrases(ranked, corpus, n_min=cfg.peer_review_overlap_n_min)
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
    collapsed = collapse_nested_hits(hits, target_text=doc.text)
    pages = load_library_pages(cfg, exclude_key=exclude_key, keys=scope_keys)
    return annotate_hit_locators(collapsed, pages), ""


def _span_in(hay: str, phrase: str) -> tuple[int, int] | None:
    needle = " ".join(_tokens(phrase))
    if not needle or not hay:
        return None
    i = hay.find(needle)
    if i < 0:
        return None
    return i, i + len(needle)


def original_span_for_phrase(text: str, phrase: str) -> tuple[int, int] | None:
    """First token-aligned span of ``phrase`` in ``text``, or None."""
    words = _tokens(phrase)
    n = len(words)
    if n < 1 or not text:
        return None
    spans = [(m.start(), m.end(), m.group(0).lower()) for m in _TOKEN.finditer(text)]
    if len(spans) < n:
        return None
    for i in range(0, len(spans) - n + 1):
        if all(spans[i + j][2] == words[j] for j in range(n)):
            return spans[i][0], spans[i + n - 1][1]
    return None


def unquoted_span_for_phrase(text: str, phrase: str) -> tuple[int, int] | None:
    """First occurrence of ``phrase`` that is not entirely inside quotes."""
    from .peer_review_direct_quotes import span_in_direct_quote

    words = _tokens(phrase)
    n = len(words)
    if n < 1 or not text:
        return None
    spans = [(m.start(), m.end(), m.group(0).lower()) for m in _TOKEN.finditer(text)]
    if len(spans) < n:
        return None
    for i in range(0, len(spans) - n + 1):
        if not all(spans[i + j][2] == words[j] for j in range(n)):
            continue
        start, end = spans[i][0], spans[i + n - 1][1]
        if not span_in_direct_quote(text, start, end):
            return start, end
    return None


def locate_phrase_in_pages(
    pages: Iterable[tuple[int, str]],
    phrase: str,
) -> tuple[str, str]:
    """Page locator ``p. N`` and a substring of that page that matches ``phrase``."""
    for num, raw in pages:
        span = original_span_for_phrase(raw, phrase)
        if span is None:
            continue
        quote = raw[span[0] : span[1]].strip()
        if not quote:
            continue
        return f"p. {num}", quote
    return "", ""


def overlap_action(hit: OverlapHit) -> str:
    """``quote`` / ``cite`` when the library page contains the span; else ``review``."""
    if not (hit.source_quote or "").strip():
        return "review"
    if hit.n_words >= 20:
        return "quote"
    return "cite"


def group_overlap_action(group: list[OverlapHit]) -> str:
    exact = [h for h in group if (h.source_quote or "").strip()]
    if not exact:
        return "review"
    if max(h.n_words for h in exact) >= 20:
        return "quote"
    return "cite"


def annotate_hit_locators(
    hits: list[OverlapHit],
    pages_by_key: dict[str, list[tuple[int, str]]],
) -> list[OverlapHit]:
    """Fill ``other_loc`` / ``source_quote`` from stored pages when the phrase occurs."""
    for h in hits:
        loc, quote = locate_phrase_in_pages(pages_by_key.get(h.other_key, ()), h.ngram)
        if quote:
            h.source_quote = quote
            h.other_loc = loc or h.other_loc
    return hits


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
