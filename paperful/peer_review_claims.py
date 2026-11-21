"""Intra-document claim ledger. Suggested lane only. No scores.

Extracts core claims, then binds each to methods/results/limitations spans
with deterministic content-word overlap. Status is support *in this extract*,
never a truth verdict. An optional second JSON turn may only downgrade.

When a library scope is loaded, an extra pass attaches locators from held
cited PDFs already in ``state/rag/text``. Missing text is a skip, never a
guessed cite. That pass does not fetch PDFs from the web.
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
SUPPORTED_MIN_SCORE = 0.35
SUPPORTED_MIN_SHARED = 3
THIN_MIN_SCORE = 0.15
THIN_MIN_SHARED = 2
_WINDOW_CHARS = 400
_NUM_HEAD = re.compile(r"(?m)^\s*(?:\[(\d+)\]|(\d+)\.)\s+")
_RANGE_SPLIT = re.compile(r"[-–]")

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
    status = label_overlap(best_score, best_shared)
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


def label_overlap(score: float, shared: int) -> str:
    if score >= SUPPORTED_MIN_SCORE and shared >= SUPPORTED_MIN_SHARED:
        return "supported"
    if score >= THIN_MIN_SCORE and shared >= THIN_MIN_SHARED:
        return "thin"
    return "unsupported"


def quote_in_text(quote: str, text: str) -> bool:
    needle = re.sub(r"\s+", " ", (quote or "").strip()).lower()
    hay = re.sub(r"\s+", " ", (text or "").strip()).lower()
    return bool(needle) and needle in hay


def claim_window(doc_text: str, claim: str, *, radius: int = _WINDOW_CHARS) -> str:
    hay = doc_text or ""
    needle = (claim or "").strip()
    if not needle:
        return ""
    idx = hay.lower().find(needle[:120].lower())
    if idx < 0:
        idx = hay.lower().find(needle[:40].lower()) if len(needle) > 40 else -1
    if idx < 0:
        return needle
    start = max(0, idx - radius)
    end = min(len(hay), idx + len(needle) + radius)
    return hay[start:end]


def numbered_bibliography(text: str) -> dict[int, dict[str, Any]]:
    from .snowball.bibliography import dehyphenate, parse_bibliography_entries

    entries = parse_bibliography_entries(text)
    if not entries:
        return {}
    _body, biblio = _split_body_biblio_safe(text)
    hay = dehyphenate(biblio or "")
    nums = [
        int(m.group(1) or m.group(2))
        for m in _NUM_HEAD.finditer(hay)
        if (m.group(1) or m.group(2))
    ]
    out: dict[int, dict[str, Any]] = {}
    if len(nums) == len(entries):
        for n, entry in zip(nums, entries, strict=True):
            out[n] = entry
        return out
    for i, entry in enumerate(entries, start=1):
        out[i] = entry
    return out


def _split_body_biblio_safe(text: str) -> tuple[str, str]:
    from .critique_checks._common import _split_body_biblio

    return _split_body_biblio(text)


def cites_in_window(window: str) -> list[dict[str, Any]]:
    from .critique_checks._common import _AUTHOR_YEAR, _NUM_CITE

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _NUM_CITE.finditer(window or ""):
        for part in re.split(r"[,]", m.group(1)):
            part = part.strip()
            if not part:
                continue
            if _RANGE_SPLIT.search(part):
                a, b = _RANGE_SPLIT.split(part, maxsplit=1)
                try:
                    lo, hi = int(a.strip()), int(b.strip())
                except ValueError:
                    continue
                for n in range(lo, hi + 1):
                    token = f"n:{n}"
                    if token in seen:
                        continue
                    seen.add(token)
                    found.append({"kind": "num", "n": n})
            else:
                try:
                    n = int(part)
                except ValueError:
                    continue
                token = f"n:{n}"
                if token in seen:
                    continue
                seen.add(token)
                found.append({"kind": "num", "n": n})
    for m in _AUTHOR_YEAR.finditer(window or ""):
        surname = m.group(1).split()[0]
        year = m.group(2)[:4]
        token = f"ay:{surname.lower()}:{year}"
        if token in seen:
            continue
        seen.add(token)
        found.append({"kind": "author_year", "surname": surname, "year": year})
    return found


def resolve_cite(
    cite: dict[str, Any],
    by_num: dict[int, dict[str, Any]],
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if cite.get("kind") == "num":
        return by_num.get(int(cite.get("n") or 0))
    surname = str(cite.get("surname") or "").lower()
    year = str(cite.get("year") or "")
    if not surname or not year:
        return None
    for entry in entries:
        raw = f"{entry.get('raw') or ''} {entry.get('title') or ''}".lower()
        if surname in raw and year in raw:
            return entry
    return None


def bind_claim_to_pages(claim: str, pages: list[tuple[int, str]]) -> dict[str, Any]:
    """Deterministic support against held PDF pages. Quote must occur in the page."""
    units = [
        Unit(heading="", loc=f"p. {n}", text=text) for n, text in pages if text.strip()
    ]
    bound = bind_claim(claim, units)
    quote = str(bound.get("support_quote") or "")
    loc = str(bound.get("loc") or "")
    status = str(bound.get("status") or "unsupported")
    page_text = ""
    for n, text in pages:
        if loc == f"p. {n}":
            page_text = text
            break
    if (
        status in {"supported", "thin"}
        and quote
        and not quote_in_text(quote, page_text)
    ):
        status = "unsupported"
        quote = ""
        loc = ""
    return {
        "status": status,
        "quote": quote,
        "loc": loc,
        "score": bound.get("score", 0.0),
    }


def attach_claim_sources(
    ledger: list[dict[str, Any]],
    doc: ExtractedDoc,
    cfg: Config,
    scope_items: list[Item],
    *,
    extra: list[Finding],
    comment_cap: int,
    exclude_key: str = "",
) -> str:
    """Mutate ledger rows with cited-PDF locators. Returns skip reason or empty."""
    if not scope_items:
        return "no_scope"
    from .identity import LibraryFingerprint
    from .snowball.bibliography import parse_bibliography_entries
    from .critique_overlap import load_library_pages

    fingerprint = LibraryFingerprint.from_items(scope_items)
    entries = parse_bibliography_entries(doc.text or "")
    by_num = numbered_bibliography(doc.text or "")
    max_sources = max(1, int(getattr(cfg, "critique_claims_cite_max_sources", 3) or 3))
    pages_by_key = load_library_pages(cfg, exclude_key=exclude_key)
    for row in ledger:
        window = claim_window(doc.text or "", str(row.get("text") or ""))
        cites = cites_in_window(window)
        if not cites:
            row["source_status"] = "no_cite"
            continue
        sources: list[dict[str, Any]] = []
        for cite in cites[:max_sources]:
            entry = resolve_cite(cite, by_num, entries)
            if entry is None:
                continue
            hit = fingerprint.find(
                entry.get("doi") or None,
                entry.get("title") or None,
                entry.get("year"),
            )
            if hit is None:
                sources.append(
                    {
                        "item_key": "",
                        "status": "not_in_library",
                        "quote": "",
                        "loc": "",
                    }
                )
                continue
            pages = pages_by_key.get(hit.item_key) or []
            if not pages:
                sources.append(
                    {
                        "item_key": hit.item_key,
                        "status": "no_text",
                        "quote": "",
                        "loc": "",
                    }
                )
                continue
            bound = bind_claim_to_pages(str(row.get("text") or ""), pages)
            sources.append(
                {
                    "item_key": hit.item_key,
                    "status": bound["status"],
                    "quote": bound["quote"][:200],
                    "loc": bound["loc"],
                }
            )
        row["sources"] = sources
        if not sources:
            row["source_status"] = "no_cite"
            continue
        statuses = {str(s.get("status") or "") for s in sources}
        if "supported" in statuses:
            row["source_status"] = "supported"
        elif "thin" in statuses:
            row["source_status"] = "thin"
        elif "no_text" in statuses:
            row["source_status"] = "no_text"
        elif "not_in_library" in statuses:
            row["source_status"] = "not_in_library"
        else:
            row["source_status"] = "unsupported"
        if len(extra) >= comment_cap:
            continue
        claim = str(row.get("text") or "")
        cid = str(row.get("id") or "")
        if "no_text" in statuses:
            extra.append(
                make_finding(
                    code="claim_cite_no_text",
                    severity="info",
                    lane="suggested",
                    loc=str(row.get("loc") or ""),
                    quote=claim,
                    detail=(
                        "Cited work is in the library but has no held PDF text "
                        f"in the index: {claim}"
                    )[:500],
                    source="claims",
                    extra={"reviewer": "claims", "claim_id": cid},
                )
            )
        elif "thin" in statuses and "supported" not in statuses:
            extra.append(
                make_finding(
                    code="claim_source_thin",
                    severity="info",
                    lane="suggested",
                    loc=str(row.get("loc") or ""),
                    quote=next(
                        (
                            str(s.get("quote") or "")
                            for s in sources
                            if s.get("status") == "thin" and s.get("quote")
                        ),
                        claim,
                    ),
                    detail=(
                        f"Claim is thinly supported by held cited PDF text: {claim}"
                    )[:500],
                    source="claims",
                    extra={"reviewer": "claims", "claim_id": cid},
                )
            )
        elif "unsupported" in statuses and not (
            statuses & {"supported", "thin", "no_text", "not_in_library"}
        ):
            extra.append(
                make_finding(
                    code="claim_source_unsupported",
                    severity="info",
                    lane="suggested",
                    loc=str(row.get("loc") or ""),
                    quote=claim,
                    detail=(f"Claim is not supported by held cited PDF text: {claim}")[
                        :500
                    ],
                    source="claims",
                    extra={"reviewer": "claims", "claim_id": cid},
                )
            )
    return ""


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
    scope_items: list[Item] | None = None,
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
    prompt_sha = sha256((_EXTRACT_SYSTEM + user[:2000]).encode("utf-8")).hexdigest()[
        :12
    ]
    meta["prompt_sha"] = prompt_sha
    say("Claims lane…")
    from .critique_llm import chat_with_json_retry, critique_chat_request

    request = critique_chat_request(
        model=model,
        messages=(
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user},
        ),
        timeout_seconds=timeout_s,
        temperature=0.2,
        json_mode=True,
    )
    t0 = time.perf_counter()
    try:
        raw = chat_with_json_retry(client, request, on_status=say, label="Claims")
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
        adj_user = f"Excerpt:\n{excerpt[:6000]}\n\nClaims:\n" + json.dumps(
            ledger, ensure_ascii=False
        )
        adj_req = critique_chat_request(
            model=model,
            messages=(
                {"role": "system", "content": _DOWNGRADE_SYSTEM},
                {"role": "user", "content": adj_user},
            ),
            timeout_seconds=timeout_s,
            temperature=0.2,
            json_mode=True,
        )
        try:
            adj_raw = chat_with_json_retry(client, adj_req, label="Claims")
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
        except Exception:  # noqa: S110 -- best-effort cleanup; intentionally ignored
            pass

    extra: list[Finding] = []
    for row in ledger:
        status = row["status"]
        if status == "supported":
            continue
        code = "claim_thin" if status == "thin" else "claim_unsupported_in_text"
        claim = row["text"]
        quote = row.get("support_quote") or claim
        if status == "thin":
            detail = f"Claim is thinly supported in this extract: {claim}"
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

    skip_sources = attach_claim_sources(
        ledger,
        doc,
        cfg,
        list(scope_items or []),
        extra=extra,
        comment_cap=comment_cap,
        exclude_key=item_key,
    )
    if skip_sources:
        meta["sources_skipped"] = skip_sources

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
