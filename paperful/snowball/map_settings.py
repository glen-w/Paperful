"""Knobs shared by every Discover map, from ``[map]`` or Settings → Maps.

View settings (colour, size, labels, fit, author panel) apply to citation
and Similar maps alike. The rest shape the citation map: how many papers it
draws, how far one Expand reaches, and the thresholds behind node roles.
Values are clamped here; bad values fall back to the default.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

from .similar_settings import _bool, _choice, _int

COLORS = ("role", "year", "category")
SIZES = ("citations", "uniform")
LABELS = ("auto", "all", "seeds", "none")
DIRECTIONS = ("both", "refs", "cites")
AUTHOR_LINKS = ("both", "coauthor")
VIEWS = ("papers", "authors")

_INT_LIMITS: dict[str, tuple[int, int]] = {
    "max_nodes": (20, 400),
    "neighbors": (5, 100),
    "ref_fetch_cap": (20, 1000),
    "recent_years": (1, 30),
    "citation_floor": (0, 100_000),
    "authors": (0, 50),
    "author_nodes": (5, 300),
    "author_min_papers": (1, 20),
    "author_peers": (1, 15),
}

# Keys Settings → Maps writes into [map].
MAP_SAVE_KEYS = (
    "color",
    "size_by",
    "labels",
    "fit",
    "authors",
    "max_nodes",
    "neighbors",
    "ref_fetch_cap",
    "recent_years",
    "citation_floor",
    "direction",
    "default_view",
    "author_nodes",
    "author_min_papers",
    "author_peers",
    "author_links",
)


@dataclass(frozen=True)
class MapSettings:
    color: str = "role"
    size_by: str = "citations"
    labels: str = "auto"
    fit: bool = True
    # Top authors listed beside the map (0 = off).
    authors: int = 12
    # Citation map only.
    max_nodes: int = 150
    neighbors: int = 25
    ref_fetch_cap: int = 200
    recent_years: int = 5
    citation_floor: int = 50
    direction: str = "both"
    # Author view: the map's papers redrawn as the people who wrote them.
    default_view: str = "papers"
    author_nodes: int = 60
    author_min_papers: int = 1
    author_peers: int = 5
    # both: co-authors plus authors whose papers are linked. coauthor: shared papers only.
    author_links: str = "both"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def view(self) -> dict[str, Any]:
        """What the browser needs to draw any map."""
        return {
            "color": self.color,
            "size_by": self.size_by,
            "labels": self.labels,
            "fit": self.fit,
            "authors": self.authors,
            "direction": self.direction,
            "default_view": self.default_view,
            "author_links": self.author_links,
        }

    def merged(self, raw: Mapping[str, Any] | None) -> "MapSettings":
        if not raw:
            return self
        out: dict[str, Any] = {}
        for key, allowed in (
            ("color", COLORS),
            ("size_by", SIZES),
            ("labels", LABELS),
            ("direction", DIRECTIONS),
            ("default_view", VIEWS),
            ("author_links", AUTHOR_LINKS),
        ):
            value = _choice(raw.get(key), allowed)
            if value:
                out[key] = value
        for key, (lo, hi) in _INT_LIMITS.items():
            value = _int(raw.get(key))
            if value is not None:
                out[key] = max(lo, min(hi, value))
        if "fit" in raw:
            out["fit"] = _bool(raw.get("fit"))
        return replace(self, **out)


DEFAULT = MapSettings()


def from_mapping(raw: Mapping[str, Any] | None) -> MapSettings:
    return DEFAULT.merged(raw)


def for_config(cfg: Any) -> MapSettings:
    found = getattr(cfg, "map_settings", None)
    return found if isinstance(found, MapSettings) else DEFAULT
