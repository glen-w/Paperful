"""Contextual summaries and relevance scores for advanced Ask."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..config import Config
from ..llm import CompletionRequest, LLMClient, LLMClientError, ctx_tokens_for
from ..store import load_json, write_json
from .retrieve import Hit

EVIDENCE_PROMPT_VERSION = 1

_SUMMARY_PROMPT = """\
Summarize the excerpt below to help answer a question.
Do not directly answer the question. Stay detailed; report specific numbers,
equations, or short quotes (marked with quotation marks).
Reply with JSON only:
{{"summary": "...", "relevance_score": 0}}
summary is relevant information from the excerpt ({summary_length}).
relevance_score is an integer 0-10 for how well the excerpt helps the question.
If the excerpt is irrelevant, set summary to an empty string and relevance_score to 0.

Excerpt from {citation}

---

{text}

---

Question: {question}
"""

_VARIANT_PROMPT = """\
Rewrite the question into alternative search queries for a scientific PDF index.
Return JSON only: {{"queries": ["...", "..."]}}
Give {n} distinct phrasings. Keep them short. Do not answer the question.

Question: {question}
"""


def evidence_dir(cfg: Config) -> Path:
    return cfg.rag_dir / "evidence"


def summary_model(cfg: Config) -> str:
    return (cfg.rag_summary_model or cfg.rag_model or cfg.llm_model).strip()


def _chunk_id(hit: Hit) -> str:
    return f"{hit.item_key}:{hit.chunk_index}"


def _cache_key(hit: Hit, question: str, model: str) -> str:
    payload = "|".join(
        [
            _chunk_id(hit),
            hashlib.sha256(question.strip().encode("utf-8")).hexdigest(),
            model,
            str(EVIDENCE_PROMPT_VERSION),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(cfg: Config, key: str) -> Path:
    return evidence_dir(cfg) / f"{key}.json"


def load_cached(cfg: Config, key: str) -> dict[str, Any] | None:
    return load_json(_cache_path(cfg, key))


def save_cached(cfg: Config, key: str, payload: dict[str, Any]) -> None:
    write_json(_cache_path(cfg, key), payload)


def parse_score(value: Any) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(10, score))


def _one(
    cfg: Config,
    hit: Hit,
    question: str,
    client: LLMClient,
    model: str,
) -> Hit:
    key = _cache_key(hit, question, model)
    cached = load_cached(cfg, key)
    if cached is not None:
        summary = str(cached.get("summary") or "")
        score = parse_score(cached.get("relevance_score"))
        return replace(hit, summary=summary, relevance_score=score)

    citation = hit.title or hit.item_key
    prompt = _SUMMARY_PROMPT.format(
        summary_length=cfg.rag_summary_length or "about 80 words",
        citation=citation.replace("{", "{{").replace("}", "}}"),
        text=hit.text.replace("{", "{{").replace("}", "}}"),
        question=question.strip().replace("{", "{{").replace("}", "}}"),
    )
    failed = False
    try:
        data = client.complete_json(
            CompletionRequest(
                model=model,
                prompt=prompt,
                timeout_seconds=min(60, cfg.llm_timeout_s),
                num_ctx=ctx_tokens_for(prompt, max_num_ctx=cfg.llm_max_num_ctx),
            )
        )
    except (LLMClientError, ValueError, TypeError):
        data = {}
        failed = True
    if not isinstance(data, dict):
        data = {}
        failed = True
    summary = str(data.get("summary") or "").strip()
    score = parse_score(data.get("relevance_score"))
    if not summary and score > 0:
        score = 0
    if failed and cfg.rag_evidence_fallback == "raw":
        summary = hit.text
        score = max(score, 1)
    save_cached(
        cfg,
        key,
        {"summary": summary, "relevance_score": score, "chunk_id": _chunk_id(hit)},
    )
    return replace(hit, summary=summary, relevance_score=score)


def summarize_hits(
    cfg: Config,
    hits: list[Hit],
    question: str,
    client: LLMClient,
) -> list[Hit]:
    """Score each hit for this question. Cache hits skip the model."""
    if not hits:
        return []
    model = summary_model(cfg)
    workers = max(1, min(cfg.rag_summary_concurrency, len(hits)))
    if workers == 1:
        return [_one(cfg, hit, question, client, model) for hit in hits]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(
            pool.map(lambda hit: _one(cfg, hit, question, client, model), hits)
        )


def filter_evidence(cfg: Config, hits: list[Hit]) -> list[Hit]:
    """Drop score 0 / below cutoff; cap papers at ``answer_max_sources``."""
    cutoff = cfg.rag_relevance_cutoff
    kept: list[Hit] = []
    papers: dict[str, int] = {}
    for hit in hits:
        score = hit.relevance_score
        if score is None:
            if cfg.rag_evidence_fallback == "drop":
                continue
            score = 1
        if score < 1 or score < cutoff:
            continue
        if papers.get(hit.item_key, 0) >= cfg.rag_max_chunks_per_item:
            continue
        if hit.item_key not in papers and len(papers) >= cfg.rag_answer_max_sources:
            continue
        papers[hit.item_key] = papers.get(hit.item_key, 0) + 1
        kept.append(hit)
    return kept


def expand_queries(
    cfg: Config,
    question: str,
    client: LLMClient,
    n: int,
) -> list[str]:
    """The original question plus up to ``n-1`` alternatives. Failure keeps one."""
    q = question.strip()
    if n <= 1 or not q:
        return [q] if q else []
    prompt = _VARIANT_PROMPT.format(n=max(1, n - 1), question=q)
    try:
        data = client.complete_json(
            CompletionRequest(
                model=(cfg.rag_model or cfg.llm_model).strip(),
                prompt=prompt,
                timeout_seconds=min(30, cfg.llm_timeout_s),
                num_ctx=ctx_tokens_for(prompt, max_num_ctx=cfg.llm_max_num_ctx),
            )
        )
    except (LLMClientError, ValueError, TypeError, json.JSONDecodeError):
        return [q]
    if not isinstance(data, dict):
        return [q]
    out = [q]
    for item in data.get("queries") or []:
        line = str(item).strip()
        if line and line not in out:
            out.append(line)
        if len(out) >= n:
            break
    return out
