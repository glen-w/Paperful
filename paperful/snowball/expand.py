"""Stop rules. No network."""

from __future__ import annotations

import random
from typing import Any, Callable

from .candidate import Candidate

# Soft ceiling so a typo does not walk the whole graph. Caps still bind first.
MAX_DEPTH = 5
# OpenAlex assigns at most five keywords to a work.
MAX_KEYWORD_LIMIT = 5
PER_HOP_RANKS = frozenset({"most-cited", "least-cited", "random"})
_DIRECTION_PARTS = {
    "ref": "refs",
    "refs": "refs",
    "references": "refs",
    "cites": "cites",
    "cited-by": "cites",
    "cited_by": "cites",
    "citations": "cites",
    "keyword": "keywords",
    "keywords": "keywords",
    "tags": "keywords",
    "similar": "similar",
    "similars": "similar",
}


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


MAX_STEM_VARIANTS = 8
MAX_SEARCH_BYTES = 3500
_STEM_SUFFIXES = ("", "s", "es", "ing", "ed", "ion", "ions", "al", "ally", "ic", "ical", "y")


def expand_search_term(term: str) -> tuple[str, list[str]]:
    """Expand a trailing ``*`` stem into an OpenAlex OR group. Return notices."""
    notices: list[str] = []
    text = (term or "").strip()
    if not text:
        return "", notices
    if "?" in text or "~" in text:
        notices.append(
            "OpenAlex search= is not a wildcard engine; ? and ~ are stripped, not expanded"
        )
        text = text.replace("?", "").replace("~", "")
    if "*" not in text:
        return text, notices
    if text.count("*") != 1 or not text.endswith("*") or len(text) < 2:
        notices.append("only a trailing * is expanded (polic* → policy OR policies …)")
        return text.replace("*", ""), notices
    stem = text[:-1].strip()
    if len(stem) < 3:
        notices.append("stem too short to expand; using the letters as-is")
        return stem, notices
    variants: list[str] = []
    for suffix in _STEM_SUFFIXES:
        if suffix == "y" and stem.endswith("y"):
            word = stem[:-1] + "ies"
        else:
            word = stem + suffix
        if word and word not in variants:
            variants.append(word)
        if len(variants) >= MAX_STEM_VARIANTS:
            break
    if stem.endswith("y"):
        ies = stem[:-1] + "ies"
        if ies not in variants and len(variants) < MAX_STEM_VARIANTS:
            variants.append(ies)
    group = " OR ".join(variants)
    if len(group.encode("utf-8")) > MAX_SEARCH_BYTES:
        kept: list[str] = []
        size = 0
        for word in variants:
            extra = len(word.encode("utf-8")) + (4 if kept else 0)
            if size + extra > MAX_SEARCH_BYTES:
                break
            kept.append(word)
            size += extra
        group = " OR ".join(kept or variants[:1])
        notices.append("stem expansion truncated to keep search= under OpenAlex's URL cap")
    return f"({group})" if " OR " in group else group, notices


def compose_keyword_query(
    terms: list[str] | tuple[str, ...],
    *,
    op: str = "and",
    notices: list[str] | None = None,
) -> str:
    """Build one OpenAlex ``search=`` string from keyword terms.

    A single term is passed through unchanged (hand-written booleans stay intact)
    unless it contains a trailing ``*``, which expands client-side into an OR group.
    Two or more terms are phrase-quoted and joined with ``AND`` (default) or ``OR``.
    """
    cleaned = [part.strip() for part in terms if part and str(part).strip()]
    if not cleaned:
        raise ValueError("Pass a keyword query.")
    mode = (op or "and").strip().lower()
    if mode not in {"and", "or"}:
        raise ValueError("query_op must be and or or")
    bucket = notices if notices is not None else []
    expanded: list[str] = []
    for part in cleaned:
        piece, extra = expand_search_term(part)
        bucket.extend(extra)
        if piece:
            expanded.append(piece)
    if not expanded:
        raise ValueError("Pass a keyword query.")
    if len(expanded) == 1:
        query = expanded[0]
    else:
        joiner = " OR " if mode == "or" else " AND "
        bits: list[str] = []
        for part in expanded:
            if part.startswith("(") or " OR " in part or " AND " in part:
                bits.append(part)
            else:
                bits.append(f'"{_escape_phrase(part)}"')
        query = joiner.join(bits)
    if len(query.encode("utf-8")) > MAX_SEARCH_BYTES:
        query = query.encode("utf-8")[:MAX_SEARCH_BYTES].decode("utf-8", errors="ignore")
        bucket.append("keyword query truncated to keep search= under OpenAlex's URL cap")
    return query


def _escape_phrase(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


# OpenAlex types treated as journal-article-shaped when [snowball] types is unset.
JOURNAL_SHAPED = frozenset(
    {"article", "journal-article", "review", "preprint", "posted-content"}
)


def truncate(rows: list[Candidate], max_candidates: int) -> list[Candidate]:
    """Cap ``new`` and ``exists`` rows. ``error`` and ``filtered`` stay in the queue.

    ``max_candidates <= 0`` keeps every row. ``per_hop_limit <= 0`` keeps every neighbour of a seed.
    """
    ranked = sorted(
        rows,
        key=lambda row: (
            -row.score,
            (row.ids.get("doi") or row.ids.get("openalex") or ""),
        ),
    )
    if max_candidates <= 0:
        return ranked
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


def publication_year(value: object) -> int | None:
    """Calendar year, or None when the field is blank or not a whole number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


# OpenAlex study_designs.id values (PubMed publication-type vocabulary).
STUDY_DESIGNS = frozenset(
    {
        "randomized-controlled-trial",
        "clinical-trial",
        "observational-study",
        "case-report",
        "systematic-review",
        "meta-analysis",
        "study-protocol",
    }
)
STUDY_DESIGN_ALIASES = {
    "rct": "randomized-controlled-trial",
    "randomized": "randomized-controlled-trial",
    "randomised-controlled-trial": "randomized-controlled-trial",
    "trial": "clinical-trial",
    "clinical": "clinical-trial",
    "observational": "observational-study",
    "case": "case-report",
    "sr": "systematic-review",
    "systematic": "systematic-review",
    "meta": "meta-analysis",
    "protocol": "study-protocol",
}


def normalize_study_design(raw: str) -> str:
    """Canonical OpenAlex ``study_designs.id`` slug, or raise ValueError."""
    text = str(raw or "").strip().lower().replace("_", "-").replace(" ", "-")
    if "/study-designs/" in text:
        text = text.rsplit("/study-designs/", 1)[-1]
    text = text.strip().strip("/")
    text = STUDY_DESIGN_ALIASES.get(text, text)
    if text not in STUDY_DESIGNS:
        known = ", ".join(sorted(STUDY_DESIGNS))
        raise ValueError(f"unknown study design {raw!r}; use one of: {known}")
    return text


def parse_study_designs(value: Any) -> tuple[str, ...]:
    """Parse CLI/config study designs. Repeatable values and commas are OR'd."""
    if value is None:
        return ()
    parts: list[str] = []
    if isinstance(value, str):
        parts = [part for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple)):
        for item in value:
            if item is None:
                continue
            if isinstance(item, str) and "," in item:
                parts.extend(part for part in item.split(",") if part.strip())
            else:
                text = str(item).strip()
                if text:
                    parts.append(text)
    else:
        text = str(value).strip()
        if text:
            parts.append(text)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        slug = normalize_study_design(part)
        if slug not in seen:
            seen.add(slug)
            out.append(slug)
    return tuple(out)


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
    study_designs: tuple[str, ...] = (),
) -> list[Candidate]:
    """Mark rejects ``filtered``. Drop rows with no DOI and no OpenAlex id."""
    allowed = {item.lower() for item in types} if types else set(JOURNAL_SHAPED)
    include = {item.lower() for item in venue_include}
    exclude = {item.lower() for item in venue_exclude}
    langs = {item.lower() for item in languages}
    wanted_designs = {item.lower() for item in study_designs if item}
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
        year = publication_year(row.biblio.get("year"))
        if year is not None:
            if year_from is not None and year < year_from:
                reasons.append("year")
            if year_to is not None and year > year_to:
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
        if wanted_designs:
            carried = {
                str(item).strip().lower()
                for item in (row.biblio.get("study_designs") or [])
                if str(item).strip()
            }
            if not (carried & wanted_designs):
                reasons.append("study_design")
        if reasons:
            row.status = "filtered"
            note = ",".join(reasons)
            if note not in row.why:
                row.why = f"{row.why} ({note})"
        out.append(row)
    return out


def cap_ids(ids: list[str], per_hop_limit: int) -> list[str]:
    """Fan-out per seed, stable order. ``per_hop_limit <= 0`` keeps every id."""
    seen: list[str] = []
    for raw in ids:
        if raw and raw not in seen:
            seen.append(raw)
        if per_hop_limit > 0 and len(seen) >= per_hop_limit:
            break
    return seen


def unique_ids(ids: list[str]) -> list[str]:
    """Deduplicate while keeping the first occurrence of each id."""
    seen: list[str] = []
    for raw in ids:
        if raw and raw not in seen:
            seen.append(raw)
    return seen


def sample_ids(ids: list[str], limit: int, *, rng: random.Random | None = None) -> list[str]:
    """Keep ``limit`` ids at random. ``limit <= 0`` keeps every id."""
    cleaned = unique_ids(ids)
    if limit <= 0 or len(cleaned) <= limit:
        return cleaned
    picker = rng or random.Random()
    return picker.sample(cleaned, limit)


def select_works_by_citations(
    works: list[dict[str, Any]],
    limit: int,
    rank: str,
    *,
    id_of: Callable[[dict[str, Any]], str] | None = None,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """Keep ``limit`` works by citation rank or a random sample.

    ``rank`` is most-cited, least-cited, or random. ``limit <= 0`` keeps every work.
    """
    if limit <= 0 or len(works) <= limit:
        return list(works)
    mode = (rank or "most-cited").strip().lower()
    if mode == "random":
        picker = rng or random.Random()
        return picker.sample(list(works), limit)
    reverse = mode != "least-cited"

    def key(work: dict[str, Any]) -> tuple[int, str]:
        cited = int(work.get("cited_by_count") or 0)
        identity = ""
        if id_of is not None:
            identity = id_of(work)
        else:
            identity = str(work.get("id") or work.get("doi") or "")
        return (cited, identity)

    ordered = sorted(works, key=key, reverse=reverse)
    return ordered[:limit]


def parse_keyword_limit(value: Any) -> int:
    """How many of a work's keywords to expand. 1–5. ``all`` and ``0`` are refused."""
    if isinstance(value, str) and value.strip().lower() in {"all", "unlimited"}:
        raise ValueError(
            "keyword_limit must be 1–5. all is not allowed; 5 uses every keyword OpenAlex stored."
        )
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("keyword_limit must be an integer from 1 to 5") from exc
    if number < 1 or number > MAX_KEYWORD_LIMIT:
        raise ValueError(
            "keyword_limit must be 1–5. all is not allowed; 5 uses every keyword OpenAlex stored."
        )
    return number


def parse_keyword_hop_limit(value: Any) -> int:
    """Works kept per seed on the keyword side. Positive integer only."""
    if isinstance(value, str) and value.strip().lower() in {"all", "unlimited", "0"}:
        raise ValueError(
            "keyword_hop_limit must be a positive integer. "
            "all is not allowed; a keyword filter is an open query."
        )
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "keyword_hop_limit must be a positive integer. "
            "all is not allowed; a keyword filter is an open query."
        ) from exc
    if number <= 0:
        raise ValueError(
            "keyword_hop_limit must be a positive integer. "
            "all is not allowed; a keyword filter is an open query."
        )
    return number


def parse_keyword_min_score(value: Any) -> float:
    """Drop seed keywords below this similarity. 0 keeps OpenAlex's own assignment."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("keyword_min_score must be 0 or greater") from exc
    if number < 0:
        raise ValueError("keyword_min_score must be 0 or greater")
    return number


def direction_sides(raw: str) -> frozenset[str]:
    """Sides named by a direction string. ``both`` and ``all`` stay refs plus cites."""
    value = (raw or "refs").strip().lower().replace(" ", "")
    if value == "all":
        return frozenset({"refs", "cites"})
    value = value.replace("both", "refs+cites")
    parts = [part for part in value.split("+") if part]
    if not parts or any(part not in _DIRECTION_PARTS for part in parts):
        raise ValueError(
            "direction must be refs, cites, both, keywords, similar, "
            "or a combination such as refs+similar "
            f"(got {raw!r})"
        )
    return frozenset(_DIRECTION_PARTS[part] for part in parts)


def format_direction(sides: frozenset[str]) -> str:
    """Canonical direction string. refs+cites stays ``both``."""
    if sides == frozenset({"refs", "cites"}):
        return "both"
    ordered = [side for side in ("refs", "cites", "keywords", "similar") if side in sides]
    return "+".join(ordered)


def normalize_direction(raw: str) -> str:
    """Return a canonical direction. Raises ValueError for anything else."""
    return format_direction(direction_sides(raw))
