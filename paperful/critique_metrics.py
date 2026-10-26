"""Readability and lexical-diversity metrics for critique packs.

Lexical diversity (tokenizer, TTR, hapax, bidirectional MTLD) follows
TranscriptX ``core/utils/lexical_diversity.py`` (copied, not imported).
Readability formulas follow Transcribe's stdlib adaptation of Flesch /
Gunning Fog / ARI — no nltk or textstat.
"""

from __future__ import annotations

import math
import re
from typing import Any

MTLD_FACTOR_THRESHOLD = 0.72
MIN_MTLD_TOKENS = 50
LONG_SENTENCE_WORDS = 60
MAX_LONG_SENTENCES = 5

TOKEN_RE = re.compile(r"[^\W\d_]+(?:['\u2019-][^\W\d_]+)*", re.UNICODE)
_SENTENCE_RE = re.compile(r"[^.?!]+[.?!]+|[^.?!]+$", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Return case-folded lexical tokens (TranscriptX tokenizer v1)."""
    if not text:
        return []
    tokens = [match.group(0) for match in TOKEN_RE.finditer(text.casefold())]
    return [token for token in tokens if len(token) >= 2]


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_RE.findall(text or "")]
    return [p for p in parts if p]


def _mtld_pass(tokens: list[str], *, threshold: float = MTLD_FACTOR_THRESHOLD) -> float:
    if not tokens:
        return 0.0
    factors: list[float] = []
    types: set[str] = set()
    count = 0
    for token in tokens:
        count += 1
        types.add(token)
        ttr = len(types) / count
        if ttr <= threshold:
            factors.append(float(count))
            types = set()
            count = 0
    if count > 0:
        ttr = len(types) / count
        if ttr >= 1.0:
            partial = float(count)
        else:
            partial = count / (1.0 - ttr)
        factors.append(float(partial))
    if not factors:
        return 0.0
    return sum(factors) / len(factors)


def compute_mtld(tokens: list[str]) -> float | None:
    if len(tokens) < MIN_MTLD_TOKENS:
        return None
    forward = _mtld_pass(tokens)
    reverse = _mtld_pass(list(reversed(tokens)))
    value = (forward + reverse) / 2.0
    if not math.isfinite(value):
        return None
    return float(value)


def compute_lexical_diversity(text: str) -> dict[str, Any]:
    tokens = tokenize(text)
    token_count = len(tokens)
    if token_count == 0:
        return {
            "token_count": 0,
            "type_count": 0,
            "hapax_count": 0,
            "ttr": None,
            "mtld": None,
            "hapax_rate": None,
        }
    freq: dict[str, int] = {}
    for token in tokens:
        freq[token] = freq.get(token, 0) + 1
    type_count = len(freq)
    hapax_count = sum(1 for count in freq.values() if count == 1)
    ttr = type_count / token_count
    hapax_rate = hapax_count / type_count if type_count else None
    return {
        "token_count": token_count,
        "type_count": type_count,
        "hapax_count": hapax_count,
        "ttr": float(ttr),
        "mtld": compute_mtld(tokens),
        "hapax_rate": float(hapax_rate) if hapax_rate is not None else None,
    }


def _syllable_count(word: str) -> int:
    w = word.casefold()
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in w:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if w.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def _finite(value: float) -> float | None:
    if not math.isfinite(value):
        return None
    return float(value)


def compute_readability(text: str) -> dict[str, Any]:
    sentences = split_sentences(text)
    words = tokenize(text)
    n_sent = len(sentences)
    n_words = len(words)
    if n_sent < 1 or n_words < 3:
        return {
            "flesch_reading_ease": None,
            "gunning_fog": None,
            "ari": None,
            "avg_sentence_length": None,
            "lexical_density": None,
            "word_count": n_words,
            "sentence_count": n_sent,
            "insufficient": True,
        }
    n_syll = sum(_syllable_count(w) for w in words)
    asl = n_words / n_sent
    asw = n_syll / n_words
    fre = 206.835 - 1.015 * asl - 84.6 * asw
    chars = sum(len(w) for w in words)
    ari = 4.71 * (chars / n_words) + 0.5 * asl - 21.43
    complex_words = sum(1 for w in words if _syllable_count(w) >= 3)
    fog = 0.4 * (asl + 100.0 * (complex_words / n_words))
    lexical_density = len(set(words)) / n_words
    return {
        "flesch_reading_ease": _finite(fre),
        "gunning_fog": _finite(fog),
        "ari": _finite(ari),
        "avg_sentence_length": _finite(asl),
        "lexical_density": _finite(lexical_density),
        "word_count": n_words,
        "sentence_count": n_sent,
        "insufficient": False,
    }


def compute_style_metrics(text: str) -> dict[str, Any]:
    """Readability + lexical diversity for one manuscript."""
    return {
        "readability": compute_readability(text),
        "lexical_diversity": compute_lexical_diversity(text),
    }


def long_sentences(text: str, *, min_words: int = LONG_SENTENCE_WORDS) -> list[tuple[int, int, str]]:
    """Return (1-based index, word count, quote) for extreme sentences."""
    out: list[tuple[int, int, str]] = []
    for idx, sent in enumerate(split_sentences(text), start=1):
        n = len(tokenize(sent))
        if n >= min_words:
            quote = sent.replace("\n", " ").strip()[:200]
            out.append((idx, n, quote))
        if len(out) >= MAX_LONG_SENTENCES:
            break
    return out
