"""Academic discourse hygiene (StoryScope inverted for manuscripts)."""

from __future__ import annotations

import re
from typing import Any

from ..peer_review import Finding, make_finding
from ..peer_review_direct_quotes import elide_direct_quotes, snippet_in_direct_quote
from ..peer_review_extract import ExtractedDoc, loc_of_span
from ._common import _AUTHOR_YEAR, _NUM_CITE

MAX_FAMILY = 5

_WEASEL = (
    "studies show",
    "research suggests",
    "experts say",
    "it has been shown that",
    "the literature suggests",
    "scholars agree",
)
_HYPE = (
    "groundbreaking",
    "cutting-edge",
    "game-changer",
    "game changer",
    "seamless",
    "delve",
    "tapestry",
    "ever-evolving",
    "in the realm of",
    "holistic approach",
    "unlock the potential",
    "pave the way",
    "shed light on",
    "paradigm shift",
    "unprecedented",
)
_CHATBOT = (
    ("in conclusion,", True),
    ("in summary,", True),
    ("i hope this helps", True),
    ("as an ai language model", True),
    ("as an ai,", True),
    ("sure,", True),
    ("great question", True),
)
_CLOSER = (
    "the takeaway",
    "the bottom line",
    "what this means for you",
    "key takeaway",
)
_LATEX_CITE = re.compile(r"\\cite[A-Za-z]*\{[^}]+\}|\[@[^\]]+\]")
_NOT_MERELY = re.compile(
    r"not merely\b.{0,80}\bbut rather\b",
    re.IGNORECASE | re.DOTALL,
)
_RULE_OF_THREE = re.compile(
    r"\b[\w'-]+,\s+[\w'-]+,\s+and\s+[\w'-]+\b",
    re.IGNORECASE,
)
def _nearby_cite(text: str, start: int, end: int, window: int = 80) -> bool:
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    chunk = text[lo:hi]
    return bool(
        _LATEX_CITE.search(chunk)
        or _NUM_CITE.search(chunk)
        or _AUTHOR_YEAR.search(chunk)
    )


def _add(
    out: list[Finding],
    *,
    code: str,
    quote: str,
    detail: str,
    loc: str,
    extra: dict[str, Any] | None = None,
) -> None:
    family = [f for f in out if f.code == code]
    if len(family) >= MAX_FAMILY:
        return
    out.append(
        make_finding(
            code=code,
            severity="info",
            loc=loc,
            quote=quote,
            detail=detail,
            source="discourse",
            extra=extra,
        )
    )


def scan_discourse(text: str, doc: ExtractedDoc | None = None) -> list[Finding]:
    """Checked hygiene findings. Skips direct quotations."""
    raw = text or ""
    prose = elide_direct_quotes(raw)
    lower = prose.casefold()
    out: list[Finding] = []
    loc = loc_of_span(doc, prose[:80]) if doc is not None else "prose"

    for phrase in _WEASEL:
        idx = 0
        folded = lower
        while True:
            pos = folded.find(phrase, idx)
            if pos < 0:
                break
            end = pos + len(phrase)
            snippet = prose[pos:end]
            if not snippet_in_direct_quote(raw, snippet) and not _nearby_cite(
                prose, pos, end
            ):
                _add(
                    out,
                    code="weasel_citation",
                    quote=snippet,
                    detail=(
                        f"Unattributed {phrase!r}. Name the study or add a cite "
                        "already in the manuscript."
                    ),
                    loc=loc_of_span(doc, snippet) if doc is not None else loc,
                )
            idx = end

    for phrase in _HYPE:
        rx = re.compile(rf"\b{re.escape(phrase)}\b", re.I)
        for m in rx.finditer(prose):
            snippet = m.group(0)
            if snippet_in_direct_quote(raw, snippet):
                continue
            _add(
                out,
                code="hype_copy",
                quote=snippet,
                detail=(
                    f"Promotional wording {snippet!r}. Prefer a concrete claim "
                    "already in the paragraph."
                ),
                loc=loc_of_span(doc, snippet) if doc is not None else loc,
            )

    for phrase, drop in _CHATBOT:
        pos = lower.find(phrase)
        if pos < 0:
            continue
        snippet = prose[pos : pos + len(phrase)]
        if snippet_in_direct_quote(raw, snippet):
            continue
        extra: dict[str, Any] = {"drop": True, "suggested": ""} if drop else {}
        _add(
            out,
            code="chatbot_residue",
            quote=snippet,
            detail=f"Chatbot leftover {snippet!r}. Drop or recast in academic register.",
            loc=loc_of_span(doc, snippet) if doc is not None else loc,
            extra=extra,
        )

    paras = [p for p in (doc.paragraphs if doc is not None else prose.split("\n\n")) if p.strip()]
    closer_blob = "\n\n".join(paras[-2:]) if paras else prose
    closer_lower = closer_blob.casefold()
    for phrase in _CLOSER:
        if phrase not in closer_lower:
            continue
        pos = closer_lower.find(phrase)
        snippet = closer_blob[pos : pos + len(phrase)]
        if snippet_in_direct_quote(raw, snippet):
            continue
        _add(
            out,
            code="marketing_closer",
            quote=snippet,
            detail=(
                f"Marketing closer {snippet!r}. Keep a contribution restatement; "
                "do not add a reader-address takeaway."
            ),
            loc=loc_of_span(doc, snippet) if doc is not None else loc,
        )

    if _NOT_MERELY.search(prose):
        m = _NOT_MERELY.search(prose)
        snippet = (m.group(0) if m else "not merely")[:80]
        if not snippet_in_direct_quote(raw, snippet):
            _add(
                out,
                code="discourse_scaffold",
                quote=snippet,
                detail="Not-merely-but-rather scaffold. Recast as a direct contrast.",
                loc=loc_of_span(doc, snippet) if doc is not None else loc,
            )
    triples = _RULE_OF_THREE.findall(prose)
    if len(triples) >= 4:
        snippet = triples[0]
        if not snippet_in_direct_quote(raw, snippet):
            _add(
                out,
                code="discourse_scaffold",
                quote=snippet,
                detail=(
                    f"Rule-of-three lists ×{len(triples)}. Vary list length; "
                    "do not invent a fourth item."
                ),
                loc=loc_of_span(doc, snippet) if doc is not None else loc,
            )
    return out
