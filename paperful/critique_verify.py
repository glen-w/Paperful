"""Section-swarm verification lane. Suggested only. No scores.

Deep Review-shaped: segment, density budget, sequential verify, local
synthesis. Does not upload the manuscript or call a hosted search API.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import Config
from .critique import Finding, make_finding
from .critique_extract import ExtractedDoc
from .critique_llm import findings_from_comments, parse_llm_json
from .critique_units import LIGHT_FAMILIES, Unit, family_of, paper_units
from .grounding import budget_slice
from .zot import Item

_HEAVY = re.compile(
    r"\b(lemma|theorem|proposition|corollary|proof|conjecture)\b", re.I
)
_MATH = re.compile(r"\$|\\\[|\\begin\{eq")
_METHODS = re.compile(
    r"\b(n\s*=|p\s*[<>=]|regression|protocol|we measured|sample size)\b", re.I
)
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
_QUOTED_TITLE = re.compile(r"[\"“]([^\"”]{8,80})[\"”]|'([^']{8,80})'")

_VERIFY_SYSTEM = """You verify one manuscript segment for objective errors.
You have the full excerpt for cross-references, but comment only on the segment.
Return JSON only:
{"comments": [{"code": "verify_logic|verify_math|verify_inconsistency|verify_gap", "quote": "span from the segment", "detail": "specific issue"}]}
Rules:
- Quotes MUST be substrings of the segment or excerpt.
- Do not invent papers, theorems, or numbers.
- No score, grade, or accept/reject.
- Do not claim plagiarism or misconduct.
- At most 6 comments. Prefer fewer sharp issues.
"""

_LIGHT_SYSTEM = """You do a short pass over a light manuscript segment.
Return JSON only:
{"comments": [{"code": "verify_logic|verify_gap", "quote": "span from the segment", "detail": "specific issue"}]}
Rules:
- Quotes MUST be substrings of the segment or excerpt.
- Skip generic style notes. At most 3 comments.
- No score, grade, or accept/reject.
"""

_ATTACK_SYSTEM = """You attack a previous acceptance of this segment.
The first pass found no issue or accepted a claim. Look again for a gap.
Return JSON only:
{"comments": [{"code": "verify_logic|verify_math|verify_inconsistency|verify_gap", "quote": "span from the segment", "detail": "specific issue"}]}
Rules:
- Quotes MUST be substrings of the segment or excerpt.
- Do not invent papers or theorems. No score or accept/reject.
- At most 4 comments. Empty is allowed if nothing new holds.
"""

_REFINE_SYSTEM = """You refine section-verify comments for one manuscript.
Return JSON only:
{"comments": [{"code": "verify_logic|verify_math|verify_inconsistency|verify_gap", "quote": "span from the paper", "detail": "clear specific comment"}]}
Drop comments that are invalid, generic, already done in the paper, score-like,
or that invent a paper or theorem not in the excerpt or bibliography.
Keep at most the asked maximum. No accept/reject or grade.
"""

_TURNS = {"heavy": 2, "medium": 1, "light": 1}


@dataclass
class Segment:
    heading: str
    loc: str
    text: str
    family: str
    budget: str = "medium"


def verify_timeout_s(cfg: Config) -> float:
    raw = float(getattr(cfg, "critique_verify_timeout_s", 0) or 0)
    if raw > 0:
        return raw
    return max(float(cfg.llm_timeout_s or 120), 600.0)


def density_budget(text: str, *, family: str = "") -> str:
    """Heuristic compute bucket for one segment."""
    body = text or ""
    if family in LIGHT_FAMILIES:
        if _HEAVY.search(body) or body.count("$") > 8:
            return "medium"
        return "light"
    score = 0
    if _HEAVY.search(body):
        score += 3
    math_n = len(_MATH.findall(body)) + body.count("$")
    if math_n > 5:
        score += 2
    digits = sum(ch.isdigit() for ch in body)
    if digits / max(len(body), 1) > 0.08:
        score += 1
    if _METHODS.search(body):
        score += 1
    if score >= 3:
        return "heavy"
    if score >= 1:
        return "medium"
    return "light"


def merge_segments(
    units: list[Unit],
    *,
    max_segments: int,
    cfg: Config | None = None,
) -> list[Segment]:
    """Merge heading units into overlapping logical segments."""
    if not units:
        return []
    groups: list[list[Unit]] = []
    current: list[Unit] = []
    current_fam = ""
    for unit in units:
        fam = family_of(unit, cfg)
        if current and fam and current_fam and fam != current_fam:
            groups.append(current)
            current = [unit]
            current_fam = fam
            continue
        current.append(unit)
        if fam:
            current_fam = fam
    if current:
        groups.append(current)
    cap = max(1, int(max_segments or 8))
    while len(groups) > cap:
        # Merge the two shortest adjacent groups.
        best_i = 0
        best_n = len(groups[0]) + len(groups[1])
        for i in range(len(groups) - 1):
            n = len(groups[i]) + len(groups[i + 1])
            if n < best_n:
                best_n = n
                best_i = i
        groups[best_i] = groups[best_i] + groups[best_i + 1]
        del groups[best_i + 1]
    out: list[Segment] = []
    for i, group in enumerate(groups):
        if i > 0 and groups[i - 1]:
            overlap = groups[i - 1][-1]
            if overlap not in group:
                group = [overlap, *group]
        heading = next((u.heading for u in group if u.heading), "")
        loc = group[0].loc if len(group) == 1 else f"{group[0].loc}–{group[-1].loc}"
        text = "\n\n".join(u.text for u in group if u.text.strip())
        fam = family_of(group[-1], cfg) or family_of(group[0], cfg)
        out.append(
            Segment(
                heading=heading,
                loc=loc,
                text=text,
                family=fam,
                budget=density_budget(text, family=fam),
            )
        )
    return [s for s in out if s.text.strip()]


def _biblio_hay(doc: ExtractedDoc) -> str:
    from .snowball.bibliography import parse_bibliography_entries

    bits: list[str] = []
    try:
        for entry in parse_bibliography_entries(doc.text or ""):
            title = str(entry.get("title") or "").strip()
            doi = str(entry.get("doi") or "").strip()
            if title:
                bits.append(title.lower())
            if doi:
                bits.append(doi.lower())
    except Exception:
        pass
    return "\n".join(bits)


def doi_in_status_cache(cfg: Config, doi: str) -> bool:
    """True when screen's Crossref/OpenAlex status cache already has this DOI.

    Cache-only. Never performs HTTP.
    """
    from .resolve import normalize_doi
    from .screen import _read_status_cache

    cleaned = normalize_doi(doi) or (doi or "").lower()
    if not cleaned:
        return False
    return _read_status_cache(cfg, cleaned) is not None


def invents_citation(
    detail: str,
    *,
    extract_hay: str,
    biblio_hay: str,
    cached_dois: set[str] | None = None,
) -> bool:
    """True when a comment names a title or DOI absent from extract, biblio, and cache."""
    text = detail or ""
    combined = f"{extract_hay}\n{biblio_hay}"
    cached = {d.lower() for d in (cached_dois or ())}
    for match in _DOI.finditer(text):
        doi = match.group(0).lower().rstrip(".,);")
        if doi in combined or doi in cached:
            continue
        return True
    for match in _QUOTED_TITLE.finditer(text):
        title = (match.group(1) or match.group(2) or "").strip().lower()
        if title and title not in combined:
            return True
    return False


def _named_dois(text: str) -> list[str]:
    return [m.group(0).rstrip(".,);") for m in _DOI.finditer(text or "")]


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


def suggested_from_verify(
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
    """Segment-and-verify pass with local grounding. Suggested lane only."""
    say = on_status or (lambda _msg: None)
    model = cfg.llm_model
    timeout = verify_timeout_s(cfg)
    deadline = time.monotonic() + timeout
    cap = max(1, int(getattr(cfg, "critique_verify_max_comments", 16) or 16))
    max_segments = max(1, int(getattr(cfg, "critique_verify_max_segments", 8) or 8))
    item_key = item.key if item is not None else ""
    units, unit_meta = paper_units(
        cfg,
        doc,
        use_grobid=use_grobid,
        pdf_path=pdf_path,
        item_key=item_key,
    )
    segments = merge_segments(units, max_segments=max_segments, cfg=cfg)
    excerpt = budget_slice(doc.text, cfg.critique_max_context_chars)
    body_hay = (hay or excerpt.lower() or "") + "\n" + excerpt.lower()
    biblio_hay = _biblio_hay(doc)
    meta: dict[str, Any] = {
        "id": "verify",
        "model": model,
        "parser": unit_meta.get("parser") or "extract",
        "calls": 0,
        "segments": [],
    }
    if unit_meta.get("grobid_skipped"):
        meta["grobid_skipped"] = unit_meta["grobid_skipped"]
    if not segments:
        meta["skipped"] = "empty_extract"
        meta["reviewers"] = [
            {"id": "verify", "model": model, "skipped": "empty_extract"}
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
    ][:20]
    say(f"Verify lane ({len(segments)} segment(s) via {meta['parser']})…")
    all_comments: list[dict[str, Any]] = []
    reviewer_rows: list[dict[str, Any]] = []
    first_sha = sha256(_VERIFY_SYSTEM.encode("utf-8")).hexdigest()[:12]
    meta["prompt_sha"] = first_sha
    cite_unchecked = False

    def remaining() -> float:
        return max(1.0, deadline - time.monotonic())

    for seg in segments:
        row: dict[str, Any] = {
            "id": f"verify-{seg.heading or seg.loc}",
            "heading": seg.heading,
            "loc": seg.loc,
            "budget": seg.budget,
            "calls": 0,
        }
        if time.monotonic() >= deadline:
            row["skipped"] = "timeout"
            meta["segments"].append(row)
            reviewer_rows.append(
                {
                    "id": f"verify-{seg.heading or seg.loc}",
                    "model": model,
                    "skipped": "timeout",
                }
            )
            continue
        turns = _TURNS.get(seg.budget, 1)
        system = _LIGHT_SYSTEM if seg.budget == "light" else _VERIFY_SYSTEM
        user = (
            f"Title: {title}\nSegment: {seg.heading or seg.loc} ({seg.budget})\n"
            f"Checked findings: {json.dumps(checked, ensure_ascii=False)}\n\n"
            f"Full excerpt:\n{excerpt}\n\nSegment:\n{seg.text}"
        )
        try:
            raw = _chat(
                client,
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                timeout=remaining(),
            )
        except Exception as exc:
            row["skipped"] = "llm_error"
            row["error"] = str(exc)
            meta["calls"] = int(meta["calls"]) + 0
            meta["segments"].append(row)
            reviewer_rows.append(
                {
                    "id": f"verify-{seg.heading or seg.loc}",
                    "model": model,
                    "skipped": "llm_error",
                    "error": str(exc),
                }
            )
            continue
        row["calls"] = 1
        meta["calls"] = int(meta["calls"]) + 1
        data = parse_llm_json(raw) or {}
        comments = [
            c for c in (data.get("comments") or []) if isinstance(c, dict)
        ]
        if turns > 1 and time.monotonic() < deadline:
            attack_user = (
                f"Previous comments: {json.dumps(comments, ensure_ascii=False)}\n"
                f"Segment:\n{seg.text}\n\nExcerpt:\n{excerpt[:4000]}"
            )
            try:
                araw = _chat(
                    client,
                    model=model,
                    messages=[
                        {"role": "system", "content": _ATTACK_SYSTEM},
                        {"role": "user", "content": attack_user},
                    ],
                    timeout=remaining(),
                )
                row["calls"] = int(row["calls"]) + 1
                meta["calls"] = int(meta["calls"]) + 1
                adata = parse_llm_json(araw) or {}
                comments.extend(
                    c for c in (adata.get("comments") or []) if isinstance(c, dict)
                )
            except Exception:
                pass
        for c in comments:
            tagged = dict(c)
            tagged.setdefault("code", "verify_gap")
            all_comments.append(tagged)
        meta["segments"].append(row)
        reviewer_rows.append(
            {
                "id": f"verify-{seg.heading or seg.loc}",
                "model": model,
                "prompt_sha": first_sha,
            }
        )

    if time.monotonic() >= deadline and any(
        s.get("skipped") == "timeout" for s in meta["segments"]
    ):
        meta["skipped"] = meta.get("skipped") or "timeout"

    if all_comments and time.monotonic() < deadline:
        payload = json.dumps(all_comments[: cap * 2], ensure_ascii=False)[:12_000]
        try:
            raw = _chat(
                client,
                model=model,
                messages=[
                    {"role": "system", "content": _REFINE_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Keep at most {cap} comments.\nExcerpt:\n{excerpt[:4000]}\n"
                            f"Comments:\n{payload}"
                        ),
                    },
                ],
                timeout=remaining(),
            )
            meta["calls"] = int(meta["calls"]) + 1
            data = parse_llm_json(raw) or {}
            refined = [
                c for c in (data.get("comments") or []) if isinstance(c, dict)
            ]
            if refined:
                all_comments = refined
        except Exception:
            pass

    cached_dois: set[str] = set()
    for row in all_comments:
        for doi in _named_dois(str(row.get("detail") or "")):
            if doi_in_status_cache(cfg, doi):
                cached_dois.add(doi.lower())
    kept: list[dict[str, Any]] = []
    for row in all_comments:
        detail = str(row.get("detail") or "")
        if invents_citation(
            detail,
            extract_hay=body_hay,
            biblio_hay=biblio_hay,
            cached_dois=cached_dois,
        ):
            dois = _named_dois(detail)
            if dois and not any(d.lower() in cached_dois for d in dois):
                cite_unchecked = True
            continue
        kept.append(row)

    findings_out = findings_from_comments(
        kept,
        hay=body_hay,
        reviewer_id="verify",
        source="llm",
        limit=cap,
    )
    if cite_unchecked:
        findings_out.append(
            make_finding(
                code="verify_cite_unchecked",
                severity="info",
                lane="suggested",
                detail=(
                    "A verify comment named a DOI that is not in this extract, "
                    "bibliography, or Crossref/OpenAlex status cache. No live lookup was made."
                ),
                source="llm",
                extra={"reviewer": "verify"},
            )
        )
    if not findings_out:
        meta["skipped"] = meta.get("skipped") or "empty_reply"
        if any(s.get("skipped") == "timeout" for s in meta["segments"]):
            findings_out = [
                make_finding(
                    code="llm_failed",
                    severity="info",
                    lane="suggested",
                    detail="Verify lane stopped: timeout.",
                    source="llm",
                    extra={"reviewer": "verify"},
                )
            ]
        elif any(s.get("skipped") == "llm_error" for s in meta["segments"]):
            err = next(
                (s.get("error") for s in meta["segments"] if s.get("error")),
                "llm_error",
            )
            findings_out = [
                make_finding(
                    code="llm_failed",
                    severity="info",
                    lane="suggested",
                    detail=f"Verify lane failed: {err}",
                    source="llm",
                    extra={"reviewer": "verify"},
                )
            ]
    if reviewer_rows:
        meta["reviewers"] = reviewer_rows
    else:
        meta["reviewers"] = [{"id": "verify", "model": model}]
    return findings_out, meta
