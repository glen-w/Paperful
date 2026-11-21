"""Figure/table/equation captions and acronym checkers."""

from __future__ import annotations

from ..config import Config
from ..critique import Finding, make_finding
from ..critique_direct_quotes import span_in_direct_quote
from ..critique_extract import ExtractedDoc, loc_for, loc_of_span
from ._common import (
    _ACRONYM,
    _EXPANSION,
    _FIG_CAPTION,
    _FIG_MENTION,
    _SKIP_ACRONYM,
    _split_body_biblio,
)


def _float_kind(word: str) -> str:
    w = (word or "").lower().rstrip(".")
    if w.startswith("fig"):
        return "fig"
    if w.startswith("tab"):
        return "tab"
    if w.startswith("eq"):
        return "eq"
    return w[:3]


def _floats(doc: ExtractedDoc) -> list[Finding]:
    captions: dict[str, str] = {}
    mentions: dict[str, str] = {}
    chunks = doc.pages or doc.paragraphs or [doc.text]
    for i, chunk in enumerate(chunks):
        loc = loc_for(doc, i)
        for m in _FIG_CAPTION.finditer(chunk):
            key = _float_kind(m.group(0).split()[0]) + m.group(1).lower()
            captions[key] = loc or chunk[:40]
        for m in _FIG_MENTION.finditer(chunk):
            key = _float_kind(m.group(0).split()[0]) + m.group(1).lower()
            line_start = chunk.rfind("\n", 0, m.start()) + 1
            prefix = chunk[line_start : m.start()]
            if not prefix.strip() and _FIG_CAPTION.match(chunk[line_start:]):
                continue
            mentions.setdefault(key, loc)
    out: list[Finding] = []
    for key, loc in captions.items():
        if key not in mentions:
            out.append(
                make_finding(
                    code="caption_not_referenced",
                    severity="info",
                    loc=loc,
                    detail=f"Caption {key} has no in-text mention.",
                    source="rule",
                )
            )
    for key, loc in mentions.items():
        if key not in captions:
            out.append(
                make_finding(
                    code="mention_without_caption",
                    severity="info",
                    loc=loc,
                    detail=f"In-text {key} has no matching caption line.",
                    source="rule",
                )
            )
    return out


def _acronyms(doc: ExtractedDoc) -> list[Finding]:
    body, _biblio = _split_body_biblio(doc.text)
    defined_at: dict[str, int] = {}
    for m in _EXPANSION.finditer(body):
        token = (m.group(2) or m.group(3) or "").upper()
        if token and token not in defined_at:
            defined_at[token] = m.start()
    seen: set[str] = set()
    out: list[Finding] = []
    for m in _ACRONYM.finditer(body):
        token = m.group(0)
        if token in _SKIP_ACRONYM or token in seen:
            continue
        first_def = defined_at.get(token)
        if first_def is not None and first_def <= m.start():
            continue
        line_start = body.rfind("\n", 0, m.start()) + 1
        line_end = body.find("\n", m.end())
        line = body[line_start : line_end if line_end != -1 else None]
        if line.strip() == token or (line.isupper() and len(line.split()) <= 8):
            continue
        seen.add(token)
        snippet = body[max(0, m.start() - 20) : m.end() + 40]
        out.append(
            make_finding(
                code="acronym_undefined",
                severity="info",
                loc=loc_of_span(doc, snippet),
                quote=snippet,
                detail=f"{token} appears before an expansion (Full Name ({token})).",
                source="rule",
            )
        )
        if len(out) >= 25:
            break
    return out


def _glossary_acronyms(cfg: Config, doc: ExtractedDoc) -> list[Finding]:
    if not cfg.critique_glossary:
        return []
    from ..glossary import MAX_HITS_PER_CODE, load_glossary, scan_glossary

    entries, _issues = load_glossary(cfg)
    if not entries:
        return []
    body, _biblio = _split_body_biblio(doc.text)
    hits = scan_glossary(
        body, entries, similarity_min=cfg.critique_glossary_similarity_min
    )
    out: list[Finding] = []
    counts = {"acronym_expansion_mismatch": 0, "acronym_phrase_mismatch": 0}
    for hit in hits:
        if span_in_direct_quote(body, hit.start, hit.end):
            continue
        n = counts.get(hit.code, 0)
        if n >= MAX_HITS_PER_CODE:
            continue
        counts[hit.code] = n + 1
        severity = "warn" if hit.code == "acronym_expansion_mismatch" else "info"
        out.append(
            make_finding(
                code=hit.code,
                severity=severity,
                loc=loc_of_span(doc, hit.quote),
                quote=hit.quote,
                detail=hit.detail,
                source="glossary",
                extra={"token": hit.token, "suggested": hit.suggested},
            )
        )
    return out
