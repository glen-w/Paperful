"""MARG-S-style multi-agent suggested comments. Suggested lane only. No scores.

Inspired by D'Arcy et al., arXiv:2401.04259 (Apache-2.0). Paperful orchestrates
JSON turns locally; it does not vendor allenai/marg-reviewer prompts or Grobid.
Optional GROBID TEI uses the operator sidecar from ``d001b9b9``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import Config
from .critique import Finding, make_finding
from .critique_extract import ExtractedDoc
from .critique_llm import findings_from_comments, grounded, parse_llm_json
from .critique_units import Unit, units_from_doc, units_from_markdown
from .zot import Item

ASPECTS = ("experiments", "clarity", "impact")
DEFAULT_ASPECTS = ASPECTS
KNOWN_ASPECTS = (
    "experiments",
    "clarity",
    "impact",
    "theory",
    "policy",
    "evidence-base",
)


def parse_marg_aspects(raw: Any) -> tuple[str, ...]:
    """Parse ``[critique].advanced_aspects``. Empty → default triple."""
    if raw is None or raw == "" or raw == []:
        return DEFAULT_ASPECTS
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple)):
        parts = [str(part).strip() for part in raw if str(part).strip()]
    else:
        raise ValueError("[critique].advanced_aspects must be an array of aspect ids")
    seen: list[str] = []
    for part in parts:
        name = part.lower()
        if name not in KNOWN_ASPECTS:
            raise ValueError(
                f"unknown MARG aspect {part!r} (want {', '.join(KNOWN_ASPECTS)})"
            )
        if name not in seen:
            seen.append(name)
    return tuple(seen) if seen else DEFAULT_ASPECTS


def resolve_marg_aspects(cfg: Config) -> tuple[str, ...]:
    raw = getattr(cfg, "critique_advanced_aspects", ()) or ()
    if not raw:
        return DEFAULT_ASPECTS
    return parse_marg_aspects(raw)


_LEADER_SYSTEM = """You lead a small review group for one aspect of a manuscript.
Workers each hold one chunk of the paper. One expert assists you.
Return JSON only:
{"action": "broadcast" or "final", "message": "text for workers", "summary": "optional paragraph", "comments": [{"quote": "span from the paper", "detail": "actionable comment", "code": "short_code"}]}
Rules:
- action=broadcast sends message to every worker and the expert.
- action=final ends the group. Put the aspect comments in comments.
- Quotes MUST appear in the paper chunks you were told about.
- Do not give an overall score, grade, or accept/reject.
- Do not claim plagiarism or misconduct.
- Do not suggest edits inside direct quotations; comment on attribution or integration only.
- At most 8 comments.
"""

_WORKER_SYSTEM = """You are {name}. You hold one chunk of a manuscript. Obey the leader.
Return JSON only:
{{"reply": "your reply", "comments": [{{"quote": "span from YOUR chunk", "detail": "comment"}}]}}
If the leader's message is not for you, reply with {{"reply": "NO_RESPONSE", "comments": []}}.
Quotes MUST be substrings of your chunk. No score, grade, or accept/reject.
Do not suggest edits inside direct quotations.
"""

_EXPERT_SYSTEM = {
    "experiments": (
        "You are the experiments expert. Sketch the experiments or proofs you would "
        "expect for the paper's claims, then compare them to what the chunks describe. "
        'Reply JSON: {"reply": "...", "comments": [{"quote": "...", "detail": "..."}]}. '
        "No score or accept/reject."
    ),
    "clarity": (
        "You are the clarity expert. Be highly curious. Ask what a careful reader "
        "still cannot reproduce or understand from the chunks. "
        'Reply JSON: {"reply": "...", "comments": [{"quote": "...", "detail": "..."}]}. '
        "No score or accept/reject."
    ),
    "impact": (
        "You are the impact expert. Be skeptical of novelty and contribution claims "
        "that the paper itself does not justify. Do not search the web. "
        'Reply JSON: {"reply": "...", "comments": [{"quote": "...", "detail": "..."}]}. '
        "No score or accept/reject."
    ),
    "theory": (
        "You are the theory expert. Look for proof or lemma gaps, missing "
        "assumptions, and counterexample-shaped holes. Do not invent theorems. "
        'Reply JSON: {"reply": "...", "comments": [{"quote": "...", "detail": "..."}]}. '
        "No score or accept/reject."
    ),
    "policy": (
        "You are the policy expert. Check legal warrant, instrument fit, and "
        "whether a mandate is supported by the evidence the text itself cites. "
        'Reply JSON: {"reply": "...", "comments": [{"quote": "...", "detail": "..."}]}. '
        "No score or accept/reject. Do not search the web."
    ),
    "evidence-base": (
        "You are the evidence-base expert for survey or doctrinal drafts. Flag "
        "overclaim versus the cited set and thin source coverage named in the text. "
        'Reply JSON: {"reply": "...", "comments": [{"quote": "...", "detail": "..."}]}. '
        "No score or accept/reject. Do not search the web."
    ),
}

_ASPECT_TASK = {
    "experiments": (
        "Focus on experiments, proofs, and whether they support the stated claims. "
        "Note missing comparisons, missing sample sizes, or unsupported numbers."
    ),
    "clarity": (
        "Focus on clarity and reproducibility. Flag undefined methods, missing steps, "
        "or terms a reader cannot recover from the text."
    ),
    "impact": (
        "Focus on how the paper states its motivation, contribution, and related work. "
        "Do not invent citations. Only comment on what the text itself claims."
    ),
    "theory": (
        "Focus on proofs, lemmas, and formal claims. Note missing assumptions "
        "or steps a reader cannot reconstruct. Do not invent counterexamples "
        "that contradict the excerpt."
    ),
    "policy": (
        "Focus on legal or policy warrant: does the instrument the paper names "
        "match the evidence it presents? Do not invent statutes or cases."
    ),
    "evidence-base": (
        "Focus on whether the cited set in the text can carry the survey or "
        "doctrinal claim. Do not invent sources."
    ),
}

_REFINE_SYSTEM = """You refine a list of suggested manuscript comments.
Return JSON only:
{"comments": [{"quote": "span from the paper", "detail": "clear specific comment", "code": "short_code"}]}
Drop comments that are invalid, generic, already done in the paper, or score-like.
Split mixed comments. Keep at most the asked maximum. No accept/reject or grade.
"""


@dataclass
class Chunk:
    worker_id: str
    heading: str
    loc: str
    text: str


def advanced_timeout_s(cfg: Config) -> float:
    raw = float(getattr(cfg, "critique_advanced_timeout_s", 0) or 0)
    if raw > 0:
        return raw
    return max(float(cfg.llm_timeout_s or 120), 600.0)


def grobid_markdown(
    cfg: Config, pdf: Path, *, item_key: str = ""
) -> tuple[list[str] | None, str]:
    """TEI-projected markdown pages, or ``(None, skip_reason)``."""
    try:
        from .grobid_client import GrobidConfigError, GrobidError
        from .sections.grobid import pdf_is_scan, process_pdf, tei_to_markdown_pages
    except Exception as exc:  # pragma: no cover - import surface
        return None, f"import:{exc}"
    try:
        if pdf_is_scan(pdf):
            return None, "scan"
        tei = process_pdf(cfg, pdf, item_key=item_key)
        pages = tei_to_markdown_pages(tei)
        if not pages:
            return None, "empty_tei"
        return pages, ""
    except (GrobidError, GrobidConfigError, OSError, ValueError) as exc:
        return None, str(exc)[:200]


def pack_chunks(units: list[Unit], *, max_workers: int, max_chars: int) -> list[Chunk]:
    if not units:
        return []
    n_workers = max(1, min(int(max_workers or 1), len(units)))
    budget = max(800, int(max_chars or 24_000) // n_workers)
    buckets: list[list[Unit]] = []
    current: list[Unit] = []
    size = 0
    for unit in units:
        piece = len(unit.text) + 1
        if current and (size + piece > budget) and len(buckets) + 1 < n_workers:
            buckets.append(current)
            current = []
            size = 0
        current.append(unit)
        size += piece
    if current:
        buckets.append(current)
    chunks: list[Chunk] = []
    for i, group in enumerate(buckets, 1):
        heading = next((u.heading for u in group if u.heading), "")
        loc = group[0].loc if len(group) == 1 else f"{group[0].loc}–{group[-1].loc}"
        text = "\n\n".join(
            f"[{u.loc}" + (f" | {u.heading}" if u.heading else "") + f"]\n{u.text}"
            for u in group
        )
        chunks.append(
            Chunk(worker_id=f"worker-{i}", heading=heading, loc=loc, text=text)
        )
    return chunks


def paper_chunks(
    cfg: Config,
    doc: ExtractedDoc,
    *,
    use_grobid: bool,
    pdf_path: Path | None,
    item_key: str = "",
) -> tuple[list[Chunk], dict[str, Any]]:
    parser = "extract"
    skip = ""
    units: list[Unit] = []
    if use_grobid and pdf_path is not None and pdf_path.suffix.lower() == ".pdf":
        pages, skip = grobid_markdown(cfg, pdf_path, item_key=item_key)
        if pages:
            units = units_from_markdown(pages)
            parser = "grobid"
        else:
            skip = skip or "grobid_failed"
    if not units:
        units = units_from_doc(doc)
        parser = "extract"
    max_workers = max(1, int(getattr(cfg, "critique_advanced_max_workers", 4) or 4))
    chunks = pack_chunks(
        units,
        max_workers=max_workers,
        max_chars=int(cfg.critique_max_context_chars or 24_000),
    )
    meta: dict[str, Any] = {"parser": parser, "workers": len(chunks)}
    if skip and parser == "extract":
        meta["grobid_skipped"] = skip
    return chunks, meta


def _chat(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, str]],
    timeout: float,
) -> str:
    from .llm.client import ChatRequest, chat

    request = ChatRequest(
        model=model,
        messages=tuple(messages),
        timeout_seconds=max(5.0, float(timeout)),
        temperature=0.2,
    )
    return chat(client, request)


def _leader_user(
    aspect: str, chunks: list[Chunk], checked: list[dict[str, Any]], title: str
) -> str:
    index = [
        {"id": c.worker_id, "loc": c.loc, "heading": c.heading, "chars": len(c.text)}
        for c in chunks
    ]
    return (
        f"Title: {title}\nAspect: {aspect}\nTask: {_ASPECT_TASK[aspect]}\n"
        f"Workers: {json.dumps(index, ensure_ascii=False)}\n"
        f"Checked findings: {json.dumps(checked, ensure_ascii=False)}\n"
        "Plan briefly, then broadcast or finalize."
    )


def _run_group(
    cfg: Config,
    client: Any,
    *,
    aspect: str,
    chunks: list[Chunk],
    checked: list[dict[str, Any]],
    title: str,
    hay: str,
    model: str,
    deadline: float,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    max_rounds = max(1, int(getattr(cfg, "critique_advanced_max_rounds", 4) or 4))
    calls = 0
    rounds = 0
    stats: dict[str, Any] = {"id": f"marg-{aspect}", "model": model, "aspect": aspect}
    prompt_sha = sha256((_LEADER_SYSTEM + aspect).encode("utf-8")).hexdigest()[:12]
    stats["prompt_sha"] = prompt_sha

    def remaining() -> float:
        return max(1.0, deadline - time.monotonic())

    if time.monotonic() >= deadline:
        stats["skipped"] = "timeout"
        return [], "", stats

    leader: list[dict[str, str]] = [
        {"role": "system", "content": _LEADER_SYSTEM},
        {"role": "user", "content": _leader_user(aspect, chunks, checked, title)},
    ]
    worker_histories: dict[str, list[dict[str, str]]] = {}
    for chunk in chunks:
        worker_histories[chunk.worker_id] = [
            {
                "role": "system",
                "content": _WORKER_SYSTEM.format(name=chunk.worker_id),
            },
            {
                "role": "user",
                "content": f"Your chunk ({chunk.loc}):\n{chunk.text}",
            },
        ]
    expert_hist: list[dict[str, str]] = [
        {"role": "system", "content": _EXPERT_SYSTEM[aspect]},
        {
            "role": "user",
            "content": "Chunks:\n"
            + "\n\n".join(f"{c.worker_id} ({c.loc}): {c.text[:1500]}" for c in chunks)[
                :8000
            ],
        },
    ]
    seen: set[str] = set()
    comments: list[dict[str, Any]] = []
    narrative = ""
    last_action = ""
    for _round in range(max_rounds):
        if time.monotonic() >= deadline:
            stats["skipped"] = "timeout"
            break
        rounds += 1
        try:
            raw = _chat(client, model=model, messages=leader, timeout=remaining())
        except Exception as exc:
            stats["skipped"] = "llm_error"
            stats["error"] = str(exc)
            break
        calls += 1
        leader.append({"role": "assistant", "content": raw})
        data = parse_llm_json(raw) or {}
        action = str(data.get("action") or "").strip().lower()
        message = str(data.get("message") or "").strip()
        if data.get("comments"):
            comments.extend(row for row in data["comments"] if isinstance(row, dict))
        summary = str(data.get("summary") or "").strip()
        if summary and grounded(summary, hay):
            narrative = narrative or summary
        last_action = action or last_action
        if action == "final" or (not action and comments):
            break
        if action != "broadcast" or not message:
            leader.append(
                {
                    "role": "user",
                    "content": "Return JSON with action=final and your comments now.",
                }
            )
            continue
        if message in seen:
            if (message + "#dup") in seen:
                stats["skipped"] = stats.get("skipped") or "loop"
                break
            leader.append(
                {
                    "role": "user",
                    "content": "That message was duplicated. Do not send it again. "
                    "Return action=final with the comment list.",
                }
            )
            seen.add(message + "#dup")
            continue
        seen.add(message)
        replies: list[str] = []
        for chunk in chunks:
            hist = worker_histories[chunk.worker_id]
            hist.append({"role": "user", "content": f"Message from leader: {message}"})
            try:
                wraw = _chat(client, model=model, messages=hist, timeout=remaining())
            except Exception as exc:
                replies.append(f"{chunk.worker_id}: error {exc}")
                hist.pop()
                continue
            calls += 1
            hist.append({"role": "assistant", "content": wraw})
            if len(hist) > 6:
                worker_histories[chunk.worker_id] = hist[:2] + hist[-3:]
            wdata = parse_llm_json(wraw) or {}
            reply = str(wdata.get("reply") or wraw).strip()
            if reply.upper() != "NO_RESPONSE":
                replies.append(f"{chunk.worker_id}: {reply[:800]}")
            if wdata.get("comments"):
                comments.extend(
                    row for row in wdata["comments"] if isinstance(row, dict)
                )
        expert_hist.append(
            {"role": "user", "content": f"Message from leader: {message}"}
        )
        try:
            eraw = _chat(client, model=model, messages=expert_hist, timeout=remaining())
            calls += 1
            expert_hist.append({"role": "assistant", "content": eraw})
            edata = parse_llm_json(eraw) or {}
            ereply = str(edata.get("reply") or eraw).strip()
            replies.append(f"expert: {ereply[:800]}")
            if edata.get("comments"):
                comments.extend(
                    row for row in edata["comments"] if isinstance(row, dict)
                )
        except Exception as exc:
            replies.append(f"expert: error {exc}")
        # Keep outgoing leader messages; prune older worker-reply user turns.
        leader = [
            m
            for m in leader
            if m["role"] != "user"
            or m is leader[1]
            or "Workers:" in m.get("content", "")
        ]
        leader.append(
            {
                "role": "user",
                "content": "Replies:\n"
                + "\n".join(replies)
                + "\nIf you have enough, return action=final.",
            }
        )

    stats["rounds"] = rounds
    stats["calls"] = calls
    if comments:
        stats["comments"] = len(comments)
    elif stats.get("skipped"):
        pass
    elif last_action != "final":
        stats["skipped"] = stats.get("skipped") or "empty_reply"
    return comments, narrative, stats


def _refine(
    cfg: Config,
    client: Any,
    *,
    comments: list[dict[str, Any]],
    hay: str,
    model: str,
    deadline: float,
    excerpt: str,
) -> tuple[list[dict[str, Any]], int]:
    cap = max(1, int(getattr(cfg, "critique_advanced_max_comments", 12) or 12))
    if not comments:
        return [], 0
    if not bool(getattr(cfg, "critique_advanced_refine", True)):
        return comments[:cap], 0
    if time.monotonic() >= deadline:
        return comments[:cap], 0
    payload = json.dumps(comments[: cap * 2], ensure_ascii=False)[:12_000]
    messages = [
        {"role": "system", "content": _REFINE_SYSTEM},
        {
            "role": "user",
            "content": f"Keep at most {cap} comments.\nPaper excerpt:\n{excerpt[:4000]}\n"
            f"Comments:\n{payload}",
        },
    ]
    try:
        raw = _chat(
            client,
            model=model,
            messages=messages,
            timeout=max(1.0, deadline - time.monotonic()),
        )
    except Exception:
        return comments[:cap], 0
    data = parse_llm_json(raw) or {}
    rows = [row for row in (data.get("comments") or []) if isinstance(row, dict)]
    return (rows[:cap] if rows else comments[:cap]), 1


def suggested_from_marg(
    cfg: Config,
    doc: ExtractedDoc,
    findings: list[Finding],
    *,
    item: Item | None,
    client: Any,
    hay: str,
    pdf_path: Path | None = None,
    use_grobid: bool = False,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[Finding], dict[str, Any]]:
    """Run configured aspect groups plus an optional refine pass."""
    say = on_status or (lambda _msg: None)
    model = cfg.llm_model
    timeout = advanced_timeout_s(cfg)
    deadline = time.monotonic() + timeout
    item_key = item.key if item is not None else ""
    chunks, chunk_meta = paper_chunks(
        cfg,
        doc,
        use_grobid=use_grobid,
        pdf_path=pdf_path,
        item_key=item_key,
    )
    meta: dict[str, Any] = {
        "model": model,
        "parser": chunk_meta.get("parser") or "extract",
        "workers": chunk_meta.get("workers") or 0,
        "calls": 0,
        "rounds": 0,
    }
    if chunk_meta.get("grobid_skipped"):
        meta["grobid_skipped"] = chunk_meta["grobid_skipped"]
        say(f"GROBID skipped ({chunk_meta['grobid_skipped']}); using extract text")
    else:
        say(f"Advanced chunks via {meta['parser']} ({meta['workers']} worker(s))")
    if not chunks:
        meta["skipped"] = "empty_extract"
        return [], meta
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
    ][:20]
    title = (item.title if item is not None else "") or ""
    all_comments: list[dict[str, Any]] = []
    reviewer_rows: list[dict[str, Any]] = []
    narratives: list[str] = []
    first_sha = ""
    aspects = resolve_marg_aspects(cfg)
    meta["aspects"] = list(aspects)
    for aspect in aspects:
        say(f"Advanced {aspect} group…")
        comments, narrative, stats = _run_group(
            cfg,
            client,
            aspect=aspect,
            chunks=chunks,
            checked=checked,
            title=title,
            hay=hay,
            model=model,
            deadline=deadline,
        )
        meta["calls"] = int(meta["calls"]) + int(stats.get("calls") or 0)
        meta["rounds"] = int(meta["rounds"]) + int(stats.get("rounds") or 0)
        first_sha = first_sha or str(stats.get("prompt_sha") or "")
        row: dict[str, Any] = {
            "id": stats.get("id") or f"marg-{aspect}",
            "model": model,
            "prompt_sha": stats.get("prompt_sha") or "",
        }
        if narrative:
            row["narrative"] = narrative
            narratives.append(narrative)
        if stats.get("skipped"):
            row["skipped"] = stats["skipped"]
            if stats.get("error"):
                row["error"] = stats["error"]
        reviewer_rows.append(row)
        for c in comments:
            tagged = dict(c)
            tagged.setdefault("code", aspect)
            all_comments.append(tagged)

    excerpt = "\n\n".join(c.text for c in chunks)
    body_hay = (hay or "") + "\n" + excerpt.lower()
    refined, refine_calls = _refine(
        cfg,
        client,
        comments=all_comments,
        hay=body_hay,
        model=model,
        deadline=deadline,
        excerpt=excerpt,
    )
    meta["calls"] = int(meta["calls"]) + refine_calls
    cap = max(1, int(getattr(cfg, "critique_advanced_max_comments", 12) or 12))
    findings_out = findings_from_comments(
        refined,
        hay=body_hay,
        reviewer_id="marg",
        source="llm",
        limit=cap,
    )
    # Restore aspect reviewer id when the comment code is an aspect name.
    for f in findings_out:
        code = f.code
        if code in KNOWN_ASPECTS:
            f.extra["reviewer"] = f"marg-{code}"
        else:
            f.extra.setdefault("reviewer", "marg")
    if not findings_out and not narratives:
        meta["skipped"] = meta.get("skipped") or "empty_reply"
        if any(r.get("skipped") == "timeout" for r in reviewer_rows):
            findings_out = [
                make_finding(
                    code="llm_failed",
                    severity="info",
                    lane="suggested",
                    detail="Advanced critique lane stopped: timeout.",
                    source="llm",
                    extra={"reviewer": "marg"},
                )
            ]
        elif any(r.get("skipped") == "llm_error" for r in reviewer_rows):
            err = next(
                (r.get("error") for r in reviewer_rows if r.get("error")),
                "llm_error",
            )
            findings_out = [
                make_finding(
                    code="llm_failed",
                    severity="info",
                    lane="suggested",
                    detail=f"Advanced critique lane failed: {err}",
                    source="llm",
                    extra={"reviewer": "marg"},
                )
            ]
    meta["reviewers"] = reviewer_rows
    meta["prompt_sha"] = first_sha
    if narratives:
        meta["narrative"] = narratives[0]
    return findings_out, meta
