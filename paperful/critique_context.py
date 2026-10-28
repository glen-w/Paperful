"""Library-grounded (and optional search) context review lane.

Inspired by ScholarPeer (Goyal et al., arXiv:2601.22638). Paperful does not
vendor that stack or open-scholar-peer skills. Suggested lane only; no scores.
``context`` stays on the extract plus optional local RAG. ``context-web`` may
call configured OpenAlex / SearXNG with an egress notice; offline skips search.
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

_SUMMARY_SYSTEM = """You write a structured summary of a manuscript excerpt.
Return JSON only:
{"claims": ["core claim", "..."], "method": "short method sketch", "evidence": ["reported result", "..."]}
Rules:
- Use only the excerpt. Do not invent citations or numbers.
- No score, grade, or accept/reject.
- At most 6 claims and 6 evidence rows.
"""

_HISTORIAN_SYSTEM = """You are a sub-domain historian for one manuscript.
Given the structured summary and library (or retrieved) passages, write a
chronological domain narrative. Return JSON only:
{"narrative": "one or two paragraphs placing the claims in that corpus"}
Rules:
- Ground the narrative in the passages and the excerpt. Do not invent papers.
- If passages are empty, say the local corpus had no hits.
- No score, grade, or accept/reject.
"""

_SCOUT_SYSTEM = """You are a baseline scout. Hunt for omitted comparisons.
Return JSON only:
{"omitted": [{"title": "work or dataset name from the passages", "detail": "why the manuscript should compare"}]}
Rules:
- Prefer named works from the passages. Do not invent venues or DOIs.
- If nothing is omitted, return {"omitted": []}.
- No score, grade, or accept/reject. At most 8 rows.
"""

_QA_NOVELTY_SYSTEM = """You audit novelty and significance as a skeptic.
Return JSON only:
{"pairs": [{"q": "probing question", "a": "answer grounded in the excerpt or passages"}]}
Rules:
- One pair per distinct claim when possible. At most 6 pairs.
- Answers must not invent literature. No score or accept/reject.
"""

_QA_SOUNDNESS_SYSTEM = """You audit technical soundness as a skeptic.
Return JSON only:
{"pairs": [{"q": "probing question", "a": "answer grounded in the excerpt"}]}
Rules:
- Scrutinize methods, evidence, and internal consistency. At most 6 pairs.
- Do not invent numbers. No score or accept/reject.
"""

_REVIEW_SYSTEM = """You synthesize a constructive manuscript critique from the
investigation log. Return JSON only:
{"summary": "one paragraph", "comments": [{"quote": "span from the excerpt", "detail": "actionable comment", "code": "short_code"}], "questions": ["author question"]}
Rules:
- Quotes MUST be substrings of the excerpt.
- No overall score, grade, or accept/reject.
- Do not claim plagiarism or misconduct.
- At most 8 comments and 5 questions.
"""


def context_timeout_s(cfg: Config) -> float:
    raw = float(getattr(cfg, "critique_context_timeout_s", 0) or 0)
    if raw > 0:
        return raw
    return max(float(cfg.llm_timeout_s or 120), 600.0)


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


def library_passages(
    cfg: Config,
    query: str,
    *,
    keys: set[str] | None,
    k: int,
) -> tuple[list[dict[str, Any]], str]:
    """Local RAG hits for the historian / scout. Fail soft when the index is missing."""
    q = (query or "").strip()
    if not q:
        return [], "empty_query"
    try:
        from .rag.index import IndexMismatch, IndexMissing, RagUnavailable
        from .rag.retrieve import search
    except Exception:
        return [], "rag_unavailable"
    try:
        hits = search(cfg, q, k=k, keys=keys)
    except (RagUnavailable, IndexMissing, IndexMismatch) as exc:
        return [], type(exc).__name__
    except Exception:
        return [], "rag_error"
    rows: list[dict[str, Any]] = []
    for hit in hits:
        text = str(getattr(hit, "text", "") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "item_key": getattr(hit, "item_key", "") or "",
                "title": getattr(hit, "title", "") or "",
                "year": getattr(hit, "year", None),
                "text": text[:1200],
            }
        )
    return rows, ""


def _openalex_works(
    cfg: Config, query: str, *, limit: int
) -> tuple[list[dict[str, Any]], str]:
    q = (query or "").strip()
    if not q:
        return [], "empty_query"
    try:
        from .snowball.openalex import OpenAlexClient
    except Exception:
        return [], "openalex_unavailable"
    try:
        client = OpenAlexClient(email=cfg.email or "", sleep_s=0.0)
        works = client.search(q, limit=limit, year_from=None, year_to=None)
    except Exception as exc:
        return [], str(exc)[:200] or "openalex_error"
    rows: list[dict[str, Any]] = []
    for work in works or []:
        if not isinstance(work, dict):
            continue
        title = str(work.get("display_name") or "").strip()
        if not title:
            continue
        rows.append(
            {
                "title": title,
                "year": work.get("publication_year"),
                "doi": str(work.get("doi") or "").strip(),
                "source": "openalex",
            }
        )
        if len(rows) >= limit:
            break
    return rows, ""


def _searxng_hits(
    cfg: Config, query: str, *, limit: int
) -> tuple[list[dict[str, Any]], str]:
    q = (query or "").strip()
    if not q:
        return [], "empty_query"
    try:
        from .snowball.searxng import search_query, searxng_base_url
    except Exception:
        return [], "searxng_unavailable"
    if not searxng_base_url(cfg):
        return [], "searxng_unset"
    try:
        hits = search_query(cfg, q, limit=limit)
    except Exception as exc:
        return [], str(exc)[:200] or "searxng_error"
    rows: list[dict[str, Any]] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        title = str(hit.get("title") or "").strip()
        url = str(hit.get("url") or "").strip()
        if not title and not url:
            continue
        rows.append({"title": title or url, "url": url, "source": "searxng"})
        if len(rows) >= limit:
            break
    return rows, ""


def _remaining(deadline: float) -> float:
    return max(1.0, deadline - time.monotonic())


def _parse_summary(raw: str) -> dict[str, Any]:
    data = parse_llm_json(raw) or {}
    claims = [str(c).strip() for c in (data.get("claims") or []) if str(c).strip()]
    evidence = [str(e).strip() for e in (data.get("evidence") or []) if str(e).strip()]
    method = str(data.get("method") or "").strip()
    return {
        "claims": claims[:6],
        "method": method[:800],
        "evidence": evidence[:6],
    }


def suggested_from_context(
    cfg: Config,
    doc: ExtractedDoc,
    findings: list[Finding],
    *,
    item: Item | None,
    client: Any,
    hay: str,
    search_enabled: bool = False,
    offline: bool = False,
    scope_items: list[Item] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[Finding], dict[str, Any]]:
    """Summary → historian → scout → Q&A → synthesis. Suggested lane only."""
    say = on_status or (lambda _msg: None)
    model = cfg.llm_model
    lane_id = "context-web" if search_enabled else "context"
    timeout = context_timeout_s(cfg)
    deadline = time.monotonic() + timeout
    excerpt = budget_slice(doc.text, cfg.critique_max_context_chars)
    max_comments = max(1, int(getattr(cfg, "critique_context_max_comments", 12) or 12))
    max_hits = max(1, int(getattr(cfg, "critique_context_max_hits", 8) or 8))
    meta: dict[str, Any] = {
        "id": lane_id,
        "model": model,
        "search_enabled": bool(search_enabled),
        "calls": 0,
        "backends": [],
    }
    if not excerpt.strip():
        meta["skipped"] = "empty_extract"
        return [], meta

    keys: set[str] | None = None
    if scope_items:
        keys = {it.key for it in scope_items if getattr(it, "key", None)}
        if item is not None:
            keys.discard(item.key)
        if not keys:
            keys = None

    title = (item.title if item is not None else "") or ""
    checked = [
        {
            "code": f.code,
            "severity": f.severity,
            "detail": f.detail,
        }
        for f in findings
        if f.lane == "checked" and not f.dismissed
    ][:20]

    def one_call(system: str, user: str, label: str) -> dict[str, Any] | None:
        if time.monotonic() >= deadline:
            meta["skipped"] = meta.get("skipped") or "timeout"
            say(f"{label} skipped (timeout)")
            return None
        remain = _remaining(deadline)
        if remain < 5.0:
            meta["skipped"] = meta.get("skipped") or "timeout"
            say(f"{label} skipped (timeout)")
            return None
        say(f"{label}…")
        meta["calls"] = int(meta["calls"]) + 1
        try:
            raw = _chat(
                client,
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                timeout=remain,
            )
        except Exception as exc:
            meta["skipped"] = meta.get("skipped") or "llm_error"
            meta["error"] = str(exc)
            say(f"{label} failed ({exc})")
            return None
        return parse_llm_json(raw)

    summary_user = f"Title: {title}\n\nExcerpt:\n{excerpt}"
    try:
        summary_raw = _chat(
            client,
            model=model,
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": summary_user},
            ],
            timeout=_remaining(deadline),
        )
        meta["calls"] = int(meta["calls"]) + 1
    except Exception as exc:
        meta["skipped"] = "llm_error"
        meta["error"] = str(exc)
        return [], meta
    summary = _parse_summary(summary_raw)
    meta["prompt_sha"] = sha256(_SUMMARY_SYSTEM.encode("utf-8")).hexdigest()[:12]
    query_bits = list(summary.get("claims") or [])[:3]
    if summary.get("method"):
        query_bits.append(str(summary["method"]))
    query = " ".join(query_bits) or excerpt[:400]

    local_hits, rag_skip = library_passages(cfg, query, keys=keys, k=max_hits)
    if rag_skip:
        meta["rag_skipped"] = rag_skip
        say(f"Context library retrieve skipped ({rag_skip})")
    else:
        meta["backends"] = list(meta["backends"]) + ["rag"]
        say(f"Context library retrieve ({len(local_hits)} hit(s))")

    remote: list[dict[str, Any]] = []
    if search_enabled:
        if offline:
            meta["search_skipped"] = "offline"
            say("Context-web search skipped (offline)")
        else:
            oa_rows, oa_skip = _openalex_works(cfg, query, limit=max_hits)
            if oa_skip:
                meta["openalex_skipped"] = oa_skip
            else:
                remote.extend(oa_rows)
                meta["backends"] = list(meta["backends"]) + ["openalex"]
            sx_rows, sx_skip = _searxng_hits(cfg, query, limit=max_hits)
            if sx_skip:
                meta["searxng_skipped"] = sx_skip
            else:
                remote.extend(sx_rows)
                meta["backends"] = list(meta["backends"]) + ["searxng"]
            if not remote and (oa_skip or sx_skip):
                meta.setdefault("search_skipped", oa_skip or sx_skip)

    passages_blob = json.dumps(
        {"library": local_hits[:max_hits], "retrieved": remote[:max_hits]},
        ensure_ascii=False,
        default=str,
    )[:12_000]
    summary_blob = json.dumps(summary, ensure_ascii=False)

    hist = one_call(
        _HISTORIAN_SYSTEM,
        f"Summary:\n{summary_blob}\n\nPassages:\n{passages_blob}",
        "Context historian",
    )
    narrative = ""
    if hist:
        narrative = str(hist.get("narrative") or "").strip()

    scout = one_call(
        _SCOUT_SYSTEM,
        f"Summary:\n{summary_blob}\n\nPassages:\n{passages_blob}",
        "Context baseline scout",
    )
    omitted = scout.get("omitted") if isinstance(scout, dict) else []

    novelty = one_call(
        _QA_NOVELTY_SYSTEM,
        f"Excerpt:\n{excerpt}\n\nSummary:\n{summary_blob}\n\nPassages:\n{passages_blob}",
        "Context Q&A novelty",
    )
    soundness = one_call(
        _QA_SOUNDNESS_SYSTEM,
        f"Excerpt:\n{excerpt}\n\nSummary:\n{summary_blob}\n\nChecked findings:\n"
        + json.dumps(checked, ensure_ascii=False),
        "Context Q&A soundness",
    )
    log = {
        "summary": summary,
        "narrative": narrative,
        "omitted": omitted,
        "novelty": (novelty or {}).get("pairs") if novelty else [],
        "soundness": (soundness or {}).get("pairs") if soundness else [],
    }
    review = one_call(
        _REVIEW_SYSTEM,
        f"Excerpt:\n{excerpt}\n\nInvestigation:\n"
        + json.dumps(log, ensure_ascii=False, default=str)[:12_000],
        "Context review",
    )
    extra: list[Finding] = []
    comments = (review or {}).get("comments") if review else []
    extra.extend(
        findings_from_comments(
            comments,
            hay=hay,
            reviewer_id=lane_id,
            source="llm",
            limit=max_comments,
        )
    )
    for pair in list(log.get("novelty") or []) + list(log.get("soundness") or []):
        if not isinstance(pair, dict):
            continue
        detail = str(pair.get("a") or pair.get("q") or "").strip()
        if not detail or not grounded(detail, hay):
            continue
        extra.append(
            make_finding(
                code="context_qa",
                severity="info",
                lane="suggested",
                detail=detail[:500],
                source="llm",
                extra={"reviewer": lane_id},
            )
        )
        if len(extra) >= max_comments:
            extra = extra[:max_comments]
            break
    for row in omitted or []:
        if not isinstance(row, dict):
            continue
        detail = str(row.get("detail") or "").strip()
        if not detail:
            continue
        extra.append(
            make_finding(
                code="context_omitted",
                severity="info",
                lane="suggested",
                detail=detail[:500],
                quote=str(row.get("title") or "")[:200],
                source="llm",
                extra={"reviewer": lane_id},
            )
        )
        if len(extra) >= max_comments:
            extra = extra[:max_comments]
            break
    review_summary = str((review or {}).get("summary") or "").strip()
    if review_summary and grounded(review_summary, hay):
        narrative = narrative or review_summary
    if narrative:
        meta["narrative"] = narrative[:4000]
    reviewer_row: dict[str, Any] = {
        "id": lane_id,
        "model": model,
        "prompt_sha": meta.get("prompt_sha") or "",
    }
    if narrative:
        reviewer_row["narrative"] = narrative[:4000]
    if meta.get("skipped"):
        reviewer_row["skipped"] = meta["skipped"]
    meta["reviewers"] = [reviewer_row]
    if not extra and not narrative:
        meta.setdefault("skipped", "empty_reply")
    return extra[:max_comments], meta
