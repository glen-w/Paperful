"""Load a kind=snowball profile. run and all refuse these files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..config import Config
from ..run_config import profiles_dir
from .command import SnowballError, SnowballRequest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def load_profile(cfg: Config, name: str) -> dict[str, Any]:
    path = profiles_dir(cfg) / f"{name}.toml"
    raw: dict[str, Any] | None = None
    if path.is_file():
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
        if isinstance(loaded, dict):
            raw = loaded
    if raw is None:
        table = cfg.run_profiles.get(name)
        if isinstance(table, dict):
            raw = dict(table)
    if raw is None:
        raise SnowballError(f"Unknown snowball profile {name!r}.")
    if str(raw.get("kind") or "") != "snowball":
        raise SnowballError(f"Profile {name!r} is not kind = snowball.")
    return raw


def request_from_profile(raw: dict[str, Any], cfg: Config) -> SnowballRequest:
    depth = raw.get("depth")
    max_candidates = raw.get("max_candidates")
    per_hop = raw.get("per_hop_limit")
    return SnowballRequest(
        gate=str(raw.get("gate") or cfg.snowball_gate),
        collection=str(raw.get("target_collection") or cfg.snowball_target_collection or ""),
        fetch_pdfs=bool(raw.get("fetch_pdfs", cfg.snowball_fetch_pdfs)),
        depth=int(depth) if depth is not None else None,
        max_candidates=int(max_candidates) if max_candidates is not None else None,
        per_hop_limit=int(per_hop) if per_hop is not None else None,
        year_from=int(raw["year_from"]) if raw.get("year_from") is not None else None,
        year_to=int(raw["year_to"]) if raw.get("year_to") is not None else None,
        direction=str(raw.get("direction") or "refs"),
    )


def profile_path(cfg: Config, name: str) -> Path:
    return profiles_dir(cfg) / f"{name}.toml"
