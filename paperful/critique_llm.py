"""Optional grounded LLM comments. Suggested lane only. No scores."""

from __future__ import annotations

import json
import re
from typing import Any

from .config import Config
from .critique import Finding, make_finding
from .critique_extract import ExtractedDoc
from .grounding import budget_slice
from .zot import Item

_SCOREISH = re.compile(
    r"\b(?:accept|reject|overall score|grade\s*[1-6]|score\s*[1-6]\s*/\s*6)\b",
    re.I,
)

_PROMPT = """You review a manuscript using ONLY the excerpt and the checked findings.
Return JSON:
{
  "summary": "one paragraph of claimed contributions that does not contradict the excerpt",
  "comments": [
    {"code": "existing_or_new_code", "quote": "short span from the excerpt", "detail": "comment", "unverified": false}
  ],
  "questions": ["actionable question for the authors", "..."]
}
Rules:
- At most 8 comments and 5 questions.
- Each comment quote MUST be a substring of the excerpt.
- Mark unverified true when you go beyond the excerpt or checked findings.
- Do not give an overall score, grade, or accept/reject.
- Do not claim plagiarism or misconduct.
"""


def _grounded(text: str, hay: str) -> bool:
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", (text or "").lower()) if w]
    if not words:
        return False
    hits = sum(1 for w in words if w in hay)
    return hits >= max(2, min(3, len(words) // 4)) if len(words) > 2 else hits >= 1


def suggested_from_llm(
    cfg: Config,
    doc: ExtractedDoc,
    findings: list[Finding],
    *,
    item: Item | None,
    client: Any | None,
    force: bool,
) -> tuple[list[Finding], dict[str, Any] | None]:
    if client is None:
        return [], None
    if not force:
        for f in findings:
            if f.code == "pdf_identity_mismatch":
                return [
                    make_finding(
                        code="llm_refused_identity",
                        severity="info",
                        lane="suggested",
                        detail="LLM lane skipped: pdf_identity_mismatch (pass --force to override).",
                        source="llm",
                    )
                ], None
    excerpt = budget_slice(doc.text, cfg.critique_max_context_chars)
    hay = excerpt.lower()
    checked = [
        {
            "code": f.code,
            "severity": f.severity,
            "loc": f.loc,
            "quote": f.quote,
            "detail": f.detail,
        }
        for f in findings
        if f.lane == "checked" and not f.dismissed
    ][:40]
    title = (item.title if item is not None else "") or ""
    user = (
        f"Title: {title}\n\nExcerpt:\n{excerpt}\n\nChecked findings:\n"
        + json.dumps(checked, ensure_ascii=False)
    )
    from .llm.client import ChatRequest, chat
    from hashlib import sha256

    prompt_sha = sha256((_PROMPT + user[:2000]).encode("utf-8")).hexdigest()[:12]
    request = ChatRequest(
        model=cfg.llm_model,
        messages=(
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": user},
        ),
        timeout_seconds=float(cfg.llm_timeout_s or 120),
        temperature=0.2,
    )
    try:
        raw = chat(client, request)
    except Exception as exc:
        return [
            make_finding(
                code="llm_failed",
                severity="info",
                lane="suggested",
                detail=f"LLM lane failed: {exc}",
                source="llm",
            )
        ], {"model": cfg.llm_model, "prompt_sha": prompt_sha, "error": str(exc)}
    data = _parse_json(raw)
    out: list[Finding] = []
    summary = str((data or {}).get("summary") or "").strip()
    if summary and _grounded(summary, hay):
        out.append(
            make_finding(
                code="llm_summary",
                severity="info",
                lane="suggested",
                detail=summary[:500],
                quote=summary[:200],
                source="llm",
            )
        )
    for row in (data or {}).get("comments") or []:
        if not isinstance(row, dict):
            continue
        quote = str(row.get("quote") or "").strip()
        detail = str(row.get("detail") or "").strip()
        if not detail:
            continue
        if _SCOREISH.search(detail):
            continue
        if quote and quote.lower() not in hay and not _grounded(quote, hay):
            continue
        if not _grounded(detail, hay) and not quote:
            continue
        unverified = bool(row.get("unverified")) or (quote.lower() not in hay if quote else True)
        code = str(row.get("code") or "llm_comment").strip() or "llm_comment"
        extra = {"unverified": True} if unverified else {}
        out.append(
            make_finding(
                code=code[:40],
                severity="info",
                lane="suggested",
                loc="",
                quote=quote,
                detail=detail[:500],
                source="llm",
                extra=extra,
            )
        )
    for q in (data or {}).get("questions") or []:
        text = str(q).strip()
        if not text:
            continue
        out.append(
            make_finding(
                code="author_question",
                severity="info",
                lane="suggested",
                detail=text[:400],
                source="llm",
            )
        )
        if sum(1 for f in out if f.code == "author_question") >= 5:
            break
    meta = {
        "model": cfg.llm_model,
        "prompt_sha": prompt_sha,
        "provider": getattr(client, "provider", ""),
    }
    return out[:16], meta


def _parse_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
