"""Grounded LLM fill for missing section fields."""

from __future__ import annotations

import json
import re
from typing import Any

from ..config import Config
from ..llm import ChatRequest, LLMClient, ctx_tokens_for, get_client
from ..rag.questions import _qid, extract_llm

_MAX_LLM_CHARS = 12_000

_LLM_SYSTEM = """\
Extract structured sections from a research paper excerpt. Use ONLY the excerpt.
Return a JSON object with optional keys: abstract, methodology, conclusion, \
research_questions.
- abstract, methodology, conclusion: strings (section text), each grounded in the excerpt.
- research_questions: array of question strings grounded in the excerpt.
Omit keys you cannot ground. No markdown fences. No commentary."""


def _grounded_text(value: str, excerpt_norm: str) -> bool:
    cleaned = re.sub(r"\s+", " ", value.strip())
    if len(cleaned) < 40:
        return False
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", cleaned.lower()) if w]
    if not words:
        return False
    hits = sum(1 for w in words if w in excerpt_norm)
    return hits >= max(3, len(words) // 4)


def build_excerpt(
    pages: list[str],
    record_abstract: str,
    section_bodies: list[str],
    *,
    max_chars: int = _MAX_LLM_CHARS,
) -> str:
    parts: list[str] = []
    if record_abstract.strip():
        parts.append(record_abstract.strip())
    for body in section_bodies:
        b = body.strip()
        if b and b not in parts:
            parts.append(b)
    parts.append("\n".join(pages[:6]))
    excerpt = "\n\n".join(p for p in parts if p).strip()
    return excerpt[:max_chars]


def fill_missing_llm(
    cfg: Config,
    *,
    pages: list[str],
    record_abstract: str,
    section_bodies: list[str],
    missing: list[str],
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """Return serialized field values for keys still missing after rules."""
    if not missing:
        return {}
    excerpt = build_excerpt(pages, record_abstract, section_bodies)
    if len(excerpt) < 80:
        return {}
    client = client or get_client(cfg)
    model = (cfg.rag_model or cfg.llm_model).strip()
    request = ChatRequest(
        model=model,
        messages=[
            {"role": "system", "content": _LLM_SYSTEM},
            {
                "role": "user",
                "content": f"Missing fields: {', '.join(missing)}\n\nExcerpt:\n\n{excerpt}",
            },
        ],
        timeout_seconds=cfg.llm_timeout_s,
        num_ctx=ctx_tokens_for(excerpt, max_num_ctx=cfg.llm_max_num_ctx),
    )
    text = "".join(client.chat_stream(request)).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return {}
    norm = re.sub(r"\s+", " ", excerpt.lower())
    out: dict[str, Any] = {}
    for key in ("abstract", "methodology", "conclusion"):
        if key not in missing:
            continue
        raw = data.get(key)
        if not isinstance(raw, str):
            continue
        cleaned = re.sub(r"\s+", " ", raw.strip())
        if not _grounded_text(cleaned, norm):
            continue
        out[key] = {
            "text": cleaned,
            "provenance": "llm",
            "heading": None,
            "pages": "",
        }
    if "research_questions" in missing:
        rqs: list[dict[str, Any]] = []
        raw_list = data.get("research_questions")
        if isinstance(raw_list, list):
            for item in raw_list:
                if not isinstance(item, str):
                    continue
                cleaned = re.sub(r"\s+", " ", item.strip())
                if len(cleaned) < 12:
                    continue
                if not cleaned.endswith("?"):
                    cleaned = cleaned.rstrip(".!;:") + "?"
                words = [w for w in re.findall(r"[a-zA-Z]{4,}", cleaned.lower()) if w]
                if not words:
                    continue
                hits = sum(1 for w in words if w in norm)
                if hits < max(2, len(words) // 3):
                    continue
                rqs.append(
                    {
                        "id": _qid(cleaned),
                        "text": cleaned,
                        "provenance": "llm",
                        "pages": "",
                    }
                )
        if not rqs:
            for q in extract_llm(cfg, pages, record_abstract, client=client):
                rqs.append(
                    {
                        "id": q.id,
                        "text": q.text,
                        "provenance": q.provenance,
                        "pages": q.pages,
                    }
                )
        if rqs:
            out["research_questions"] = rqs
    return out
