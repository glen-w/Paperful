"""Intra-document claim ledger. Suggested lane only. No scores.

Extracts core claims, then binds each to methods/results/limitations spans
with deterministic content-word overlap. Status is support *in this extract*,
never a truth verdict. An optional second JSON turn may only downgrade.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import Config
from .critique import Finding, make_finding
from .critique_extract import ExtractedDoc
from .critique_llm import grounded, parse_llm_json
from .critique_units import (
    SOURCE_FAMILIES,
    SUPPORT_FAMILIES,
    Unit,
    family_of,
    paper_units,
    units_for_families,
)
from .grounding import budget_slice
from .zot import Item

_STOP = frozenset(
    {
        "that",
        "this",
        "with",
        "from",
        "were",
        "been",
        "have",
        "they",
        "them",
        "their",
        "which",
        "when",
        "what",
        "where",
        "there",
        "these",
        "those",
        "into",
        "over",
        "under",
        "than",
        "then",
        "also",
        "only",
        "more",
        "most",
        "such",
        "using",
        "used",
        "between",
        "among",
        "about",
        "after",
        "before",
        "because",
        "while",
        "paper",
        "study",
        "results",
        "method",
        "methods",
        "however",
        "therefore",
    }
)
_STATUS_RANK = {"supported": 0, "thin": 1, "unsupported": 2}

_EXTRACT_SYSTEM = """You extract core claims from a manuscript excerpt.
Return JSON only:
{"claims": ["core claim", "..."], "method": "short method sketch"}
Rules:
- Use only the excerpt. Do not invent citations, numbers, or methods.
- At most the asked maximum of claims.
- Prefer abstract, results, and conclusion wording.
- No score, grade, or accept/reject.
"""

_DOWNGRADE_SYSTEM = """You may only downgrade claim-support labels already assigned.
Return JSON only:
{"adjustments": [{"id": "c1", "status": "thin or unsupported", "detail": "one line"}]}
Rules:
- status may only be thin or unsupported.
- Do not invent a supporting span or raise a label to supported.
- Leave a claim unchanged by omitting it.
- Quotes and numbers must come from the excerpt.
- No score, grade, or accept/reject.
"""


def claims_timeout_s(cfg: Config) -> float:
    raw = float(getattr(cfg, "critique_claims_timeout_s", 0) or 0)
    if raw > 0:
        return raw
    return float(cfg.llm_timeout_s or 120)


def content_words(text: str) -> set[str]:
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", (text or "").lower()) if w]
    return {w for w in words if w not in _STOP}


def overlap_score(claim: str, unit: Unit) -> float:
    left = content_words(claim)
    right = content_words(unit.text)
    if not left:
        return 0.0
    return len(left & right) / len(left)


def bind_claim(claim: str, support: list[Unit]) -> dict[str, Any]:
    """Deterministic support label against methods/results/limitations units."""
    best: Unit | None = None
    best_score = 0.0
    best_shared = 0
    left = content_words(claim)
    for unit in support:
        score = overlap_score(claim, unit)
        shared = len(left & content_words(unit.text))
        if score > best_score or (score == best_score and shared > best_shared):
            best_score = score
            best_shared = shared
            best = unit
    if best is None or best_shared == 0:
        return {
            "status": "unsupported",
            "support_quote": "",
            "loc": "",
            "score": 0.0,
        }
    quote = _best_quote(claim, best)
    if best_score >= 0.35 and best_shared >= 3:
        status = "supported"
    elif best_score >= 0.15 and best_shared >= 2:
        status = "thin"
    else:
        status = "unsupported"
    return {
        "status": status,
        "support_quote": quote,
        "loc": best.loc,
        "score": round(best_score, 3),
    }


def _best_quote(claim: str, unit: Unit) -> str:
    words = content_words(claim)
    best = ""
    best_n = 0
    for sent in re.split(r"(?<=[.!?])\s+", unit.text or ""):
        n = len(content_words(sent) & words)
        if n > best_n:
            best_n = n
            best = sent.strip()
    raw = best or (unit.text or "").strip()
    return re.sub(r"\s+", " ", raw)[:200]


def _join_units(units: list[Unit], *, limit: int) -> str:
    parts: list[str] = []
    size = 0
    for unit in units:
        chunk = unit.text.strip()
        if not chunk:
            continue
        if size and size + len(chunk) > limit:
            break
        parts.append(chunk)
        size += len(chunk)
    return "\n\n".join(parts)


def suggested_from_claims(
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
    """Extract claims and bind them to intra-doc support spans."""
    say = on_status or (lambda _msg: None)
    model = cfg.llm_model
    cap = max(1, int(getattr(cfg, "critique_claims_max", 8) or 8))
    comment_cap = max(1, int(getattr(cfg, "critique_claims_max_comments", 16) or 16))
    timeout_s = claims_timeout_s(cfg)
    item_key = item.key if item is not None else ""
    units, unit_meta = paper_units(
        cfg,
        doc,
        use_grobid=use_grobid,
        pdf_path=pdf_path,
        item_key=item_key,
    )
    source = units_for_families(units, SOURCE_FAMILIES, cfg)
    support = units_for_families(units, SUPPORT_FAMILIES, cfg)
    excerpt = _join_units(source, limit=int(cfg.critique_max_context_chars or 24_000))
    if not excerpt.strip():
        excerpt = budget_slice(doc.text, cfg.critique_max_context_chars)
    if not support:
        support = [
            u
            for u in units
            if family_of(u, cfg) not in {"abstract", "references", "acknowledgements"}
        ]
    meta: dict[str, Any] = {
        "id": "claims",
        "model": model,
        "calls": 0,
        "parser": unit_meta.get("parser") or "extract",
    }
    if unit_meta.get("grobid_skipped"):
        meta["grobid_skipped"] = unit_meta["grobid_skipped"]
    if not excerpt.strip():
        meta["skipped"] = "empty_extract"
        meta["reviewers"] = [
            {"id": "claims", "model": model, "skipped": "empty_extract"}
        ]
        meta["ledger"] = []
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
    ][:20]
    user = (
        f"Title: {title}\nMax claims: {cap}\n\nExcerpt:\n{excerpt}\n\n"
        f"Checked findings:\n{json.dumps(checked, ensure_ascii=False)}"
    )
    prompt_sha = sha256((_EXTRACT_SYSTEM + user[:2000]).encode("utf-8")).hexdigest()[:12]
    meta["prompt_sha"] = prompt_sha
    say("Claims lane…")
    from .llm.client import ChatRequest, chat

    request = ChatRequest(
        model=model,
        messages=(
            {"role": "system", "content": _EXTRACT_SYSTEM},
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
        meta["ledger"] = []
        meta["reviewers"] = [
            {
                "id": "claims",
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
                detail=f"Claims lane failed: {exc}",
                source="llm",
                extra={"reviewer": "claims"},
            )
        ], meta
    meta["calls"] = 1
    data = parse_llm_json(raw) or {}
    hay_bind = (hay or excerpt.lower()).lower()
    raw_claims = []
    for c in data.get("claims") or []:
        text = str(c).strip()
        if not text:
            continue
        if not grounded(text, hay_bind):
            continue
        raw_claims.append(text)
        if len(raw_claims) >= cap:
            break
    method = str(data.get("method") or "").strip()
    if method and grounded(method, hay or excerpt.lower()):
        meta["method"] = method[:400]

    ledger: list[dict[str, Any]] = []
    for i, text in enumerate(raw_claims, 1):
        bound = bind_claim(text, support)
        row = {
            "id": f"c{i}",
            "text": text[:400],
            "status": bound["status"],
            "support_quote": bound["support_quote"],
            "loc": bound["loc"],
        }
        ledger.append(row)

    if ledger:
        adj_user = (
            f"Excerpt:\n{excerpt[:6000]}\n\nClaims:\n"
            + json.dumps(ledger, ensure_ascii=False)
        )
        adj_req = ChatRequest(
            model=model,
            messages=(
                {"role": "system", "content": _DOWNGRADE_SYSTEM},
                {"role": "user", "content": adj_user},
            ),
            timeout_seconds=timeout_s,
            temperature=0.2,
        )
        try:
            adj_raw = chat(client, adj_req)
            meta["calls"] = int(meta["calls"]) + 1
            adj = parse_llm_json(adj_raw) or {}
            by_id = {row["id"]: row for row in ledger}
            for item_row in adj.get("adjustments") or []:
                if not isinstance(item_row, dict):
                    continue
                cid = str(item_row.get("id") or "").strip()
                new_status = str(item_row.get("status") or "").strip().lower()
                if cid not in by_id or new_status not in {"thin", "unsupported"}:
                    continue
                current = by_id[cid]["status"]
                if _STATUS_RANK[new_status] <= _STATUS_RANK.get(current, 0):
                    continue
                by_id[cid]["status"] = new_status
                detail = str(item_row.get("detail") or "").strip()
                if detail and grounded(detail, hay or excerpt.lower()):
                    by_id[cid]["detail"] = detail[:400]
        except Exception:
            pass

    extra: list[Finding] = []
    for row in ledger:
        status = row["status"]
        if status == "supported":
            continue
        code = (
            "claim_thin" if status == "thin" else "claim_unsupported_in_text"
        )
        claim = row["text"]
        quote = row.get("support_quote") or claim
        if status == "thin":
            detail = (
                f"Claim is thinly supported in this extract: {claim}"
            )
        else:
            detail = f"Claim is not supported in this extract: {claim}"
        extra.append(
            make_finding(
                code=code,
                severity="info",
                lane="suggested",
                loc=str(row.get("loc") or ""),
                quote=quote,
                detail=detail[:500],
                source="claims",
                extra={"reviewer": "claims", "claim_id": row["id"]},
            )
        )
        if len(extra) >= comment_cap:
            break

    dt = time.perf_counter() - t0
    bits = [f"{dt:.0f}s", f"{len(ledger)} claim(s)"]
    if extra:
        bits.append(f"{len(extra)} gap(s)")
    say(f"Claims lane done ({', '.join(bits)})")
    reviewer_row: dict[str, Any] = {
        "id": "claims",
        "model": model,
        "prompt_sha": prompt_sha,
    }
    if not ledger:
        meta["skipped"] = "empty_reply"
        reviewer_row["skipped"] = "empty_reply"
    meta["ledger"] = ledger
    meta["reviewers"] = [reviewer_row]
    return extra, meta
