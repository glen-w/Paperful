"""Literature categories for the citation map (orthogonal to year×cite roles).

Built-ins map OpenAlex ``study_designs`` slugs onto short labels. Users can
add more rules via config ``map_category_defs`` (any-of study designs and/or
document types). A paper may match several categories at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CategoryDef:
    """One map category: id, label, and match rules."""

    id: str
    label: str
    any_study_designs: tuple[str, ...] = ()
    any_types: tuple[str, ...] = ()
    color: str = "#5c6b7a"


# Default fill accents for badges (role colors stay on the node circle).
# Study-design rules use OpenAlex study_designs; type rules use biblio.type.
BUILT_IN_CATEGORIES: tuple[CategoryDef, ...] = (
    CategoryDef(
        id="evidence-synthesis",
        label="Evidence synthesis",
        any_study_designs=("systematic-review", "meta-analysis"),
        color="#6b3fa0",
    ),
    CategoryDef(
        id="trials",
        label="Trials",
        any_study_designs=("randomized-controlled-trial",),
        color="#b23a48",
    ),
    CategoryDef(
        id="clinical-trials",
        label="Clinical trials",
        any_study_designs=("clinical-trial",),
        color="#c45c26",
    ),
    CategoryDef(
        id="observational",
        label="Observational",
        any_study_designs=("observational-study",),
        color="#2a6f97",
    ),
    CategoryDef(
        id="case-reports",
        label="Case reports",
        any_study_designs=("case-report",),
        color="#9a7b4f",
    ),
    CategoryDef(
        id="protocols",
        label="Protocols",
        any_study_designs=("study-protocol",),
        color="#4a7c59",
    ),
    CategoryDef(
        id="narrative-reviews",
        label="Narrative reviews",
        any_types=("review",),
        color="#5c4d7a",
    ),
    CategoryDef(
        id="preprints",
        label="Preprints",
        any_types=("preprint", "posted-content"),
        color="#3d6b8a",
    ),
    CategoryDef(
        id="books",
        label="Books & chapters",
        any_types=("book", "book-chapter", "edited-book"),
        color="#6b5a3e",
    ),
    CategoryDef(
        id="commentary",
        label="Commentary / letters",
        any_types=("editorial", "letter", "paratext"),
        color="#7a7a7a",
    ),
)

DEFAULT_MAP_CATEGORIES: tuple[str, ...] = tuple(item.id for item in BUILT_IN_CATEGORIES)
_BUILT_IN_BY_ID = {item.id: item for item in BUILT_IN_CATEGORIES}


def parse_category_def(raw: Mapping[str, Any]) -> CategoryDef:
    """Parse one custom category table from config/profile."""
    cid = str(raw.get("id") or "").strip().lower().replace("_", "-").replace(" ", "-")
    if not cid:
        raise ValueError("map category needs an id")
    label = str(raw.get("label") or cid).strip() or cid
    designs = _strs(raw.get("any_study_designs") or raw.get("study_designs"))
    types = _strs(raw.get("any_types") or raw.get("types"))
    if not designs and not types:
        raise ValueError(f"map category {cid!r} needs any_study_designs or any_types")
    if designs:
        from .expand import normalize_study_design

        designs = tuple(normalize_study_design(item) for item in designs)
    color = str(raw.get("color") or "#5c6b7a").strip() or "#5c6b7a"
    return CategoryDef(
        id=cid,
        label=label,
        any_study_designs=designs,
        any_types=types,
        color=color,
    )


def parse_map_category_defs(raw: Any) -> tuple[dict[str, Any], ...]:
    """Normalize a list of category tables for Config storage."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("map_category_defs must be a list of tables")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("each map_category_defs entry must be a table")
        parsed = parse_category_def(item)
        if parsed.id in seen:
            raise ValueError(f"duplicate map category id {parsed.id!r}")
        seen.add(parsed.id)
        out.append(
            {
                "id": parsed.id,
                "label": parsed.label,
                "any_study_designs": list(parsed.any_study_designs),
                "any_types": list(parsed.any_types),
                "color": parsed.color,
            }
        )
    return tuple(out)


def parse_map_categories(raw: Any) -> tuple[str, ...]:
    """Parse enabled category ids (comma string or list)."""
    if raw is None:
        return DEFAULT_MAP_CATEGORIES
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
        return tuple(_norm_id(part) for part in parts)
    if isinstance(raw, (list, tuple)):
        return tuple(_norm_id(str(part)) for part in raw if str(part).strip())
    return DEFAULT_MAP_CATEGORIES


def resolve_catalog(
    *,
    enabled: Sequence[str] | None = None,
    custom_defs: Sequence[Mapping[str, Any]] | None = None,
) -> list[CategoryDef]:
    """Active category defs for map tagging, in display order."""
    catalog: dict[str, CategoryDef] = dict(_BUILT_IN_BY_ID)
    for raw in custom_defs or ():
        parsed = parse_category_def(raw) if not isinstance(raw, CategoryDef) else raw
        catalog[parsed.id] = parsed
    ids = list(enabled) if enabled is not None else list(DEFAULT_MAP_CATEGORIES)
    if enabled is None:
        # Default: all built-ins, then every custom def not already listed.
        for cid in catalog:
            if cid not in ids and cid not in _BUILT_IN_BY_ID:
                ids.append(cid)
    out: list[CategoryDef] = []
    seen: set[str] = set()
    for cid in ids:
        key = _norm_id(cid)
        if key in seen:
            continue
        defn = catalog.get(key)
        if defn is None:
            continue
        seen.add(key)
        out.append(defn)
    return out


def categories_for(
    biblio: Mapping[str, Any] | None,
    catalog: Sequence[CategoryDef],
) -> list[str]:
    """Category ids matched by this work's biblio, in catalog order."""
    designs = {
        str(item).strip().lower()
        for item in ((biblio or {}).get("study_designs") or [])
        if str(item).strip()
    }
    work_type = str((biblio or {}).get("type") or "").strip().lower()
    matched: list[str] = []
    for defn in catalog:
        if defn.any_study_designs and designs.intersection(defn.any_study_designs):
            matched.append(defn.id)
            continue
        if defn.any_types and work_type in {t.lower() for t in defn.any_types}:
            matched.append(defn.id)
    return matched


def study_designs_of(biblio: Mapping[str, Any] | None) -> list[str]:
    """Canonical study-design slugs from candidate biblio."""
    out: list[str] = []
    seen: set[str] = set()
    for item in (biblio or {}).get("study_designs") or []:
        slug = str(item).strip().lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return out


def legend_for(catalog: Sequence[CategoryDef]) -> list[dict[str, str]]:
    """Graph payload legend rows."""
    return [
        {"id": item.id, "label": item.label, "color": item.color} for item in catalog
    ]


def _strs(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return tuple(part.strip() for part in raw.replace(";", ",").split(",") if part.strip())
    if isinstance(raw, (list, tuple)):
        return tuple(str(part).strip() for part in raw if str(part).strip())
    return ()


def _norm_id(raw: str) -> str:
    return str(raw or "").strip().lower().replace("_", "-").replace(" ", "-")
