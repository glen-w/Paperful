"""Named year windows for slicing an ego co-authorship graph."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


@dataclass(frozen=True)
class Phase:
    id: str
    label: str
    year_from: int | None
    year_to: int | None

    def contains(self, year: int | None) -> bool:
        if year is None:
            return False
        if self.year_from is not None and year < self.year_from:
            return False
        if self.year_to is not None and year > self.year_to:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "year_from": self.year_from,
            "year_to": self.year_to,
        }


BBNJ_PHASES: tuple[Phase, ...] = (
    Phase("pre-2006", "Pre-2006", None, 2005),
    Phase("adhoc", "Ad Hoc Working Group", 2006, 2015),
    Phase("prepcom", "PrepCom", 2016, 2017),
    Phase("igc", "Intergovernmental conference", 2018, 2023),
    Phase("post-adoption", "Post-adoption", 2023, 2025),
)

_PRESETS: dict[str, tuple[Phase, ...]] = {"bbnj": BBNJ_PHASES}


def load_phases(spec: str | Path | None) -> tuple[Phase, ...]:
    """Load a named preset (``bbnj``) or a ``[[phases]]`` TOML file."""
    text = str(spec or "bbnj").strip()
    if not text:
        return BBNJ_PHASES
    key = text.lower()
    if key in _PRESETS:
        return _PRESETS[key]
    path = Path(text).expanduser()
    if not path.is_file():
        known = ", ".join(sorted(_PRESETS))
        raise ValueError(
            f"Unknown phase preset {text!r}. Use {known}, or a TOML file with [[phases]]."
        )
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    rows = raw.get("phases") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path} has no [[phases]] table.")
    out: list[Phase] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "").strip()
        if not pid or pid in seen:
            raise ValueError(f"{path}: each phase needs a unique id.")
        seen.add(pid)
        year_from = row.get("year_from")
        year_to = row.get("year_to")
        out.append(
            Phase(
                id=pid,
                label=str(row.get("label") or pid),
                year_from=int(year_from) if year_from is not None else None,
                year_to=int(year_to) if year_to is not None else None,
            )
        )
    if not out:
        raise ValueError(f"{path} has no usable [[phases]] rows.")
    return tuple(out)


def slice_graph(graph: dict[str, Any], phase: Phase) -> dict[str, Any]:
    """Keep edges whose ``years`` intersect the phase, and the nodes they touch."""
    keep_ids: set[str] = set()
    edges: list[dict[str, Any]] = []
    for edge in graph.get("edges") or []:
        years = [int(y) for y in (edge.get("years") or []) if _is_int(y)]
        hit = [y for y in years if phase.contains(y)]
        if not hit:
            continue
        left = str(edge.get("a") or edge.get("source") or "")
        right = str(edge.get("b") or edge.get("target") or "")
        if not left or not right:
            continue
        keep_ids.add(left)
        keep_ids.add(right)
        edges.append(
            {
                "a": left,
                "b": right,
                "weight": len(hit) if years else int(edge.get("weight") or 0),
                "years": hit,
            }
        )
    ego = str((graph.get("ego") or {}).get("id") or "")
    if ego:
        keep_ids.add(ego)
    nodes = [
        dict(node)
        for node in graph.get("nodes") or []
        if str(node.get("id") or "") in keep_ids
    ]
    return {
        "schema": graph.get("schema") or "",
        "ego": dict(graph.get("ego") or {}),
        "phase": phase.to_dict(),
        "nodes": nodes,
        "edges": edges,
    }


def _is_int(value: Any) -> bool:
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True
