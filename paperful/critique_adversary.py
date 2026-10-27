"""Structured validity red-team suggested lane. No scores.

One JSON turn over the excerpt and checked findings. Comments are grounded
the same way as reviewers. Suggested lane only.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from hashlib import sha256
from typing import Any

from .config import Config
from .critique import Finding, make_finding
from .critique_extract import ExtractedDoc
from .critique_llm import findings_from_comments, grounded, parse_llm_json
from .grounding import budget_slice
from .zot import Item

_SYSTEM = """You are a structured validity red-team for a manuscript.
Use ONLY the title, excerpt, and checked findings. Do not invent citations, data, or methods.
Return JSON only:
{
  "summary": "one paragraph of the core claim and what would have to be true for it to hold",
  "comments": [
    {"code": "adversary_alt|adversary_validity|adversary_rdf|adversary_falsify|adversary_negative", "quote": "span from the excerpt", "detail": "attack on that span"}
  ]
}
Cover, as far as the excerpt allows:
- adversary_alt: alternative explanations
- adversary_validity: selection, construct, or external validity
- adversary_rdf: researcher degrees of freedom / unstated analytic choices
- adversary_falsify: what would falsify the core claim
- adversary_negative: missing negative or comparison cases
Rules:
- Quotes MUST be substrings of the excerpt.
- At most 8 comments. Prefer fewer sharp attacks over a laundry list.
- No score, grade, or accept/reject.
- Do not claim plagiarism or misconduct.
- Label opinion as opinion when you go beyond the checkers.
"""


def suggested_from_adversary(
    cfg: Config,
    doc: ExtractedDoc,
    findings: list[Finding],
    *,
    item: Item | None,
    client: Any,
    hay: str,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[Finding], dict[str, Any]]:
    """One JSON validity-attack turn. Suggested lane only."""
    say = on_status or (lambda _msg: None)
    model = cfg.llm_model
    excerpt = budget_slice(doc.text, cfg.critique_max_context_chars)
    cap = max(1, int(getattr(cfg, "critique_adversary_max_comments", 12) or 12))
    timeout_s = float(cfg.llm_timeout_s or 120)
    meta: dict[str, Any] = {
        "id": "adversary",
        "model": model,
        "calls": 0,
    }
    if not excerpt.strip():
        meta["skipped"] = "empty_extract"
        meta["reviewers"] = [
            {"id": "adversary", "model": model, "skipped": "empty_extract"}
        ]
        return [], meta

    title = (item.title if item is not None else "") or ""
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
    user = f"Title: {title}\n\nExcerpt:\n{excerpt}\n\nChecked findings:\n" + json.dumps(
        checked, ensure_ascii=False
    )
    prompt_sha = sha256((_SYSTEM + user[:2000]).encode("utf-8")).hexdigest()[:12]
    meta["prompt_sha"] = prompt_sha
    say("Adversary lane…")
    from .llm.client import ChatRequest, chat

    request = ChatRequest(
        model=model,
        messages=(
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ),
        timeout_seconds=timeout_s,
        temperature=0.2,
    )
    t0 = time.perf_counter()
    try:
        raw = chat(client, request)
    except Exception as exc:
        meta["skipped"] = "llm_error"
        meta["error"] = str(exc)
        meta["reviewers"] = [
            {
                "id": "adversary",
                "model": model,
                "prompt_sha": prompt_sha,
                "skipped": "llm_error",
                "error": str(exc),
            }
        ]
        return [
            make_finding(
                code="llm_failed",
                severity="info",
                lane="suggested",
                detail=f"Adversary lane failed: {exc}",
                source="llm",
                extra={"reviewer": "adversary"},
            )
        ], meta
    meta["calls"] = 1
    data = parse_llm_json(raw) or {}
    extra = findings_from_comments(
        data.get("comments"),
        hay=hay,
        reviewer_id="adversary",
        source="llm",
        limit=cap,
    )
    summary = str(data.get("summary") or "").strip()
    narrative = ""
    if summary and grounded(summary, hay):
        narrative = summary[:4000]
        extra.insert(
            0,
            make_finding(
                code="llm_summary",
                severity="info",
                lane="suggested",
                detail=summary[:500],
                quote=summary[:200],
                source="llm",
                extra={"reviewer": "adversary"},
            ),
        )
        extra = extra[:cap]
    dt = time.perf_counter() - t0
    bits = [f"{dt:.0f}s"]
    if extra:
        bits.append(f"{len(extra)} comment(s)")
    if narrative:
        bits.append("note")
    say(f"Adversary lane done ({', '.join(bits)})")
    reviewer_row: dict[str, Any] = {
        "id": "adversary",
        "model": model,
        "prompt_sha": prompt_sha,
    }
    if narrative:
        meta["narrative"] = narrative
        reviewer_row["narrative"] = narrative
    if not extra and not narrative:
        meta["skipped"] = "empty_reply"
        reviewer_row["skipped"] = "empty_reply"
    meta["reviewers"] = [reviewer_row]
    return extra, meta
