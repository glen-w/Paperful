"""Shared heading synonyms for chunking and section extract."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config

try:
    import tomllib
except ImportError:
    import tomli as tomllib

# canonical -> synonym phrases (lowercase, no trailing colon)
_SHIPPED: dict[str, tuple[str, ...]] = {
    "abstract": ("abstract", "summary"),
    "introduction": ("introduction", "background"),
    "methodology": (
        "methods",
        "method",
        "methodology",
        "materials and methods",
        "material and methods",
        "experimental methods",
        "study design",
    ),
    "results": ("results", "results and discussion", "findings"),
    "discussion": ("discussion",),
    "conclusion": ("conclusion", "conclusions", "concluding remarks"),
    "research_questions": (
        "research questions",
        "research question",
        "research aims",
        "aims and objectives",
        "aims",
        "objectives",
        "questions addressed",
    ),
    "limitations": ("limitations", "limitation", "study limitations"),
    "references": ("references", "bibliography", "works cited"),
    "acknowledgements": ("acknowledgements", "acknowledgments", "acknowledgement"),
    "appendix": ("appendix", "appendices", "supplementary material"),
}

# MVP field -> canonical section keys used to fill that field
MVP_CANONICALS: dict[str, tuple[str, ...]] = {
    "abstract": ("abstract",),
    "methodology": ("methodology",),
    "conclusion": ("conclusion",),
    "research_questions": ("research_questions",),
}

DEFAULT_MVP_FIELDS: tuple[str, ...] = (
    "abstract",
    "conclusion",
    "methodology",
    "research_questions",
)

_OVERLAY_CACHE: dict[str, dict[str, tuple[str, ...]]] = {}


def _build_maps(
    extra: dict[str, tuple[str, ...]] | None = None,
) -> tuple[frozenset[str], dict[str, str]]:
    """All lowercase synonym phrases and synonym -> canonical."""
    canon: dict[str, tuple[str, ...]] = {k: v for k, v in _SHIPPED.items()}
    if extra:
        for key, syns in extra.items():
            canon_key = key.strip().lower()
            if not canon_key:
                continue
            merged = tuple(dict.fromkeys((*canon.get(canon_key, ()), *syns)))
            canon[canon_key] = merged
    named: set[str] = set()
    to_canon: dict[str, str] = {}
    for canonical, syns in canon.items():
        for phrase in syns:
            p = phrase.strip().lower().rstrip(":")
            if not p:
                continue
            named.add(p)
            to_canon[p] = canonical
        named.add(canonical)
        to_canon[canonical] = canonical
    return frozenset(named), to_canon


def named_headings_set(cfg: Config | None = None) -> frozenset[str]:
    """Lowercase heading phrases recognized as section titles (for the chunker)."""
    return heading_maps(cfg)[0]


def heading_maps(cfg: Config | None = None) -> tuple[frozenset[str], dict[str, str]]:
    cache_key = _overlay_key(cfg)
    if cache_key not in _OVERLAY_CACHE:
        _OVERLAY_CACHE[cache_key] = _load_overlay(cfg)
    extra = _OVERLAY_CACHE[cache_key]
    return _build_maps(extra)


def _overlay_key(cfg: Config | None) -> str:
    if cfg is None:
        return ""
    parts = [str(cfg.state_dir), (cfg.extract_sections_headings or "").strip()]
    return "|".join(parts)


def _load_overlay(cfg: Config | None) -> dict[str, tuple[str, ...]]:
    if cfg is None:
        return {}
    paths: list[Path] = []
    custom = (cfg.extract_sections_headings or "").strip()
    if custom:
        p = Path(custom).expanduser()
        if not p.is_absolute() and cfg.config_path:
            p = (cfg.config_path.parent / p).resolve()
        paths.append(p)
    default = cfg.state_dir / "section-headings.toml"
    if default.is_file() and default not in paths:
        paths.append(default)
    out: dict[str, tuple[str, ...]] = {}
    for path in paths:
        if not path.is_file():
            continue
        try:
            with path.open("rb") as fh:
                raw = tomllib.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            canon = key.strip().lower()
            if not canon:
                continue
            if isinstance(value, str):
                syns = (value.strip().lower(),)
            elif isinstance(value, list):
                syns = tuple(
                    str(v).strip().lower() for v in value if str(v).strip()
                )
            else:
                continue
            prev = out.get(canon, ())
            out[canon] = tuple(dict.fromkeys((*prev, *syns)))
    return out


def normalize_heading_line(line: str) -> str:
    return line.strip().rstrip(":").strip().lower()


def canonical_for_heading(heading: str, cfg: Config | None = None) -> str | None:
    """Map a detected section title to a canonical key, if known."""
    _, to_canon = heading_maps(cfg)
    key = normalize_heading_line(heading)
    if key in to_canon:
        return to_canon[key]
    # Strip leading numbering: "1. Introduction" -> "introduction"
    import re

    stripped = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", key).strip()
    return to_canon.get(stripped)


def clear_heading_cache() -> None:
    _OVERLAY_CACHE.clear()
