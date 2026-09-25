"""Stop rules. No network."""

from __future__ import annotations

from .candidate import Candidate

# Soft ceiling so a typo does not walk the whole graph. Caps still bind first.
MAX_DEPTH = 5


def clamp_depth(depth: int) -> tuple[int, str | None]:
    """Normalize depth. Returns the depth to use and an optional warning."""
    if depth < 0:
        return 0, None
    if depth > MAX_DEPTH:
        return MAX_DEPTH, f"depth clamped to {MAX_DEPTH}"
    return depth, None


def keyword_depth(explicit: int | None) -> int:
    """Keyword runs stay at the hit list unless this command sets depth."""
    if explicit is None:
        return 0
    used, _warning = clamp_depth(explicit)
    return used


# OpenAlex types treated as journal-article-shaped when [snowball] types is unset.
JOURNAL_SHAPED = frozenset(
    {"article", "journal-article", "review", "preprint", "posted-content"}
)


def truncate(rows: list[Candidate], max_candidates: int) -> list[Candidate]:
    """Cap ``new`` and ``exists`` rows. ``error`` and ``filtered`` stay in the queue."""
    ranked = sorted(
        rows,
        key=lambda row: (
            -row.score,
            (row.ids.get("doi") or row.ids.get("openalex") or ""),
        ),
    )
    if max_candidates < 0:
        return [row for row in ranked if row.status in {"error", "filtered"}]
    kept: list[Candidate] = []
    budget = max_candidates
    for row in ranked:
        if row.status in {"error", "filtered"}:
            kept.append(row)
            continue
        if budget <= 0:
            continue
        kept.append(row)
        budget -= 1
    return kept


def apply_filters(
    rows: list[Candidate],
    *,
    year_from: int | None,
    year_to: int | None,
    types: tuple[str, ...],
    oa_only: bool,
    venue_include: tuple[str, ...],
    venue_exclude: tuple[str, ...],
    languages: tuple[str, ...] = (),
) -> list[Candidate]:
    """Mark rejects ``filtered``. Drop rows with no DOI and no OpenAlex id."""
    allowed = {item.lower() for item in types} if types else set(JOURNAL_SHAPED)
    include = {item.lower() for item in venue_include}
    exclude = {item.lower() for item in venue_exclude}
    langs = {item.lower() for item in languages}
    out: list[Candidate] = []
    for row in rows:
        if row.status == "error":
            out.append(row)
            continue
        if not row.identity:
            continue
        if row.status != "new":
            out.append(row)
            continue
        reasons: list[str] = []
        year = row.biblio.get("year")
        if year is not None:
            if year_from is not None and int(year) < year_from:
                reasons.append("year")
            if year_to is not None and int(year) > year_to:
                reasons.append("year")
        kind = str(row.biblio.get("type") or "").lower()
        if kind not in allowed:
            reasons.append("type")
        if oa_only and not row.biblio.get("is_oa"):
            reasons.append("oa")
        venue = str(row.biblio.get("venue") or "").lower()
        if include and venue not in include:
            reasons.append("venue")
        if venue and venue in exclude:
            reasons.append("venue")
        lang = str(row.biblio.get("language") or "").lower()
        if langs and lang and lang not in langs:
            reasons.append("language")
        if reasons:
            row.status = "filtered"
            note = ",".join(reasons)
            if note not in row.why:
                row.why = f"{row.why} ({note})"
        out.append(row)
    return out


def cap_ids(ids: list[str], per_hop_limit: int) -> list[str]:
    """Fan-out per seed, stable order."""
    seen: list[str] = []
    limit = max(0, per_hop_limit)
    for raw in ids:
        if raw and raw not in seen:
            seen.append(raw)
        if len(seen) >= limit:
            break
    return seen


def normalize_direction(raw: str) -> str:
    """Return refs, cites, or both. Raises ValueError for anything else."""
    value = (raw or "refs").strip().lower()
    if value in {"refs", "references", "ref"}:
        return "refs"
    if value in {"cites", "cited-by", "cited_by", "citations"}:
        return "cites"
    if value in {"both", "refs+cites", "all"}:
        return "both"
    raise ValueError(f"direction must be refs, cites, or both (got {raw!r})")
