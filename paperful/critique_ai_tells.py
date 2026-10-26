"""Heuristic LLM-style prose signals for critique (not proof of AI authorship).

Zero-dependency stylometry inspired by ADAFAI (MIT): burstiness, stock phrases,
discourse scaffolds, unicode forensics. Abstains below 150 words.
"""

from __future__ import annotations

import math
import re
import statistics
from typing import Any

from .critique_direct_quotes import elide_direct_quotes
from .critique_metrics import split_sentences, tokenize

MIN_AI_TELL_WORDS = 150
MAX_PHRASE_FINDINGS = 5

# Distinctive stock phrases (high precision). Academic connectors are counted
# only in the density total, not as individual findings.
_DISTINCTIVE_PHRASES = (
    "delve into",
    "it's important to note",
    "it is important to note",
    "it is worth noting",
    "in the realm of",
    "a testament to",
    "plays a crucial role",
    "shed light on",
    "at its core",
    "pave the way",
    "ever-evolving",
    "landscape of",
    "holistic approach",
    "as an ai",
    "tapestry of",
    "underscores the",
    "underscore the",
)
_WORD_TELLS = (
    "delve",
    "tapestry",
    "multifaceted",
    "pivotal",
)
_CONNECTORS = (
    "moreover",
    "furthermore",
    "additionally",
    "notably",
)
_ZERO_WIDTH = (
    "\u200b",
    "\u200c",
    "\u200d",
    "\ufeff",
    "\u2060",
    "\u180e",
)
_NOT_MERELY = re.compile(
    r"not merely\b.{0,80}\bbut rather\b",
    re.IGNORECASE | re.DOTALL,
)
_RULE_OF_THREE = re.compile(
    r"\b[\w'-]+,\s+[\w'-]+,\s+and\s+[\w'-]+\b",
    re.IGNORECASE,
)
_LATIN = re.compile(r"[A-Za-z]")
_CYRILLIC = re.compile(r"[\u0400-\u04FF]")


def _phrase_count(lower: str, phrase: str) -> int:
    if " " in phrase:
        return lower.count(phrase)
    return len(re.findall(rf"\b{re.escape(phrase)}\b", lower))


def _burstiness_cv(sentences: list[str]) -> float | None:
    lengths = [len(tokenize(s)) for s in sentences]
    lengths = [n for n in lengths if n > 0]
    if len(lengths) < 2:
        return None
    mean_len = statistics.mean(lengths)
    if mean_len <= 0:
        return None
    std_len = statistics.pstdev(lengths)
    cv = std_len / mean_len
    if not math.isfinite(cv):
        return None
    return float(cv)


def _paragraph_cv(paragraphs: list[str]) -> float | None:
    lengths = [len(tokenize(p)) for p in paragraphs if p.strip()]
    lengths = [n for n in lengths if n > 0]
    if len(lengths) < 4:
        return None
    mean_len = statistics.mean(lengths)
    if mean_len <= 0:
        return None
    cv = statistics.pstdev(lengths) / mean_len
    if not math.isfinite(cv):
        return None
    return float(cv)


def _unicode_flags(text: str) -> list[str]:
    flags: list[str] = []
    zw = sum(text.count(ch) for ch in _ZERO_WIDTH)
    if zw:
        flags.append(f"zero_width:{zw}")
    mixed = 0
    for token in re.findall(r"\S+", text):
        if _LATIN.search(token) and _CYRILLIC.search(token):
            mixed += 1
    if mixed:
        flags.append(f"mixed_script_tokens:{mixed}")
    return flags


def _discourse_flags(text: str, paragraphs: list[str]) -> list[str]:
    flags: list[str] = []
    if _NOT_MERELY.search(text):
        flags.append("not_merely_but_rather")
    triples = _RULE_OF_THREE.findall(text)
    if len(triples) >= 4:
        flags.append(f"rule_of_three:{len(triples)}")
    para_cv = _paragraph_cv(paragraphs)
    if para_cv is not None and para_cv < 0.12:
        flags.append(f"paragraph_uniformity_cv:{para_cv:.3f}")
    punch = 0
    for para in paragraphs:
        sents = split_sentences(para)
        if len(sents) < 2:
            continue
        last = len(tokenize(sents[-1]))
        body = [len(tokenize(s)) for s in sents[:-1]]
        if last <= 8 and body and statistics.mean(body) >= 16:
            punch += 1
    if punch >= 3:
        flags.append(f"paragraph_punchlines:{punch}")
    return flags


def compute_ai_tells(text: str, paragraphs: list[str] | None = None) -> dict[str, Any]:
    """Return metrics for the pack ``ai_tells`` object (always safe JSON)."""
    prose = elide_direct_quotes(text)
    paras = paragraphs if paragraphs is not None else [p for p in prose.split("\n\n") if p.strip()]
    tokens = tokenize(prose)
    word_count = len(tokens)
    if word_count < MIN_AI_TELL_WORDS:
        return {
            "word_count": word_count,
            "burstiness_cv": None,
            "tell_phrase_hits": [],
            "tell_phrase_total": 0,
            "unicode_flags": [],
            "discourse": [],
            "abstain": True,
        }
    lower = prose.casefold()
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for phrase in _DISTINCTIVE_PHRASES:
        n = _phrase_count(lower, phrase)
        if n:
            hits.append({"phrase": phrase, "count": n, "kind": "distinctive"})
            seen.add(phrase)
    for word in _WORD_TELLS:
        if word in seen or any(word in h["phrase"] for h in hits):
            continue
        n = _phrase_count(lower, word)
        if n:
            hits.append({"phrase": word, "count": n, "kind": "distinctive"})
    connector_total = sum(_phrase_count(lower, c) for c in _CONNECTORS)
    tell_total = sum(h["count"] for h in hits) + connector_total
    sentences = split_sentences(prose)
    return {
        "word_count": word_count,
        "burstiness_cv": _burstiness_cv(sentences),
        "tell_phrase_hits": hits,
        "tell_phrase_total": tell_total,
        "connector_hits": connector_total,
        "unicode_flags": _unicode_flags(prose),
        "discourse": _discourse_flags(prose, paras),
        "abstain": False,
    }
