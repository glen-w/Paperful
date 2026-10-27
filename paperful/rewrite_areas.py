"""Area maps and finding filters for ``paperful rewrite``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

KNOWN_AREAS = ("style", "cites", "structure", "comments")
KNOWN_OUTPUTS = ("edits", "sidecar", "tracked")
KNOWN_COMMENTS = ("off", "substantive", "all")

STYLE_CODES = frozenset(
    {
        "acronym_undefined",
        "acronym_expansion_mismatch",
        "acronym_phrase_mismatch",
        "long_sentence",
        "hedge_words",
        "passive_voice",
    }
)
CITES_CODES = frozenset(
    {
        "cite_not_in_bibliography",
        "bibliography_not_cited",
        "cited_not_in_library",
    }
)
STRUCTURE_CODES = frozenset(
    {
        "missing_section",
        "caption_not_referenced",
        "mention_without_caption",
        "missing_mention",
    }
)
COMMENT_ONLY_CODES = frozenset(
    {
        "cited_retracted",
        "cited_withdrawn",
        "cited_expression_of_concern",
    }
)
SKIP_CODES = frozenset(
    {
        "needs_ocr",
        "empty_extract",
        "short_pdf",
        "skipped_not_pdf",
        "text_overlap",
        "overlap_skipped_no_text",
        "ai_tell",
        "ai_tell_summary",
        "ai_tells_abstain",
        "ai_model_unavailable",
        "readability_summary",
        "lexical_diversity_summary",
        "pdf_identity_mismatch",
        "llm_refused_identity",
        "doi_status_skipped_offline",
        "identity_skipped_offline",
        "vale_unavailable",
        "vale_no_config",
        "vale_failed",
        "vale_truncated",
        "paperguard_unavailable",
        "paperguard_no_input",
        "paperguard_failed",
        "paperguard_truncated",
    }
)
SKIP_PREFIXES = ("paperguard_",)
_ACTIONABLE = re.compile(
    r"\b(should|must|missing|unclear|replace|expand|cite|add|remove|define|"
    r"passive|hedge|long|mismatch|not in|undefined)\b",
    re.I,
)
_PRAISE = re.compile(
    r"\b(well written|clearly written|strength|commend|excellent|solid work)\b",
    re.I,
)


@dataclass(frozen=True)
class RewriteArea:
    """One specialist for ``paperful rewrite``."""

    id: str
    model: str = ""
    prompt: str = "default"
    codes: tuple[str, ...] = ()


def parse_rewrite_areas_list(raw: Any) -> tuple[str, ...]:
    """Normalise ``[rewrite].areas``."""
    if raw is None:
        return ("style",)
    if isinstance(raw, str):
        names = [raw]
    elif isinstance(raw, (list, tuple)):
        names = list(raw)
    else:
        raise ValueError("[rewrite].areas must be a string or list of area ids")
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        token = str(name or "").strip().lower()
        if not token:
            continue
        if token == "all":
            return tuple(KNOWN_AREAS)
        if token not in KNOWN_AREAS:
            raise ValueError(
                f"unknown rewrite area {name!r} (want {', '.join(KNOWN_AREAS)} or all)"
            )
        if token not in seen:
            seen.add(token)
            out.append(token)
    return tuple(out) or ("style",)


def parse_rewrite_outputs(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ("edits", "tracked")
    if isinstance(raw, str):
        names = [raw]
    elif isinstance(raw, (list, tuple)):
        names = list(raw)
    else:
        raise ValueError("[rewrite].outputs must be a string or list")
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        token = str(name or "").strip().lower()
        if not token:
            continue
        if token not in KNOWN_OUTPUTS:
            raise ValueError(
                f"unknown rewrite output {name!r} (want {', '.join(KNOWN_OUTPUTS)})"
            )
        if token not in seen:
            seen.add(token)
            out.append(token)
    if "edits" not in seen:
        out.insert(0, "edits")
    return tuple(out) or ("edits", "tracked")


def parse_rewrite_comments(raw: Any) -> str:
    value = str(raw or "off").strip().lower() or "off"
    if value not in KNOWN_COMMENTS:
        raise ValueError(
            f"[rewrite].comments {raw!r} must be off, substantive, or all"
        )
    return value


def parse_rewrite_specialists(raw: Any) -> tuple[RewriteArea, ...]:
    """Parse ``[[rewrite.specialists]]`` (not ``areas`` — that key is the enabled id list)."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(
            "[rewrite].specialists must be an array of tables ([[rewrite.specialists]])"
        )
    out: list[RewriteArea] = []
    seen: set[str] = set()
    for i, row in enumerate(raw, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"[rewrite.specialists] entry {i} must be a table")
        rid = str(row.get("id") or "").strip() or (
            "style" if len(raw) == 1 else f"area-{i}"
        )
        if rid in seen:
            raise ValueError(f"[rewrite.specialists] duplicate id {rid!r}")
        seen.add(rid)
        codes_raw = row.get("codes")
        codes: tuple[str, ...] = ()
        if codes_raw is not None:
            if not isinstance(codes_raw, (list, tuple)):
                raise ValueError(f"[rewrite.specialists] {rid} codes must be a list")
            codes = tuple(str(c).strip() for c in codes_raw if str(c).strip())
        out.append(
            RewriteArea(
                id=rid,
                model=str(row.get("model") or "").strip(),
                prompt=str(row.get("prompt") or "default").strip() or "default",
                codes=codes,
            )
        )
    return tuple(out)


def rewrite_areas_for(
    cfg: Any,
    wanted: list[str] | None = None,
) -> tuple[RewriteArea, ...]:
    """Configured specialists, or builtin rows for the selected area ids."""
    selected = tuple(wanted) if wanted else tuple(getattr(cfg, "rewrite_areas", ()) or ("style",))
    selected = parse_rewrite_areas_list(list(selected))
    rows = tuple(getattr(cfg, "rewrite_specialists", ()) or ())
    by_id = {r.id: r for r in rows}
    out: list[RewriteArea] = []
    for aid in selected:
        row = by_id.get(aid)
        if row is None:
            out.append(RewriteArea(id=aid))
        else:
            out.append(row)
    return tuple(out)


def code_matches(code: str, patterns: Iterable[str]) -> bool:
    token = (code or "").strip()
    if not token:
        return False
    for raw in patterns:
        pat = str(raw or "").strip()
        if not pat:
            continue
        if pat.endswith("*"):
            if token.startswith(pat[:-1]):
                return True
        elif token == pat:
            return True
    return False


def is_skip_code(code: str) -> bool:
    token = (code or "").strip()
    if token in SKIP_CODES:
        return True
    return any(token.startswith(p) for p in SKIP_PREFIXES)


def is_vale_style(code: str) -> bool:
    token = (code or "").strip()
    return token.startswith("vale_") and not is_skip_code(token)


def builtin_codes_for(area_id: str) -> frozenset[str]:
    if area_id == "style":
        return STYLE_CODES
    if area_id == "cites":
        return CITES_CODES
    if area_id == "structure":
        return STRUCTURE_CODES
    if area_id == "comments":
        return COMMENT_ONLY_CODES
    return frozenset()


def finding_area(finding: dict[str, Any], areas: Iterable[str]) -> str | None:
    """First enabled area that owns this finding, or None."""
    code = str(finding.get("code") or "")
    enabled = [a for a in areas if a in KNOWN_AREAS]
    if "style" in enabled and (code in STYLE_CODES or is_vale_style(code)):
        return "style"
    if "cites" in enabled and code in CITES_CODES:
        return "cites"
    if "structure" in enabled and code in STRUCTURE_CODES:
        return "structure"
    if "comments" in enabled and code in COMMENT_ONLY_CODES:
        return "comments"
    if "comments" in enabled and str(finding.get("lane") or "") == "suggested":
        return "comments"
    return None


def is_actionable(finding: dict[str, Any]) -> bool:
    """True when a suggested note implies a request, not praise."""
    if str(finding.get("lane") or "") != "suggested":
        return True
    detail = str(finding.get("detail") or "")
    quote = str(finding.get("quote") or "")
    if _PRAISE.search(detail) and not _ACTIONABLE.search(detail):
        return False
    if not quote and not detail:
        return False
    if quote or _ACTIONABLE.search(detail):
        return True
    return bool(str(finding.get("loc") or "").strip())


def skip_reason_for(finding: dict[str, Any], *, hay: str) -> str | None:
    """Return a skip reason, or None if the finding may proceed to align."""
    if finding.get("dismissed"):
        return "dismissed"
    code = str(finding.get("code") or "")
    if is_skip_code(code):
        return "not_actionable"
    if not is_actionable(finding):
        return "not_actionable"
    quote = str(finding.get("quote") or "").strip()
    if quote:
        from .critique_direct_quotes import snippet_in_direct_quote

        if snippet_in_direct_quote(hay, quote):
            return "quote"
    return None


def bucket_findings(
    findings: Iterable[dict[str, Any]],
    *,
    areas: Iterable[str],
    hay: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """Split findings into area buckets and skips."""
    enabled = tuple(a for a in areas if a in KNOWN_AREAS)
    buckets: dict[str, list[dict[str, Any]]] = {a: [] for a in enabled}
    skips: list[dict[str, str]] = []
    for row in findings:
        if not isinstance(row, dict):
            continue
        fid = str(row.get("id") or "")
        reason = skip_reason_for(row, hay=hay)
        if reason:
            skips.append({"finding_id": fid, "reason": reason})
            continue
        area = finding_area(row, enabled)
        if area is None:
            skips.append({"finding_id": fid, "reason": "not_actionable"})
            continue
        buckets[area].append(row)
    return buckets, skips
