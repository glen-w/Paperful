"""Optional grounded LLM comments. Suggested lane only. No scores."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import (
    CRITIQUE_REVIEWER_MAX_TOKENS,
    Config,
    CritiqueReviewer,
    critique_reviewers_for,
)
from .critique import Finding, make_finding
from .critique_direct_quotes import snippet_in_direct_quote
from .critique_extract import ExtractedDoc
from .grounding import budget_slice
from .llm.client import ChatRequest, LLMClientError
from .zot import Item

SCOREISH = re.compile(
    r"\b(?:accept|reject|overall score|grade\s*[1-6]|score\s*[1-6]\s*/\s*6)\b",
    re.I,
)
_SCOREISH = SCOREISH
_FENCE = re.compile(r"^```[a-zA-Z]*\s*$")
_THINK_BLOCK = re.compile(r"<think>[\s\S]*?</think>", re.I)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
JSON_REPAIR_USER = (
    "Your previous reply was not valid JSON matching the schema. "
    "Reply with a single JSON object only."
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
    text = _THINK_BLOCK.sub("", raw or "").strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
    except ValueError:
        return None
    slice_ = text[start:end]
    for candidate in (slice_, _TRAILING_COMMA.sub(r"\1", slice_)):
        data = _loads_object(candidate)
        if isinstance(data, dict):
            return data
    return None


def _loads_object(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            data, _end = json.JSONDecoder().raw_decode(text)
        except json.JSONDecodeError:
            return None
        return data


def critique_chat_request(
    *,
    model: str,
    messages: tuple[dict[str, str], ...] | list[dict[str, str]],
    timeout_seconds: float,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> ChatRequest:
    """Critique JSON turns pin format=json and turn thinking off (qwen3)."""
    return ChatRequest(
        model=model,
        messages=tuple(messages),
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
        think=False,
    )


def chat_with_json_retry(
    client: Any,
    request: ChatRequest,
    *,
    on_status: Callable[[str], None] | None = None,
    label: str = "",
) -> str:
    """One chat, then one repair turn if the reply is not a JSON object."""
    from .llm.client import chat

    say = on_status or (lambda _msg: None)
    raw = chat(client, request)
    if parse_llm_json(raw) is not None:
        return raw
    if label:
        say(f"{label} retry (unusable JSON)…")
    repair = ChatRequest(
        model=request.model,
        messages=tuple(request.messages)
        + (
            {"role": "assistant", "content": (raw or "")[:8000]},
            {"role": "user", "content": JSON_REPAIR_USER},
        ),
        timeout_seconds=request.timeout_seconds,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        num_ctx=request.num_ctx,
        json_mode=True,
        think=False,
    )
    return chat(client, repair)


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


def chat_reviewer_stream(
    client: Any,
    request: ChatRequest,
    *,
    wall_s: float,
    on_status: Callable[[str], None] | None = None,
    label: str = "Reviewer",
    heartbeat_s: float = 30.0,
) -> str:
    """Stream a reviewer reply; abort when wall clock expires.

    ``request.timeout_seconds`` remains the idle gap between Ollama chunks.
    ``wall_s`` is total elapsed time for this reviewer call.
    """
    say = on_status or (lambda _msg: None)
    raw_wall = float(wall_s) if wall_s is not None else 0.0
    if raw_wall <= 0:
        raw_wall = float(request.timeout_seconds or 120) or 120.0
    wall = max(0.01, raw_wall)
    beat = max(0.01, float(heartbeat_s))
    parts: list[str] = []
    t0 = time.perf_counter()
    last_beat = t0
    stream = client.chat_stream(request)
    try:
        for piece in stream:
            parts.append(piece)
            now = time.perf_counter()
            if now - t0 >= wall:
                raise LLMClientError(
                    f"Reviewer wall clock exceeded after {wall:.0f}s "
                    f"({sum(len(p) for p in parts)} chars)"
                )
            if now - last_beat >= beat:
                say(
                    f"{label} still generating "
                    f"({now - t0:.0f}s, {sum(len(p) for p in parts)} chars)…"
                )
                last_beat = now
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: S110 -- best-effort cleanup; intentionally ignored
                pass
    return "".join(parts)


@dataclass
class _LaneState:
    out: list[Finding] = field(default_factory=list)
    reviewer_meta: list[dict[str, Any]] = field(default_factory=list)
    first_narrative: str = ""
    first_model: str = ""
    first_sha: str = ""
    skip_reason: str = ""
    marg_meta: dict[str, Any] = field(default_factory=dict)
    adversary_meta: dict[str, Any] = field(default_factory=dict)
    outline_meta: dict[str, Any] = field(default_factory=dict)
    claims_meta: dict[str, Any] = field(default_factory=dict)
    verify_meta: dict[str, Any] = field(default_factory=dict)
    context_meta: dict[str, Any] = field(default_factory=dict)

    def absorb(
        self,
        extra: list[Finding],
        meta: dict[str, Any],
        *,
        keep_if_ledger: bool = False,
        keep_if_narrative: bool = True,
    ) -> None:
        self.out.extend(extra)
        self.reviewer_meta.extend(meta.get("reviewers") or [])
        keep = (
            extra
            or (keep_if_narrative and meta.get("narrative"))
            or (keep_if_ledger and meta.get("ledger"))
        )
        if keep:
            self.first_sha = self.first_sha or str(meta.get("prompt_sha") or "")
            if not self.first_narrative and meta.get("narrative"):
                self.first_narrative = str(meta.get("narrative") or "")
                self.first_model = self.first_model or str(meta.get("model") or "")
        elif not extra:
            self.skip_reason = self.skip_reason or str(
                meta.get("skipped") or "empty_reply"
            )


def _run_optional_lane(
    *,
    enabled: bool,
    start_msg: str,
    done_label: str,
    runner: Callable[[], tuple[list[Finding], dict[str, Any]]],
    say: Callable[[str], None],
) -> tuple[list[Finding], dict[str, Any]]:
    if not enabled:
        return [], {}
    if start_msg:
        say(start_msg)
    t0 = time.perf_counter()
    extra, meta = runner()
    say(f"{done_label} ({time.perf_counter() - t0:.0f}s, {len(extra)} comment(s))")
    return extra, meta


def _run_reviewers(
    *,
    cfg: Config,
    client: Any,
    reviewers: tuple[CritiqueReviewer, ...],
    user: str,
    hay: str,
    say: Callable[[str], None],
) -> tuple[list[Finding], list[dict[str, Any]], str, str, str, str]:
    reviewer_out: list[Finding] = []
    reviewer_meta: list[dict[str, Any]] = []
    first_narrative = ""
    first_model = ""
    first_sha = ""
    skip_reason = ""
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
        label = f"Reviewer {i}/{n_reviewers} {reviewer.id}"
        say(f"{label} · {model} (wall {timeout_s:.0f}s, idle {timeout_s:.0f}s)…")
        prompt_sha = sha256((prompt + user[:2000]).encode("utf-8")).hexdigest()[:12]
        max_tokens = int(getattr(reviewer, "max_tokens", CRITIQUE_REVIEWER_MAX_TOKENS))
        json_prompt = prompt == _PROMPT
        request = critique_chat_request(
            model=model,
            messages=(
                {"role": "system", "content": prompt},
                {"role": "user", "content": user},
            ),
            timeout_seconds=timeout_s,
            temperature=0.2,
            max_tokens=max_tokens if max_tokens > 0 else None,
            json_mode=json_prompt,
        )
        t0 = time.perf_counter()
        try:
            raw = chat_reviewer_stream(
                client,
                request,
                wall_s=timeout_s,
                on_status=say,
                label=label,
            )
            extra, narrative = _findings_from_reply(
                raw, hay=hay, reviewer_id=reviewer.id, json_prompt=json_prompt
            )
            if json_prompt and not extra and not narrative:
                say(f"{label} retry (unusable JSON)…")
                repair = critique_chat_request(
                    model=model,
                    messages=tuple(request.messages)
                    + (
                        {"role": "assistant", "content": (raw or "")[:8000]},
                        {"role": "user", "content": JSON_REPAIR_USER},
                    ),
                    timeout_seconds=timeout_s,
                    temperature=0.2,
                    max_tokens=max_tokens if max_tokens > 0 else None,
                    json_mode=True,
                )
                raw = chat_reviewer_stream(
                    client,
                    repair,
                    wall_s=timeout_s,
                    on_status=say,
                    label=label,
                )
                extra, narrative = _findings_from_reply(
                    raw, hay=hay, reviewer_id=reviewer.id, json_prompt=True
                )
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
    return (
        reviewer_out,
        reviewer_meta,
        first_narrative,
        first_model,
        first_sha,
        skip_reason,
    )


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
    run_outline = "outline" in lanes
    run_claims = "claims" in lanes
    run_verify = "verify" in lanes
    run_context = "context" in lanes or "context-web" in lanes
    if not (
        run_reviewers
        or run_marg
        or run_adversary
        or run_outline
        or run_claims
        or run_verify
        or run_context
    ):
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
        and not run_outline
        and not run_claims
        and not run_verify
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

    state = _LaneState()
    if run_reviewers and wanted and not reviewers:
        state.skip_reason = "no_matching_reviewers"
    if reviewers:
        (
            reviewer_out,
            reviewer_meta,
            first_narrative,
            first_model,
            first_sha,
            skip_reason,
        ) = _run_reviewers(
            cfg=cfg,
            client=client,
            reviewers=reviewers,
            user=user,
            hay=hay,
            say=say,
        )
        state.out.extend(reviewer_out)
        state.reviewer_meta.extend(reviewer_meta)
        state.first_narrative = first_narrative
        state.first_model = first_model
        state.first_sha = first_sha
        state.skip_reason = state.skip_reason or skip_reason

    def _marg() -> tuple[list[Finding], dict[str, Any]]:
        from .critique_marg import suggested_from_marg

        return suggested_from_marg(
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

    extra_m, state.marg_meta = _run_optional_lane(
        enabled=run_marg,
        start_msg="MARG-S lane comments…",
        done_label="MARG-S comments done",
        runner=_marg,
        say=say,
    )
    state.absorb(extra_m, state.marg_meta)

    def _adversary() -> tuple[list[Finding], dict[str, Any]]:
        from .critique_adversary import suggested_from_adversary

        return suggested_from_adversary(
            cfg,
            doc,
            findings,
            item=item,
            client=client,
            hay=hay,
            on_status=say,
        )

    extra_a, state.adversary_meta = _run_optional_lane(
        enabled=run_adversary,
        start_msg="",
        done_label="Adversary comments done",
        runner=_adversary,
        say=say,
    )
    state.absorb(extra_a, state.adversary_meta)

    def _outline() -> tuple[list[Finding], dict[str, Any]]:
        from .critique_outline import suggested_from_outline

        return suggested_from_outline(
            cfg,
            doc,
            findings,
            item=item,
            client=client,
            hay=hay,
            on_status=say,
        )

    extra_o, state.outline_meta = _run_optional_lane(
        enabled=run_outline,
        start_msg="",
        done_label="Outline comments done",
        runner=_outline,
        say=say,
    )
    state.absorb(extra_o, state.outline_meta, keep_if_ledger=True)

    def _claims() -> tuple[list[Finding], dict[str, Any]]:
        from .critique_claims import suggested_from_claims

        return suggested_from_claims(
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

    extra_cl, state.claims_meta = _run_optional_lane(
        enabled=run_claims,
        start_msg="",
        done_label="Claims comments done",
        runner=_claims,
        say=say,
    )
    state.absorb(
        extra_cl,
        state.claims_meta,
        keep_if_ledger=True,
        keep_if_narrative=False,
    )

    def _verify() -> tuple[list[Finding], dict[str, Any]]:
        from .critique_verify import suggested_from_verify

        return suggested_from_verify(
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

    extra_v, state.verify_meta = _run_optional_lane(
        enabled=run_verify,
        start_msg="",
        done_label="Verify comments done",
        runner=_verify,
        say=say,
    )
    state.absorb(extra_v, state.verify_meta)

    def _context() -> tuple[list[Finding], dict[str, Any]]:
        from .critique_context import suggested_from_context

        return suggested_from_context(
            cfg,
            doc,
            findings,
            item=item,
            client=client,
            hay=hay,
            search_enabled="context-web" in lanes,
            offline=offline,
            scope_items=scope_items or [],
            on_status=say,
        )

    ctx_label = "Context-web" if "context-web" in lanes else "Context"
    extra_c, state.context_meta = _run_optional_lane(
        enabled=run_context,
        start_msg=f"{ctx_label} lane…",
        done_label=f"{ctx_label} done",
        runner=_context,
        say=say,
    )
    state.absorb(extra_c, state.context_meta)

    capped = state.out
    first_model = state.first_model
    first_sha = state.first_sha
    first_narrative = state.first_narrative
    reviewer_meta = state.reviewer_meta
    skip_reason = state.skip_reason
    marg_meta = state.marg_meta
    adversary_meta = state.adversary_meta
    outline_meta = state.outline_meta
    claims_meta = state.claims_meta
    verify_meta = state.verify_meta
    context_meta = state.context_meta

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
        if outline_meta:
            row["outline"] = {
                k: v
                for k, v in outline_meta.items()
                if k not in {"reviewers", "ledger"}
            }
            row["outline_ledger"] = list(outline_meta.get("ledger") or [])
        if claims_meta:
            row["claims"] = {
                k: v for k, v in claims_meta.items() if k not in {"reviewers", "ledger"}
            }
            row["claims_ledger"] = list(claims_meta.get("ledger") or [])
        if verify_meta:
            row["verify"] = {k: v for k, v in verify_meta.items() if k != "reviewers"}
        if context_meta:
            row["context"] = {k: v for k, v in context_meta.items() if k != "reviewers"}
        return row

    if (
        not capped
        and not first_narrative
        and not (claims_meta.get("ledger") or [])
        and not (outline_meta.get("ledger") or [])
    ):
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
