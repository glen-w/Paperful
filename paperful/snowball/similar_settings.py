"""Knobs for the Similar map, from ``[similar_map]`` or the Explore form.

Every value is clamped here, so config, Settings, and the per-map form share
one set of limits. Unknown keys and bad values fall back to the default.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

# refs, citers, co-cited, partner refs, partners per ref
POOL_PRESETS: dict[str, tuple[int, int, int, int, int]] = {
    "small": (100, 60, 30, 4, 15),
    "standard": (200, 150, 60, 8, 25),
    "large": (400, 300, 120, 16, 40),
}
SOURCES = ("auto", "store", "api")
COLORS = ("role", "year")

_INT_LIMITS: dict[str, tuple[int, int]] = {
    "nodes": (5, 150),
    "peers": (1, 10),
    "ref_cap": (0, 1000),
    "citer_cap": (0, 1000),
    "cocited_cap": (0, 500),
    "partner_refs": (0, 40),
    "partners_per_ref": (1, 200),
    "prior_works": (0, 50),
    "derivative_works": (0, 50),
}
_FLOAT_LIMITS: dict[str, tuple[float, float]] = {
    "min_similarity": (0.0, 1.0),
    "coupling_weight": (0.0, 1.0),
}
_POOL_KEYS = ("ref_cap", "citer_cap", "cocited_cap", "partner_refs", "partners_per_ref")


@dataclass(frozen=True)
class SimilarSettings:
    """Similar map settings. Defaults match the first release of the map."""

    nodes: int = 40
    peers: int = 4
    min_similarity: float = 0.02
    # 0 = co-citation only, 1 = shared references only.
    coupling_weight: float = 0.5
    pool: str = "standard"
    ref_cap: int = 200
    citer_cap: int = 150
    cocited_cap: int = 60
    partner_refs: int = 8
    partners_per_ref: int = 25
    year_from: int | None = None
    year_to: int | None = None
    hide_in_library: bool = False
    prior_works: int = 10
    derivative_works: int = 10
    color: str = "role"
    # auto: store first, then the live API. store: never call the API. api: ignore the store.
    source: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def merged(self, raw: Mapping[str, Any] | None) -> "SimilarSettings":
        """A copy with ``raw`` applied on top. Bad values keep the current one."""
        if not raw:
            return self
        out: dict[str, Any] = {}
        pool = _choice(raw.get("pool"), tuple(POOL_PRESETS))
        if pool:
            out["pool"] = pool
            out.update(dict(zip(_POOL_KEYS, POOL_PRESETS[pool])))
        for key, (lo, hi) in _INT_LIMITS.items():
            value = _int(raw.get(key))
            if value is not None:
                out[key] = max(lo, min(hi, value))
        for key, (lo, hi) in _FLOAT_LIMITS.items():
            value = _float(raw.get(key))
            if value is not None:
                out[key] = max(lo, min(hi, value))
        for key in ("year_from", "year_to"):
            if key in raw:
                value = _int(raw.get(key))
                out[key] = value if value is not None and 1000 <= value <= 3000 else None
        if "hide_in_library" in raw:
            out["hide_in_library"] = _bool(raw.get("hide_in_library"))
        color = _choice(raw.get("color"), COLORS)
        if color:
            out["color"] = color
        source = _choice(raw.get("source"), SOURCES)
        if source:
            out["source"] = source
        merged = replace(self, **out)
        if (
            merged.year_from is not None
            and merged.year_to is not None
            and merged.year_from > merged.year_to
        ):
            merged = replace(merged, year_from=merged.year_to, year_to=merged.year_from)
        return merged


DEFAULT = SimilarSettings()

# Keys Settings writes into [similar_map]. Pool caps stay config-only overrides.
SIMILAR_SAVE_KEYS = (
    "nodes",
    "peers",
    "min_similarity",
    "coupling_weight",
    "pool",
    "year_from",
    "year_to",
    "hide_in_library",
    "prior_works",
    "derivative_works",
    "color",
    "source",
)


def toml_literal(value: Any) -> str:
    """TOML literal for a settings value. ``None`` years are written as 0 (= any)."""
    if value is None:
        return "0"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def from_mapping(raw: Mapping[str, Any] | None) -> SimilarSettings:
    return DEFAULT.merged(raw)


def for_config(cfg: Any) -> SimilarSettings:
    found = getattr(cfg, "similar_map", None)
    return found if isinstance(found, SimilarSettings) else DEFAULT


def _choice(value: Any, allowed: tuple[str, ...]) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else ""


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number == number else None  # drop NaN


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
