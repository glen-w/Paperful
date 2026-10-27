"""Optional grounded LLM comments. Suggested lane only. No scores."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import Config, CritiqueReviewer, critique_reviewers_for
from .critique import Finding, make_finding
from .critique_direct_quotes import snippet_in_direct_quote
from .critique_extract import ExtractedDoc
from .grounding import budget_slice
from .zot import Item

SCOREISH = re.compile(
    r"\b(?:accept|reject|overall score|grade\s*[1-6]|score\s*[1-6]\s*/\s*6)\b",
    re.I,
)
_SCOREISH = SCOREISH
_FENCE = re.compile(r"^```[a-zA-Z]*\s*$")

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
- Do not suggest edits to direct quotations (text inside quotation marks or block quotes).
  Comment only on how the author integrates or attributes quoted material.
"""


def grounded(text: str, hay: str) -> bool:
    """True when ``text`` shares enough content words with ``hay``."""
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", (text or "").lower()) if w]
    if not words:
        return False
    hits = sum(1 for w in words if w in hay)
    return hits >= max(2, min(3, len(words) // 4)) if len(words) > 2 else hits >= 1


def is_scoreish(text: str) -> bool:
    """True when the span looks like an accept/reject or numeric grade."""
    return bool(SCOREISH.search(text or ""))


def strip_fences(text: str) -> str:
    lines = (text or "").splitlines()
    if len(lines) >= 2 and _FENCE.match(lines[0]) and _FENCE.match(lines[-1]):
        return "\n".join(lines[1:-1]).strip()
    return (text or "").strip()


def parse_llm_json(raw: str) -> dict[str, Any] | None:
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


def findings_from_comments(
    comments: Any,
    *,
    hay: str,
    reviewer_id: str,
    source: str = "llm",
    limit: int = 16,
) -> list[Finding]:
    """Map JSON comment rows to suggested findings (ungrounded / score-ish dropped)."""
    extra = {"reviewer": reviewer_id} if reviewer_id else {}
    out: list[Finding] = []
    for row in comments or []:
        if not isinstance(row, dict):
            continue
        quote = str(row.get("quote") or "").strip()
        detail = str(row.get("detail") or "").strip()
        if not detail:
            continue
        if is_scoreish(detail):
            continue
        if quote and snippet_in_direct_quote(hay, quote):
            continue
        if quote and quote.lower() not in hay and not grounded(quote, hay):
            continue
        if not grounded(detail, hay) and not quote:
            continue
        unverified = bool(row.get("unverified")) or (
            quote.lower() not in hay if quote else True
        )
        code = str(row.get("code") or "llm_comment").strip() or "llm_comment"
        row_extra = dict(extra)
        if unverified:
            row_extra["unverified"] = True
        out.append(
            make_finding(
                code=code[:40],
                severity="info",
                lane="suggested",
                loc="",
                quote=quote,
                detail=detail[:500],
                source=source,
                extra=row_extra,
            )
        )
        if len(out) >= limit:
            break
    return out


_grounded = grounded
_strip_fences = strip_fences
_parse_json = parse_llm_json


def load_reviewer_prompt(reviewer: CritiqueReviewer) -> str | None:
    """Builtin JSON prompt, or file contents. None if the path is missing."""
    raw = (reviewer.prompt or "default").strip() or "default"
    if raw == "default":
        return _PROMPT
    path = Path(raw)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def suggested_from_llm(
    cfg: Config,
    doc: ExtractedDoc,
    findings: list[Finding],
    *,
    item: Item | None,
    client: Any | None,
    force: bool,
    metrics: dict[str, Any] | None = None,
    reviewer_ids: list[str] | None = None,
    use_llm: bool = True,
    advanced: bool = False,
    lanes: tuple[str, ...] | list[str] | None = None,
    use_grobid: bool = False,
    pdf_path: Path | None = None,
    offline: bool = False,
    scope_items: list[Item] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[Finding], dict[str, Any] | None]:
    from .critique_lanes import mode_for_lanes, ordered_lanes

    say = on_status or (lambda _msg: None)
    if lanes is None:
        shim: list[str] = []
        if use_llm:
            shim.append("reviewers")
        if advanced:
            shim.append("marg")
        lanes = tuple(shim)
    lanes = ordered_lanes(lanes)
    run_reviewers = "reviewers" in lanes
    run_marg = "marg" in lanes
    run_adversary = "adversary" in lanes
    run_context = "context" in lanes or "context-web" in lanes
    if not run_reviewers and not run_marg and not run_adversary and not run_context:
        return [], None
    lane_list = list(lanes)
    mode = mode_for_lanes(lanes)
    wanted = [w for w in (reviewer_ids or []) if str(w).strip()]
    reviewers = critique_reviewers_for(cfg, wanted or None) if run_reviewers else ()
    if (
        run_reviewers
        and wanted
        and not reviewers
        and not run_marg
        and not run_adversary
        and not run_context
    ):
        return [], {
            "skipped": "no_matching_reviewers",
            "mode": mode,
            "lanes": lane_list,
        }
    if client is None:
        return [], {"skipped": "llm_disabled", "mode": mode, "lanes": lane_list}
    if not force:
        for f in findings:
            if f.code == "pdf_identity_mismatch":
                say(
                    "LLM lane skipped: pdf_identity_mismatch (pass --force to override)"
                )
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
    user = f"Title: {title}\n\nExcerpt:\n{excerpt}\n\nChecked findings:\n" + json.dumps(
        checked, ensure_ascii=False
    )
    if metrics:
        user += (
            "\n\nMetrics:\n"
            + json.dumps(metrics, ensure_ascii=False, default=str)[:4000]
        )

    reviewer_out: list[Finding] = []
    reviewer_meta: list[dict[str, Any]] = []
    first_narrative = ""
    first_model = ""
    first_sha = ""
    skip_reason = ""
    from .llm.client import ChatRequest, chat

    if run_reviewers and wanted and not reviewers:
        skip_reason = "no_matching_reviewers"

    n_reviewers = len(reviewers)
    for i, reviewer in enumerate(reviewers, start=1):
        prompt = load_reviewer_prompt(reviewer)
        model = reviewer.model or cfg.llm_model
        if prompt is None:
            say(f"Reviewer {i}/{n_reviewers} {reviewer.id}: prompt missing, skipped")
            reviewer_meta.append(
                {"id": reviewer.id, "model": model, "skipped": "prompt_missing"}
            )
            skip_reason = skip_reason or "prompt_missing"
            continue
        timeout_s = float(cfg.llm_timeout_s or 120)
        say(
            f"Reviewer {i}/{n_reviewers} {reviewer.id} · {model} "
            f"(timeout {timeout_s:.0f}s)…"
        )
        prompt_sha = sha256((prompt + user[:2000]).encode("utf-8")).hexdigest()[:12]
        request = ChatRequest(
            model=model,
            messages=(
                {"role": "system", "content": prompt},
                {"role": "user", "content": user},
            ),
            timeout_seconds=timeout_s,
            temperature=0.2,
        )
        t0 = time.perf_counter()
        try:
            raw = chat(client, request)
        except Exception as exc:
            dt = time.perf_counter() - t0
            say(
                f"Reviewer {i}/{n_reviewers} {reviewer.id} failed after {dt:.0f}s: {exc}"
            )
            reviewer_meta.append(
                {
                    "id": reviewer.id,
                    "model": model,
                    "prompt_sha": prompt_sha,
                    "skipped": "llm_error",
                    "error": str(exc),
                }
            )
            skip_reason = skip_reason or "llm_error"
            reviewer_out.append(
                make_finding(
                    code="llm_failed",
                    severity="info",
                    lane="suggested",
                    detail=f"LLM lane failed ({reviewer.id}): {exc}",
                    source="llm",
                    extra={"reviewer": reviewer.id},
                )
            )
            continue
        extra, narrative = _findings_from_reply(
            raw, hay=hay, reviewer_id=reviewer.id, json_prompt=prompt == _PROMPT
        )
        dt = time.perf_counter() - t0
        bits = [f"{dt:.0f}s"]
        if extra:
            bits.append(f"{len(extra)} comment(s)")
        if narrative:
            bits.append("note")
        say(f"Reviewer {i}/{n_reviewers} {reviewer.id} done ({', '.join(bits)})")
        reviewer_out.extend(extra)
        row: dict[str, Any] = {
            "id": reviewer.id,
            "model": model,
            "prompt_sha": prompt_sha,
        }
        if narrative:
            row["narrative"] = narrative
            if not first_narrative:
                first_narrative = narrative
                first_model = model
        if extra or narrative:
            first_sha = first_sha or prompt_sha
        elif not extra:
            row["skipped"] = "empty_reply"
            skip_reason = skip_reason or "empty_reply"
        reviewer_meta.append(row)

    if reviewers:
        reviewer_out = reviewer_out[: 16 * max(1, len(reviewers))]
    out = list(reviewer_out)
    marg_meta: dict[str, Any] = {}
    if run_marg:
        from .critique_marg import suggested_from_marg

        say("MARG-S lane comments…")
        t_m = time.perf_counter()
        extra_m, marg_meta = suggested_from_marg(
            cfg,
            doc,
            findings,
            item=item,
            client=client,
            hay=hay,
            pdf_path=pdf_path,
            use_grobid=use_grobid,
            on_status=say,
        )
        say(
            f"MARG-S comments done ({time.perf_counter() - t_m:.0f}s, "
            f"{len(extra_m)} comment(s))"
        )
        out.extend(extra_m)
        reviewer_meta.extend(marg_meta.get("reviewers") or [])
        if extra_m or marg_meta.get("narrative"):
            first_sha = first_sha or str(marg_meta.get("prompt_sha") or "")
            if not first_narrative and marg_meta.get("narrative"):
                first_narrative = str(marg_meta.get("narrative") or "")
                first_model = first_model or str(marg_meta.get("model") or "")
        elif not extra_m:
            skip_reason = skip_reason or str(marg_meta.get("skipped") or "empty_reply")

    adversary_meta: dict[str, Any] = {}
    if run_adversary:
        from .critique_adversary import suggested_from_adversary

        t_a = time.perf_counter()
        extra_a, adversary_meta = suggested_from_adversary(
            cfg,
            doc,
            findings,
            item=item,
            client=client,
            hay=hay,
            on_status=say,
        )
        say(
            f"Adversary comments done ({time.perf_counter() - t_a:.0f}s, "
            f"{len(extra_a)} comment(s))"
        )
        out.extend(extra_a)
        reviewer_meta.extend(adversary_meta.get("reviewers") or [])
        if extra_a or adversary_meta.get("narrative"):
            first_sha = first_sha or str(adversary_meta.get("prompt_sha") or "")
            if not first_narrative and adversary_meta.get("narrative"):
                first_narrative = str(adversary_meta.get("narrative") or "")
                first_model = first_model or str(adversary_meta.get("model") or "")
        elif not extra_a:
            skip_reason = skip_reason or str(
                adversary_meta.get("skipped") or "empty_reply"
            )

    context_meta: dict[str, Any] = {}
    if run_context:
        from .critique_context import suggested_from_context

        search_enabled = "context-web" in lanes
        label = "Context-web" if search_enabled else "Context"
        say(f"{label} lane…")
        t_c = time.perf_counter()
        extra_c, context_meta = suggested_from_context(
            cfg,
            doc,
            findings,
            item=item,
            client=client,
            hay=hay,
            search_enabled=search_enabled,
            offline=offline,
            scope_items=scope_items or [],
            on_status=say,
        )
        say(
            f"{label} done ({time.perf_counter() - t_c:.0f}s, "
            f"{len(extra_c)} comment(s))"
        )
        out.extend(extra_c)
        reviewer_meta.extend(context_meta.get("reviewers") or [])
        if extra_c or context_meta.get("narrative"):
            first_sha = first_sha or str(context_meta.get("prompt_sha") or "")
            if not first_narrative and context_meta.get("narrative"):
                first_narrative = str(context_meta.get("narrative") or "")
                first_model = first_model or str(context_meta.get("model") or "")
        elif not extra_c:
            skip_reason = skip_reason or str(
                context_meta.get("skipped") or "empty_reply"
            )

    capped = out

    def _pack_meta(*, skipped: str = "") -> dict[str, Any]:
        row: dict[str, Any] = {
            "model": first_model
            or (reviewers[0].model if reviewers else "")
            or cfg.llm_model,
            "mode": mode,
            "lanes": lane_list,
        }
        if skipped:
            row["skipped"] = skipped
        else:
            row["prompt_sha"] = first_sha
            row["provider"] = getattr(client, "provider", "")
            row["reviewers"] = reviewer_meta
        if skipped and reviewer_meta:
            row["reviewers"] = reviewer_meta
        if first_narrative:
            row["narrative"] = first_narrative
        if marg_meta:
            row["marg"] = {k: v for k, v in marg_meta.items() if k != "reviewers"}
        if adversary_meta:
            row["adversary"] = {
                k: v for k, v in adversary_meta.items() if k != "reviewers"
            }
        if context_meta:
            row["context"] = {
                k: v for k, v in context_meta.items() if k != "reviewers"
            }
        return row

    if not capped and not first_narrative:
        return [], _pack_meta(skipped=skip_reason or "empty_reply")
    return capped, _pack_meta()


def _findings_from_reply(
    raw: str,
    *,
    hay: str,
    reviewer_id: str,
    json_prompt: bool,
) -> tuple[list[Finding], str]:
    extra = {"reviewer": reviewer_id} if reviewer_id else {}
    data = parse_llm_json(raw)
    if data is None and json_prompt:
        return [], ""
    if data is None:
        narrative = strip_fences(raw)[:4000]
        if not narrative:
            return [], ""
        # Keep the reviewer note even if it says accept/reject; do not also
        # copy that verdict into suggested findings.
        if is_scoreish(narrative):
            return [], narrative
        return [
            make_finding(
                code="llm_summary",
                severity="info",
                lane="suggested",
                detail=narrative[:500],
                quote=narrative[:200],
                source="llm",
                extra=extra,
            )
        ], narrative
    out: list[Finding] = []
    summary = str(data.get("summary") or "").strip()
    narrative = ""
    if summary and grounded(summary, hay):
        out.append(
            make_finding(
                code="llm_summary",
                severity="info",
                lane="suggested",
                detail=summary[:500],
                quote=summary[:200],
                source="llm",
                extra=extra,
            )
        )
        narrative = summary
    out.extend(
        findings_from_comments(
            data.get("comments"), hay=hay, reviewer_id=reviewer_id, limit=16
        )
    )
    for q in data.get("questions") or []:
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
                extra=extra,
            )
        )
        if sum(1 for f in out if f.code == "author_question") >= 5:
            break
    return out[:16], narrative
