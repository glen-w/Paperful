"""Mentions, stats, readability, and prose checkers."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ..critique import Finding, make_finding
from ..critique_direct_quotes import offset_in_direct_quote, snippet_in_direct_quote
from ..critique_extract import ExtractedDoc, loc_of_span
from ..critique_stats import scan_stats
from ..zot import Item
from ._common import (
    _CONSORT_HINT,
    _CONSORT_WORD,
    _HEDGE,
    _MENTIONS,
    _NUM,
    _PASSIVE,
    _PRISMA_HINT,
    _PRISMA_WORD,
    _REPO_URL,
    _SENTENCE,
    _URL,
    _YEAR,
    _split_body_biblio,
)


def _abstract_numbers(doc: ExtractedDoc) -> list[Finding]:
    pages = doc.pages or [doc.text]
    abstract = pages[0]
    if len(pages) > 1:
        body = "\n".join(pages[1:])
    else:
        body, _ = _split_body_biblio(doc.text)
        # drop first 800 chars as abstract-ish
        abstract = body[:1200]
        body = body[1200:]
    body_fold = re.sub(r"\s+", " ", body)
    out: list[Finding] = []
    seen: set[str] = set()
    for m in _NUM.finditer(abstract):
        token = m.group(1)
        if token in seen or _YEAR.match(token):
            continue
        seen.add(token)
        if token not in body_fold:
            out.append(
                make_finding(
                    code="abstract_number_missing",
                    severity="info",
                    loc=loc_of_span(doc, abstract[:80]),
                    quote=abstract[max(0, m.start() - 30) : m.end() + 30],
                    detail=f"Number {token} in the opening/abstract is not repeated in the body.",
                    source="rule",
                )
            )
        if len(out) >= 12:
            break
    return out


def _mentions_and_urls(doc: ExtractedDoc) -> list[Finding]:
    out: list[Finding] = []
    text = doc.text
    for code, rx in _MENTIONS.items():
        if not rx.search(text):
            out.append(
                make_finding(
                    code="missing_mention",
                    severity="info",
                    detail=f"No mention of {code.replace('_', ' ')}.",
                    source="rule",
                    extra={"mention": code},
                )
            )
    if not _REPO_URL.search(text):
        out.append(
            make_finding(
                code="missing_mention",
                severity="info",
                detail="No GitHub/Zenodo/OSF/Hugging Face data or code URL.",
                source="rule",
                extra={"mention": "code_or_data_url"},
            )
        )
    for m in _URL.finditer(text):
        url = m.group(0).rstrip(".,;:")
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or "." not in parsed.netloc
        ):
            out.append(
                make_finding(
                    code="malformed_url",
                    severity="warn",
                    loc=loc_of_span(doc, url),
                    quote=url,
                    detail="URL looks malformed.",
                    source="rule",
                )
            )
    return out


def _checklists(doc: ExtractedDoc, item: Item | None) -> list[Finding]:
    text = doc.text
    out: list[Finding] = []
    if _PRISMA_HINT.search(text) and not _PRISMA_WORD.search(text):
        out.append(
            make_finding(
                code="checklist_prisma",
                severity="info",
                detail="Text looks like a systematic review / meta-analysis but does not mention PRISMA.",
                source="rule",
            )
        )
    if _CONSORT_HINT.search(text) and not _CONSORT_WORD.search(text):
        out.append(
            make_finding(
                code="checklist_consort",
                severity="info",
                detail="Text looks like a trial but does not mention CONSORT.",
                source="rule",
            )
        )
    return out


def _stats(doc: ExtractedDoc) -> list[Finding]:
    out: list[Finding] = []
    for hit in scan_stats(doc.text):
        if hit.kind == "grim" and not hit.consistent:
            out.append(
                make_finding(
                    code="grim_impossible_mean",
                    severity="warn",
                    loc=loc_of_span(doc, hit.quote),
                    quote=hit.quote,
                    detail=hit.detail,
                    source="rule",
                )
            )
        elif hit.kind in {"t", "F", "chi2", "z"} and not hit.consistent:
            out.append(
                make_finding(
                    code="statcheck_p_mismatch",
                    severity="warn",
                    loc=loc_of_span(doc, hit.quote),
                    quote=hit.quote,
                    detail=hit.detail,
                    source="rule",
                )
            )
        elif hit.kind == "p_no_n":
            out.append(
                make_finding(
                    code="p_without_n",
                    severity="info",
                    loc=loc_of_span(doc, hit.quote),
                    quote=hit.quote,
                    detail=hit.detail,
                    source="rule",
                )
            )
    return out


def _fmt_metric(value: Any, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _style_metrics(doc: ExtractedDoc) -> list[Finding]:
    """Readability / lexical summaries plus suggested AI-prose tells."""
    from ..critique_ai_tells import (
        MAX_PHRASE_FINDINGS,
        MIN_AI_TELL_WORDS,
        compute_ai_tells,
    )
    from ..critique_metrics import compute_style_metrics

    text = doc.text or ""
    metrics = compute_style_metrics(text)
    tells = compute_ai_tells(text, doc.paragraphs or None)
    out: list[Finding] = []
    read = metrics.get("readability") or {}
    if not read.get("insufficient"):
        out.append(
            make_finding(
                code="readability_summary",
                severity="info",
                loc="document",
                detail=(
                    f"Flesch {_fmt_metric(read.get('flesch_reading_ease'))}; "
                    f"Gunning Fog {_fmt_metric(read.get('gunning_fog'))}; "
                    f"ARI {_fmt_metric(read.get('ari'))}. "
                    "Academic FRE is often 0–30; that is expected, not a defect."
                ),
                source="readability",
            )
        )
    lex = metrics.get("lexical_diversity") or {}
    mtld = lex.get("mtld")
    mtld_bit = (
        f"MTLD {_fmt_metric(mtld, 1)}"
        if mtld is not None
        else "MTLD omitted (<50 tokens)"
    )
    if lex.get("token_count"):
        out.append(
            make_finding(
                code="lexical_diversity_summary",
                severity="info",
                loc="document",
                detail=(
                    f"TTR {_fmt_metric(lex.get('ttr'), 3)}; {mtld_bit}; "
                    f"hapax rate {_fmt_metric(lex.get('hapax_rate'), 3)} "
                    f"({lex.get('type_count')} types / {lex.get('token_count')} tokens)."
                ),
                source="lexical_diversity",
            )
        )
    if tells.get("abstain"):
        out.append(
            make_finding(
                code="ai_tells_abstain",
                severity="info",
                lane="suggested",
                loc="document",
                detail=(
                    f"Fewer than {MIN_AI_TELL_WORDS} words; "
                    "heuristic AI-prose signals skipped."
                ),
                source="ai_tells",
            )
        )
        return out
    cv = tells.get("burstiness_cv")
    out.append(
        make_finding(
            code="ai_tell_summary",
            severity="info",
            lane="suggested",
            loc="document",
            detail=(
                f"Burstiness CV {_fmt_metric(cv, 2)}; "
                f"{tells.get('tell_phrase_total', 0)} tell-phrase hits "
                f"({len(tells.get('tell_phrase_hits') or [])} distinctive). "
                "Not proof of AI authorship."
            ),
            source="ai_tells",
        )
    )
    for hit in (tells.get("tell_phrase_hits") or [])[:MAX_PHRASE_FINDINGS]:
        phrase = str(hit.get("phrase") or "")
        count = hit.get("count") or 0
        out.append(
            make_finding(
                code="ai_tell",
                severity="info",
                lane="suggested",
                loc="prose",
                quote=phrase,
                detail=(
                    f"Stock phrase {phrase!r} ×{count}. Associated with some "
                    "LLM-style prose; not proof of AI."
                ),
                source="ai_tells",
            )
        )
    for flag in tells.get("unicode_flags") or []:
        out.append(
            make_finding(
                code="ai_tell",
                severity="info",
                lane="suggested",
                loc="unicode",
                quote=str(flag),
                detail=f"Typography flag {flag}. Provenance hint, not authorship proof.",
                source="ai_tells",
            )
        )
    for flag in tells.get("discourse") or []:
        out.append(
            make_finding(
                code="ai_tell",
                severity="info",
                lane="suggested",
                loc="discourse",
                quote=str(flag),
                detail=f"Discourse scaffold {flag}. Not proof of AI authorship.",
                source="ai_tells",
            )
        )
    return out


def _prose(doc: ExtractedDoc) -> list[Finding]:
    sentences = [s.strip() for s in _SENTENCE.findall(doc.text) if s.strip()]
    if not sentences:
        return []
    body = doc.text or ""
    long = [
        s
        for s in sentences
        if len(s.split()) >= 40 and not snippet_in_direct_quote(body, s)
    ]
    hedges = [
        m for m in _HEDGE.finditer(body) if not offset_in_direct_quote(body, m.start())
    ]
    passive = [
        m
        for m in _PASSIVE.finditer(body)
        if not offset_in_direct_quote(body, m.start())
    ]
    words = len(doc.text.split())
    out: list[Finding] = []
    if long:
        out.append(
            make_finding(
                code="long_sentence",
                severity="info",
                loc=loc_of_span(doc, long[0][:80]),
                quote=long[0],
                detail=f"{len(long)} sentence(s) with ≥40 words.",
                source="rule",
            )
        )
    if hedges:
        density = len(hedges) / max(1, words) * 1000
        if density >= 12:
            out.append(
                make_finding(
                    code="hedge_words",
                    severity="info",
                    loc=loc_of_span(doc, hedges[0].group(0)),
                    quote=hedges[0].group(0),
                    detail=f"{len(hedges)} hedge-word hits ({density:.1f} per 1000 words).",
                    source="rule",
                )
            )
    if passive:
        out.append(
            make_finding(
                code="passive_voice",
                severity="info",
                loc=loc_of_span(doc, passive[0].group(0)),
                quote=passive[0].group(0),
                detail=f"{len(passive)} passive-voice hotspot(s) (heuristic).",
                source="rule",
            )
        )
    return out
