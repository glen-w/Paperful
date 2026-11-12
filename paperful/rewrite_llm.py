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

_DEFAULT_PROMPT = """You rewrite one manuscript paragraph using ONLY PAPER_CONTENT and FINDINGS.
Return JSON:
{
  "edits": [
    {
      "finding_id": "id",
      "kind": "replace|insert|comment",
      "paragraph": "the full rewritten PAPER_CONTENT paragraph",
      "quote": "optional; Paperful diffs paragraph if omitted",
      "replacement": "optional span replacement",
      "body": "Word comment text for comment",
      "needs_author": false
    }
  ]
}
Rules:
- Return ONE replace edit for the whole paragraph covering every finding you can ground.
- paragraph MUST be the complete paragraph. Unflagged sentences stay word-for-word.
- Do not paraphrase findings into the prose. Keep the paper's voice.
- Do not add numbers, experiments, URLs, or citation keys that are not already in PAPER_CONTENT or the finding.
- Copy every «PF…» placeholder unchanged.
- Do not promise future work or point at an appendix you did not edit.
- Do not mention Paperful, the critique pack, or "the reviewer" in replacement text.
- Do not hide limitations. Do not invent results.
- Prefer kind=comment when the finding is a question, indirect criticism, or needs the author's judgement.
- needs_author true when you cannot ground a body edit.
- No score, grade, or accept/reject.
"""


def paragraph_span(source: str, target: str) -> tuple[str, str, int, int] | None:
    """Longest common prefix/suffix diff. Offsets are into ``source``."""
    src = source or ""
    tgt = target or ""
    if src == tgt or not src or not tgt:
        return None
    i = 0
    limit = min(len(src), len(tgt))
    while i < limit and src[i] == tgt[i]:
        i += 1
    j = 0
    while j < limit - i and src[-(j + 1)] == tgt[-(j + 1)]:
        j += 1
    end = len(src) - j
    quote = src[i:end]
    replacement = tgt[i : len(tgt) - j]
    if not quote:
        return None
    return quote, replacement, i, end


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
) -> tuple[list[RewriteEdit], list[dict[str, str]], str, dict[str, Any]]:
    """One JSON call for an area. Returns edits, skips, model id, call meta."""
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
            {},
        )
    if client is None or not model:
        return (
            [],
            [
                {"finding_id": str(f.get("id") or ""), "reason": "needs_author"}
                for f in findings
            ],
            model,
            {},
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
    from . import __version__ as PAPERFUL_VERSION
    from .llm.client import ChatRequest, chat, ctx_tokens_for, prompt_exceeds_ctx

    timeout = timeout_s or float(cfg.llm_timeout_s or 120)
    max_ctx = int(cfg.llm_max_num_ctx or 32768)
    blob = prompt + user
    prompt_sha = sha256(blob.encode("utf-8")).hexdigest()[:12]
    if prompt_exceeds_ctx(blob, max_num_ctx=max_ctx):
        return (
            [],
            [
                {
                    "finding_id": str(f.get("id") or ""),
                    "reason": "context_overflow",
                }
                for f in findings
            ],
            model,
            {
                "temperature": 0.0,
                "seed": 0,
                "num_ctx": max_ctx,
                "prompt_sha": prompt_sha,
                "paperful": PAPERFUL_VERSION,
            },
        )
    num_ctx = ctx_tokens_for(blob, max_num_ctx=max_ctx)
    say(f"Rewrite {area.id} ({model})…")
    req = ChatRequest(
        model=model,
        messages=(
            {"role": "system", "content": prompt},
            {"role": "user", "content": user},
        ),
        timeout_seconds=timeout,
        temperature=0.0,
        seed=0,
        num_ctx=num_ctx,
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
            {},
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
        paragraph = str(row.get("paragraph") or "").strip()
        if row.get("needs_author"):
            skips.append({"finding_id": fid, "reason": "needs_author"})
            seen.add(fid)
            continue
        aln = alignments.get(fid)
        source_para = (aln.paragraph if aln else "") or excerpt
        if paragraph:
            if not freeze_preserved(
                selected_frozen=frozen_excerpt,
                reply=paragraph,
                mapping=mapping,
            ):
                skips.append({"finding_id": fid, "reason": "no_evidence"})
                seen.add(fid)
                continue
            paragraph = thaw(paragraph, mapping)
            diff = paragraph_span(source_para, paragraph)
            if diff is None:
                skips.append({"finding_id": fid, "reason": "needs_author"})
                seen.add(fid)
                continue
            quote, replacement, _ls, _le = diff
            kind = "replace"
        sel_f = selected_frozen.get(fid, "")
        reply_for_freeze = (
            paragraph
            if paragraph
            else (replacement if kind == "replace" else f"{quote} {replacement}")
        )
        if kind in {"replace", "insert", "delete"} and sel_f and not paragraph:
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
        span = unique_span(excerpt, quote)
        if span is not None:
            start, end = span
        else:
            start = aln.start if aln else -1
            end = aln.end if aln else -1
        para = source_para or quote
        target = paragraph if paragraph else (
            replacement if kind == "replace" else para
        )
        if kind == "insert" and not paragraph:
            target = (para + " " + replacement).strip() if replacement else para
        fids = [fid] if fid else []
        extra_ids = row.get("finding_ids")
        if isinstance(extra_ids, list):
            fids = [str(x) for x in extra_ids if str(x).strip()]
        edits.append(
            RewriteEdit(
                kind=kind,
                finding_ids=fids,
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
        for extra in fids:
            seen.add(extra)
    for row in findings:
        fid = str(row.get("id") or "")
        if fid and fid not in seen:
            skips.append({"finding_id": fid, "reason": "needs_author"})
    meta = {
        "temperature": 0.0,
        "seed": 0,
        "num_ctx": num_ctx,
        "prompt_sha": prompt_sha,
        "model": model,
        "paperful": PAPERFUL_VERSION,
    }
    return edits, skips, model, meta


def budget_excerpt(cfg: Config, text: str) -> str:
    return budget_slice(text, int(getattr(cfg, "critique_max_context_chars", 24000)))
