"""Per-area JSON rewrite calls. Suggested edits only. Grounded in extract + findings."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import Config
from .critique_llm import is_scoreish, parse_llm_json
from .grounding import budget_slice
from .rewrite_align import Alignment, unique_span
from .rewrite_areas import RewriteArea
from .rewrite_grounding import (
    apply_freeze,
    cites_ok,
    freeze_preserved,
    freeze_tokens,
    numbers_ok,
    thaw,
)
from .rewrite_plan import RewriteEdit

_LEAK = re.compile(
    r"\b(paperful|critique pack|the reviewer|this pack|llm reviewer)\b", re.I
)
_PROMISE = re.compile(
    r"\b(future work|see (the )?appendix|we will (add|run|include)|placeholder)\b",
    re.I,
)

_DEFAULT_PROMPT = """You revise locatable spans in a manuscript using ONLY PAPER_CONTENT, SELECTED_CONTENT, and the finding.
Return JSON:
{
  "edits": [
    {
      "finding_id": "id",
      "kind": "replace|insert|comment",
      "quote": "exact substring of SELECTED_CONTENT or PAPER_CONTENT",
      "replacement": "new text for replace",
      "body": "Word comment text for comment",
      "needs_author": false
    }
  ]
}
Rules:
- At most one edit per finding_id unless the finding needs two non-overlapping spans.
- quote MUST be a substring of PAPER_CONTENT.
- Do not paraphrase the finding into the prose. Integrate in the paper's voice.
- Do not add numbers, experiments, URLs, or citation keys that are not already in PAPER_CONTENT or the finding.
- Do not promise future work or point at an appendix you did not edit.
- Do not mention Paperful, the critique pack, or "the reviewer" in replacement text.
- Do not hide limitations. Do not invent results.
- Prefer kind=comment when the finding is a question, indirect criticism, or needs the author's judgement.
- needs_author true when you cannot ground a body edit.
- No score, grade, or accept/reject.
"""


def load_area_prompt(area: RewriteArea) -> str | None:
    raw = (area.prompt or "default").strip() or "default"
    if raw != "default":
        path = Path(raw)
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None
    name = f"rewrite-{area.id}.md"
    for root in (Path.cwd(), Path(__file__).resolve().parents[1]):
        candidate = root / "prompts" / name
        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if text:
                return text
    return _DEFAULT_PROMPT


def edit_is_grounded(
    *,
    kind: str,
    quote: str,
    replacement: str,
    body: str,
    hay: str,
) -> str | None:
    """Return a skip reason when the proposed edit is not allowed."""
    payload = f"{replacement} {body}"
    if is_scoreish(payload):
        return "not_actionable"
    if _LEAK.search(replacement or "") or _LEAK.search(body or ""):
        return "leakage"
    if kind in {"replace", "insert", "delete"}:
        if kind == "replace" and _PROMISE.search(replacement or ""):
            return "no_evidence"
        if kind in {"replace", "delete", "insert"}:
            if not quote or unique_span(hay, quote) is None:
                return "no_unique_span"
        check = replacement if kind != "delete" else replacement
        if not numbers_ok(check, hay) or not cites_ok(check, hay):
            return "no_evidence"
    if kind == "comment" and not (body or "").strip():
        return "not_actionable"
    return None


def proposed_from_area(
    cfg: Config,
    *,
    area: RewriteArea,
    findings: list[dict[str, Any]],
    alignments: dict[str, Alignment],
    excerpt: str,
    client: Any,
    timeout_s: float,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[RewriteEdit], list[dict[str, str]], str]:
    """One JSON call for an area. Returns edits, skips, model id."""
    say = on_status or (lambda _msg: None)
    model = (area.model or cfg.llm_model or "").strip()
    prompt = load_area_prompt(area)
    if prompt is None:
        return (
            [],
            [
                {"finding_id": str(f.get("id") or ""), "reason": "needs_author"}
                for f in findings
            ],
            model,
        )
    if client is None or not model:
        return (
            [],
            [
                {"finding_id": str(f.get("id") or ""), "reason": "needs_author"}
                for f in findings
            ],
            model,
        )

    frozen_excerpt, mapping = freeze_tokens(excerpt)
    payload = []
    selected_frozen: dict[str, str] = {}
    for row in findings:
        fid = str(row.get("id") or "")
        aln = alignments.get(fid)
        raw_sel = str(aln.quote if aln else row.get("quote") or "")
        frozen_sel = apply_freeze(raw_sel, mapping)
        selected_frozen[fid] = frozen_sel
        payload.append(
            {
                "finding_id": fid,
                "code": row.get("code"),
                "detail": row.get("detail"),
                "selected_content": frozen_sel,
                "loc": (aln.loc if aln else row.get("loc") or ""),
            }
        )
    user = (
        f"<PAPER_CONTENT>\n{frozen_excerpt}\n</PAPER_CONTENT>\n"
        f"<FINDINGS>\n{json.dumps(payload, ensure_ascii=False)}\n</FINDINGS>\n"
        "For each finding, treat selected_content as SELECTED_CONTENT and "
        "detail as QUESTION. Copy every «PF…» placeholder unchanged."
    )
    hay = excerpt
    from .llm.client import ChatRequest, chat, ctx_tokens_for

    timeout = timeout_s or float(cfg.llm_timeout_s or 120)
    say(f"Rewrite {area.id} ({model})…")
    req = ChatRequest(
        model=model,
        messages=(
            {"role": "system", "content": prompt},
            {"role": "user", "content": user},
        ),
        timeout_seconds=timeout,
        temperature=0.2,
        num_ctx=ctx_tokens_for(
            prompt + user, max_num_ctx=int(cfg.llm_max_num_ctx or 32768)
        ),
    )
    try:
        raw = chat(client, req)
    except Exception:
        return (
            [],
            [
                {"finding_id": str(f.get("id") or ""), "reason": "needs_author"}
                for f in findings
            ],
            model,
        )
    data = parse_llm_json(raw) or {}
    edits: list[RewriteEdit] = []
    skips: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in data.get("edits") or []:
        if not isinstance(row, dict):
            continue
        fid = str(row.get("finding_id") or "").strip()
        kind = str(row.get("kind") or "replace").strip().lower()
        if kind not in {"replace", "insert", "delete", "comment"}:
            kind = "replace"
        quote = str(row.get("quote") or "").strip()
        replacement = str(row.get("replacement") or "").strip()
        body = str(row.get("body") or "").strip()
        if row.get("needs_author"):
            skips.append({"finding_id": fid, "reason": "needs_author"})
            seen.add(fid)
            continue
        sel_f = selected_frozen.get(fid, "")
        reply_for_freeze = replacement if kind == "replace" else f"{quote} {replacement}"
        if kind in {"replace", "insert", "delete"} and sel_f:
            if not freeze_preserved(
                selected_frozen=sel_f, reply=reply_for_freeze, mapping=mapping
            ):
                skips.append({"finding_id": fid, "reason": "no_evidence"})
                seen.add(fid)
                continue
        quote = thaw(quote, mapping)
        replacement = thaw(replacement, mapping)
        body = thaw(body, mapping)
        reason = edit_is_grounded(
            kind=kind, quote=quote, replacement=replacement, body=body, hay=hay
        )
        if reason:
            skips.append({"finding_id": fid, "reason": reason})
            seen.add(fid)
            continue
        aln = alignments.get(fid)
        span = unique_span(excerpt, quote)
        if span is not None:
            start, end = span
        else:
            start = aln.start if aln else -1
            end = aln.end if aln else -1
        para = aln.paragraph if aln else quote
        target = replacement if kind == "replace" else para
        if kind == "insert":
            target = (para + " " + replacement).strip() if replacement else para
        edits.append(
            RewriteEdit(
                kind=kind,
                finding_ids=[fid] if fid else [],
                area=area.id,
                loc=(aln.loc if aln else ""),
                quote=quote,
                replacement=replacement,
                body=body,
                source_paragraph=para,
                target_paragraph=target,
                start=start,
                end=end,
            )
        )
        seen.add(fid)
    for row in findings:
        fid = str(row.get("id") or "")
        if fid and fid not in seen:
            skips.append({"finding_id": fid, "reason": "needs_author"})
    _ = sha256((prompt + user).encode("utf-8")).hexdigest()[:12]
    return edits, skips, model


def budget_excerpt(cfg: Config, text: str) -> str:
    return budget_slice(text, int(getattr(cfg, "critique_max_context_chars", 24000)))
