"""Composable critique review lanes. Suggested extras only; checkers always run.

Paperful owns orchestration. Do not vendor allenai/marg-reviewer or ScholarPeer.
``--llm`` / ``--advanced`` remain aliases for ``reviewers`` / ``marg``.
"""

from __future__ import annotations

from typing import Any, Iterable

KNOWN_LANES = ("reviewers", "marg", "adversary", "context", "context-web")
LANE_ALIASES = {
    "llm": "reviewers",
    "standard": "reviewers",
    "advanced": "marg",
}


def canonical_lane(name: str) -> str:
    raw = str(name or "").strip().lower()
    raw = LANE_ALIASES.get(raw, raw)
    if raw not in KNOWN_LANES:
        raise ValueError(
            f"unknown critique lane {name!r} (want {', '.join(KNOWN_LANES)})"
        )
    return raw


def parse_critique_lanes(raw: Any) -> tuple[str, ...]:
    """Parse ``[critique].lanes`` (list or comma-separated). Empty is valid."""
    if raw is None or raw == "":
        return ()
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, list):
        parts = [str(part).strip() for part in raw if str(part).strip()]
    else:
        raise ValueError("[critique].lanes must be an array of lane ids")
    return ordered_lanes(canonical_lane(p) for p in parts)


def ordered_lanes(lanes: Iterable[str]) -> tuple[str, ...]:
    seen = {canonical_lane(x) for x in lanes if str(x).strip()}
    return tuple(name for name in KNOWN_LANES if name in seen)


def mode_for_lanes(lanes: Iterable[str]) -> str:
    """Deprecated pack ``llm.mode`` for readers that still expect it."""
    names = set(ordered_lanes(lanes))
    has_r = "reviewers" in names
    has_m = "marg" in names
    if has_r and has_m:
        return "both"
    if has_m:
        return "marg"
    if has_r:
        return "default"
    if "adversary" in names:
        return "adversary"
    if "context-web" in names:
        return "context-web"
    if "context" in names:
        return "context"
    return "default"


def lanes_need_llm(lanes: Iterable[str]) -> bool:
    return bool(ordered_lanes(lanes))


def resolve_critique_lanes(
    cfg: Any,
    *,
    lane_flags: list[str] | None = None,
    llm: bool | None = None,
    advanced: bool | None = None,
) -> tuple[str, ...]:
    """Resolve one-run lanes from ``--lane`` plus config / bool shims.

    Base set: CLI ``--lane`` if any; else ``[critique].lanes`` when non-empty
    (config ``llm`` / ``advanced`` ignored); else map those bools (CLI overlay
    of config). Then ``--llm`` / ``--no-llm`` and ``--advanced`` /
    ``--no-advanced`` add or remove ``reviewers`` / ``marg``.
    """
    flags = [canonical_lane(x) for x in (lane_flags or []) if str(x).strip()]
    config_lanes = ordered_lanes(getattr(cfg, "critique_lanes", ()) or ())
    if flags:
        base = list(dict.fromkeys(flags))
        overlay = True
    elif config_lanes:
        base = list(config_lanes)
        overlay = True
    else:
        want_r = cfg.critique_llm if llm is None else bool(llm)
        want_m = cfg.critique_advanced if advanced is None else bool(advanced)
        base = []
        if want_r:
            base.append("reviewers")
        if want_m:
            base.append("marg")
        overlay = False
    if overlay:
        if llm is True and "reviewers" not in base:
            base.append("reviewers")
        if llm is False:
            base = [name for name in base if name != "reviewers"]
        if advanced is True and "marg" not in base:
            base.append("marg")
        if advanced is False:
            base = [name for name in base if name != "marg"]
    return ordered_lanes(base)
