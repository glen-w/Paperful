"""Library-grounded (and optional search) context review lane.

Inspired by ScholarPeer (Goyal et al., arXiv:2601.22638). Paperful does not
vendor that stack or open-scholar-peer skills. Suggested lane only; no scores.
``context`` stays on the extract plus optional local RAG. ``context-web`` may
call configured OpenAlex / SearXNG with an egress notice; offline skips search.
Retrieve is three deterministic rounds (subdomain / method / temporal), then a
second pass for novelty answers only. Soundness stays extract-only.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import Config
from .peer_review import Finding, make_finding
from .peer_review_extract import ExtractedDoc
from .peer_review_llm import findings_from_comments, grounded, parse_llm_json
from .grounding import budget_slice
from .zot import Item

CONTEXT_LOG_SCHEMA = "paperful.peer_review.context.v1"
CONTEXT_LOG_NAME = "context.json"
_PASSAGES_CAP = 12_000

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

_QA_NOVELTY_QUESTIONS_SYSTEM = """You write novelty and significance questions as a skeptic.
Return JSON only:
{"questions": ["probing question", "..."]}
Rules:
- One question per distinct claim when possible. At most 6 questions.
- Do not invent literature, titles, or DOIs. No score or accept/reject.
"""

_QA_NOVELTY_ANSWERS_SYSTEM = """You answer novelty and significance questions as a skeptic.
Return JSON only:
{"pairs": [{"q": "question", "a": "answer grounded in the excerpt or passages"}]}
Rules:
- Answer only the given questions. Do not invent titles or DOIs.
- If passages are empty, say so. No score or accept/reject.
"""

_QA_SOUNDNESS_SYSTEM = """You audit technical soundness as a skeptic.
Return JSON only:
{"pairs": [{"q": "probing question", "a": "answer grounded in the excerpt"}]}
Rules:
- Scrutinize methods, evidence, and internal consistency. At most 6 pairs.
- Do not invent numbers. No score or accept/reject.
"""

_REVIEW_SYSTEM = """You synthesize a constructive manuscript peer-review from the
investigation log. Return JSON only:
{"summary": "one paragraph", "comments": [{"quote": "span from the excerpt", "detail": "actionable comment", "code": "short_code"}], "questions": ["author question"]}
Rules:
- Quotes MUST be substrings of the excerpt.
- No overall score, grade, or accept/reject.
- Do not claim plagiarism or misconduct.
- At most 8 comments and 5 questions.
"""


def context_timeout_s(cfg: Config) -> float:
    raw = float(getattr(cfg, "peer_review_context_timeout_s", 0) or 0)
    if raw > 0:
        return raw
    return max(float(cfg.llm_timeout_s or 120), 600.0)


def persist_context_log(folder: Path, log: dict[str, Any]) -> Path:
    """Write ``context.json`` beside ``pack.json``. Compact investigation only."""
    from .store import write_json

    payload = {"schema": CONTEXT_LOG_SCHEMA}
    if isinstance(log, dict):
        payload.update({k: v for k, v in log.items() if k != "schema"})
    dest = folder / CONTEXT_LOG_NAME
    write_json(dest, payload)
    return dest


def _chat(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, str]],
    timeout: float,
) -> str:
    from .peer_review_llm import chat_with_json_retry, peer_review_chat_request

    request = peer_review_chat_request(
        model=model,
        messages=messages,
        timeout_seconds=max(5.0, float(timeout)),
        temperature=0.2,
        json_mode=True,
    )
    return chat_with_json_retry(client, request)


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
    cfg: Config, query: str, *, limit: int, year_from: int | None = None
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
        works = client.search(q, limit=limit, year_from=year_from, year_to=None)
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


def _hit_key(row: dict[str, Any]) -> tuple[str, str] | None:
    doi = str(row.get("doi") or "").strip().lower()
    if doi:
        return ("doi", doi)
    item_key = str(row.get("item_key") or "").strip()
    if item_key:
        return ("key", item_key)
    title = str(row.get("title") or "").strip().lower()
    if title:
        return ("title", title)
    url = str(row.get("url") or "").strip()
    if url:
        return ("url", url)
    return None


def _merge_hits(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for rows in groups:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            key = _hit_key(row)
            if key is None or key in seen:
                continue
            seen.add(key)
            out.append(row)
    return out


def _titles(rows: list[dict[str, Any]], *, limit: int) -> list[str]:
    out: list[str] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if title:
            out.append(title[:200])
        if len(out) >= limit:
            break
    return out


def _passage_hay(excerpt_hay: str, *groups: list[dict[str, Any]]) -> str:
    bits = [excerpt_hay]
    for rows in groups:
        for row in rows:
            if not isinstance(row, dict):
                continue
            bits.append(str(row.get("title") or "").lower())
            bits.append(str(row.get("text") or "").lower()[:1200])
            bits.append(str(row.get("doi") or "").lower())
    return " ".join(b for b in bits if b)


def _round_specs(
    summary: dict[str, Any],
    *,
    title: str,
    item: Item | None,
    excerpt: str,
) -> list[dict[str, Any]]:
    claims = list(summary.get("claims") or [])
    claim_text = " ".join(str(c).strip() for c in claims[:3] if str(c).strip())
    method = str(summary.get("method") or "").strip()
    fallback = claim_text or excerpt[:400]
    subdomain = (
        " ".join(p for p in (title.strip(), claim_text) if p).strip() or fallback
    )
    method_q = method or fallback
    year = getattr(item, "year", None) if item is not None else None
    recency = str(year) if year else "recent"
    temporal = " ".join(p for p in (claim_text or method_q, recency) if p).strip()
    now_year = datetime.now(tz=timezone.utc).year
    return [
        {"id": "subdomain", "query": subdomain, "year_from": None},
        {"id": "method", "query": method_q, "year_from": None},
        {
            "id": "temporal",
            "query": temporal,
            "year_from": now_year - 2,
        },
    ]


def _compact_skip(value: str) -> str:
    return str(value or "").strip()


def _retrieve(
    cfg: Config,
    query: str,
    *,
    keys: set[str] | None,
    max_hits: int,
    search_enabled: bool,
    offline: bool,
    year_from: int | None,
    meta: dict[str, Any],
) -> dict[str, Any]:
    local, rag_skip = library_passages(cfg, query, keys=keys, k=max_hits)
    remote: list[dict[str, Any]] = []
    oa_skip = ""
    sx_skip = ""
    search_skip = ""
    backends: list[str] = []
    if not rag_skip:
        backends.append("rag")
        if "rag" not in meta["backends"]:
            meta["backends"] = list(meta["backends"]) + ["rag"]
    if search_enabled:
        if offline:
            search_skip = "offline"
        else:
            oa_rows, oa_skip = _openalex_works(
                cfg, query, limit=max_hits, year_from=year_from
            )
            if oa_skip:
                pass
            else:
                remote.extend(oa_rows)
                if "openalex" not in meta["backends"]:
                    meta["backends"] = list(meta["backends"]) + ["openalex"]
                backends.append("openalex")
            sx_rows, sx_skip = _searxng_hits(cfg, query, limit=max_hits)
            if not sx_skip:
                remote.extend(sx_rows)
                if "searxng" not in meta["backends"]:
                    meta["backends"] = list(meta["backends"]) + ["searxng"]
                backends.append("searxng")
            if not remote and (oa_skip or sx_skip):
                search_skip = oa_skip or sx_skip
    return {
        "library": local,
        "retrieved": remote,
        "backends": backends,
        "rag_skipped": _compact_skip(rag_skip),
        "openalex_skipped": _compact_skip(oa_skip),
        "searxng_skipped": _compact_skip(sx_skip),
        "search_skipped": _compact_skip(search_skip),
    }


def _compact_round(
    spec: dict[str, Any], result: dict[str, Any], *, max_hits: int
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": spec.get("id") or "",
        "query": str(spec.get("query") or "")[:400],
        "library": _titles(result.get("library") or [], limit=max_hits),
        "retrieved": _titles(result.get("retrieved") or [], limit=max_hits),
    }
    if spec.get("year_from") is not None:
        row["year_from"] = spec["year_from"]
    for key in (
        "rag_skipped",
        "openalex_skipped",
        "searxng_skipped",
        "search_skipped",
    ):
        if result.get(key):
            row[key] = result[key]
    return row


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
    """Summary → 3-round retrieve → historian → scout → novelty Q/A → soundness → synthesis."""
    say = on_status or (lambda _msg: None)
    model = cfg.llm_model
    lane_id = "context-web" if search_enabled else "context"
    timeout = context_timeout_s(cfg)
    deadline = time.monotonic() + timeout
    excerpt = budget_slice(doc.text, cfg.peer_review_max_context_chars)
    max_comments = max(1, int(getattr(cfg, "peer_review_context_max_comments", 12) or 12))
    max_hits = max(1, int(getattr(cfg, "peer_review_context_max_hits", 8) or 8))
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

    def timed_out() -> bool:
        if time.monotonic() >= deadline:
            meta["skipped"] = meta.get("skipped") or "timeout"
            return True
        if _remaining(deadline) < 5.0:
            meta["skipped"] = meta.get("skipped") or "timeout"
            return True
        return False

    def one_call(system: str, user: str, label: str) -> dict[str, Any] | None:
        if timed_out():
            say(f"{label} skipped (timeout)")
            return None
        remain = _remaining(deadline)
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

    if search_enabled and offline:
        meta["search_skipped"] = "offline"
        say("Context-web search skipped (offline)")

    local_hits: list[dict[str, Any]] = []
    remote: list[dict[str, Any]] = []
    round_rows: list[dict[str, Any]] = []
    rag_skips: list[str] = []
    for i, spec in enumerate(
        _round_specs(summary, title=title, item=item, excerpt=excerpt), start=1
    ):
        rid = str(spec.get("id") or f"round{i}")
        if timed_out():
            say(f"Context retrieve round {i}/3 ({rid}) skipped (timeout)")
            round_rows.append(
                {
                    "id": rid,
                    "query": str(spec.get("query") or "")[:400],
                    "library": [],
                    "retrieved": [],
                    "skipped": "timeout",
                }
            )
            continue
        say(f"Context retrieve round {i}/3 ({rid})…")
        year_from = spec.get("year_from") if search_enabled and not offline else None
        result = _retrieve(
            cfg,
            str(spec.get("query") or ""),
            keys=keys,
            max_hits=max_hits,
            search_enabled=search_enabled,
            offline=offline,
            year_from=year_from if isinstance(year_from, int) else None,
            meta=meta,
        )
        local_hits = _merge_hits(local_hits, result.get("library") or [])
        remote = _merge_hits(remote, result.get("retrieved") or [])
        if result.get("rag_skipped"):
            rag_skips.append(str(result["rag_skipped"]))
        compact = _compact_round(spec, result, max_hits=max_hits)
        round_rows.append(compact)
        n_lib = len(result.get("library") or [])
        n_rem = len(result.get("retrieved") or [])
        say(f"Context retrieve round {i}/3 ({rid}) {n_lib} library, {n_rem} retrieved")

    if not local_hits and rag_skips:
        meta["rag_skipped"] = rag_skips[0]
        say(f"Context library retrieve skipped ({rag_skips[0]})")
    elif local_hits:
        say(f"Context library retrieve ({len(local_hits)} unique hit(s))")

    if search_enabled and not offline and not remote:
        oa_bits = [
            r.get("openalex_skipped") for r in round_rows if r.get("openalex_skipped")
        ]
        sx_bits = [
            r.get("searxng_skipped") for r in round_rows if r.get("searxng_skipped")
        ]
        if oa_bits or sx_bits:
            meta.setdefault("search_skipped", oa_bits[0] if oa_bits else sx_bits[0])
        if oa_bits:
            meta.setdefault("openalex_skipped", oa_bits[0])
        if sx_bits:
            meta.setdefault("searxng_skipped", sx_bits[0])

    passages_blob = json.dumps(
        {"library": local_hits[:max_hits], "retrieved": remote[:max_hits]},
        ensure_ascii=False,
        default=str,
    )[:_PASSAGES_CAP]
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
    if not isinstance(omitted, list):
        omitted = []

    novelty_qs_raw = one_call(
        _QA_NOVELTY_QUESTIONS_SYSTEM,
        f"Excerpt:\n{excerpt}\n\nSummary:\n{summary_blob}\n\nNarrative:\n{narrative}\n\n"
        f"Omitted:\n{json.dumps(omitted, ensure_ascii=False, default=str)[:4000]}",
        "Context novelty questions",
    )
    novelty_questions = [
        str(q).strip()
        for q in ((novelty_qs_raw or {}).get("questions") or [])
        if str(q).strip()
    ][:6]

    novelty_local: list[dict[str, Any]] = []
    novelty_remote: list[dict[str, Any]] = []
    novelty_search_rows: list[dict[str, Any]] = []
    for nq in novelty_questions:
        if timed_out():
            novelty_search_rows.append(
                {
                    "query": nq[:400],
                    "library": [],
                    "retrieved": [],
                    "skipped": "timeout",
                }
            )
            continue
        say("Context novelty search…")
        result = _retrieve(
            cfg,
            nq,
            keys=keys,
            max_hits=max_hits,
            search_enabled=search_enabled,
            offline=offline,
            year_from=None,
            meta=meta,
        )
        novelty_local = _merge_hits(novelty_local, result.get("library") or [])
        novelty_remote = _merge_hits(novelty_remote, result.get("retrieved") or [])
        novelty_search_rows.append(
            {
                "query": nq[:400],
                "library": _titles(result.get("library") or [], limit=max_hits),
                "retrieved": _titles(result.get("retrieved") or [], limit=max_hits),
                **{
                    k: result[k]
                    for k in (
                        "rag_skipped",
                        "openalex_skipped",
                        "searxng_skipped",
                        "search_skipped",
                    )
                    if result.get(k)
                },
            }
        )

    answer_local = _merge_hits(local_hits, novelty_local)
    answer_remote = _merge_hits(remote, novelty_remote)
    novelty_blob = json.dumps(
        {"library": answer_local[:max_hits], "retrieved": answer_remote[:max_hits]},
        ensure_ascii=False,
        default=str,
    )[:_PASSAGES_CAP]
    novelty_pairs: list[Any] = []
    if novelty_questions:
        novelty_ans = one_call(
            _QA_NOVELTY_ANSWERS_SYSTEM,
            "Excerpt:\n"
            + excerpt
            + "\n\nQuestions:\n"
            + json.dumps(novelty_questions, ensure_ascii=False)
            + "\n\nPassages:\n"
            + novelty_blob,
            "Context novelty answers",
        )
        raw_pairs = (novelty_ans or {}).get("pairs") if novelty_ans else []
        if isinstance(raw_pairs, list):
            novelty_pairs = raw_pairs

    soundness = one_call(
        _QA_SOUNDNESS_SYSTEM,
        f"Excerpt:\n{excerpt}\n\nSummary:\n{summary_blob}\n\nChecked findings:\n"
        + json.dumps(checked, ensure_ascii=False),
        "Context Q&A soundness",
    )
    soundness_pairs = (soundness or {}).get("pairs") if soundness else []
    if not isinstance(soundness_pairs, list):
        soundness_pairs = []

    omitted_compact: list[dict[str, str]] = []
    for row in omitted:
        if not isinstance(row, dict):
            continue
        omitted_compact.append(
            {
                "title": str(row.get("title") or "")[:200],
                "detail": str(row.get("detail") or "")[:500],
            }
        )

    def _pair_rows(raw: list[Any]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for pair in raw:
            if not isinstance(pair, dict):
                continue
            q = str(pair.get("q") or "").strip()[:400]
            a = str(pair.get("a") or "").strip()[:500]
            if q or a:
                rows.append({"q": q, "a": a})
        return rows

    investigation: dict[str, Any] = {
        "summary": summary,
        "rounds": round_rows,
        "novelty_search": {
            "queries": [q[:400] for q in novelty_questions],
            "library": _titles(novelty_local, limit=max_hits),
            "retrieved": _titles(novelty_remote, limit=max_hits),
            "hits": novelty_search_rows,
        },
        "narrative": narrative[:4000],
        "omitted": omitted_compact,
        "novelty": _pair_rows(novelty_pairs),
        "soundness": _pair_rows(soundness_pairs),
    }
    log = {
        "summary": summary,
        "narrative": narrative,
        "omitted": omitted,
        "novelty": investigation["novelty"],
        "soundness": investigation["soundness"],
    }
    review = one_call(
        _REVIEW_SYSTEM,
        f"Excerpt:\n{excerpt}\n\nInvestigation:\n"
        + json.dumps(log, ensure_ascii=False, default=str)[:_PASSAGES_CAP],
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
    novelty_hay = _passage_hay(hay, answer_local, answer_remote)
    for pair in investigation["novelty"]:
        detail = str(pair.get("a") or pair.get("q") or "").strip()
        if not detail or not grounded(detail, novelty_hay):
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
    if len(extra) < max_comments:
        for pair in investigation["soundness"]:
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
    for row in omitted_compact:
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
    if review_summary:
        investigation["review"] = review_summary[:4000]
    if narrative:
        meta["narrative"] = narrative[:4000]
        investigation["narrative"] = narrative[:4000]
    meta["investigation"] = investigation
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
