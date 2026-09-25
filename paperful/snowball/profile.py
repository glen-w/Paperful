"""Load a kind=snowball profile. run and all refuse these files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..config import Config, parse_cap, parse_fetch_pdfs, parse_per_hop_rank
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


def _profile_pdf_mode(value: Any) -> str:
    try:
        return parse_fetch_pdfs(value)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc


def _profile_cap(value: Any) -> int:
    try:
        return parse_cap(value)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc


def _profile_rank(value: Any) -> str:
    try:
        return parse_per_hop_rank(value)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc


def request_from_profile(raw: dict[str, Any], cfg: Config) -> SnowballRequest:
    depth = raw.get("depth")
    max_candidates = raw.get("max_candidates")
    per_hop = raw.get("per_hop_limit")
    return SnowballRequest(
        gate=str(raw.get("gate") or cfg.snowball_gate),
        collection=str(raw.get("target_collection") or cfg.snowball_target_collection or ""),
        fetch_pdfs=(
            _profile_pdf_mode(raw["fetch_pdfs"])
            if "fetch_pdfs" in raw
            else cfg.snowball_fetch_pdfs
        ),
        depth=int(depth) if depth is not None else None,
        max_candidates=_profile_cap(max_candidates) if max_candidates is not None else None,
        per_hop_limit=_profile_cap(per_hop) if per_hop is not None else None,
        per_hop_rank=_profile_rank(raw["per_hop_rank"]) if raw.get("per_hop_rank") else None,
        year_from=int(raw["year_from"]) if raw.get("year_from") is not None else None,
        year_to=int(raw["year_to"]) if raw.get("year_to") is not None else None,
        direction=str(raw.get("direction") or cfg.snowball_direction or "refs"),
        keyword_limit=raw.get("keyword_limit"),
        keyword_hop_limit=raw.get("keyword_hop_limit"),
        keyword_min_score=raw.get("keyword_min_score"),
        dedupe_scope=str(raw["dedupe_scope"]) if raw.get("dedupe_scope") else None,
        tag_prefix=str(raw["tag_prefix"]) if raw.get("tag_prefix") else None,
        types=_strs(raw.get("types")) if "types" in raw else None,
        oa_only=bool(raw["oa_only"]) if "oa_only" in raw else None,
        venue_include=_strs(raw.get("venue_include")) if "venue_include" in raw else None,
        venue_exclude=_strs(raw.get("venue_exclude")) if "venue_exclude" in raw else None,
        languages=_strs(raw.get("languages")) if "languages" in raw else None,
        min_seed_citations=int(raw["min_seed_citations"]) if raw.get("min_seed_citations") is not None else None,
        note_provenance=bool(raw["note_provenance"]) if "note_provenance" in raw else None,
        backends=_strs(raw.get("backends")) if "backends" in raw else None,
        hybrid_seeds=int(raw["hybrid_seeds"]) if raw.get("hybrid_seeds") is not None else None,
        approve_each_max=int(raw["approve_each_max"]) if raw.get("approve_each_max") is not None else None,
        refine=bool(raw["refine"]) if "refine" in raw else None,
    )


def profile_path(cfg: Config, name: str) -> Path:
    return profiles_dir(cfg) / f"{name}.toml"


_SECRET = ("api_key", "apikey", "token", "password", "secret", "mailto")


def _strs(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    if isinstance(raw, list):
        return tuple(str(part).strip() for part in raw if str(part).strip())
    return ()


def save_profile(cfg: Config, name: str, body: dict[str, Any], *, force: bool) -> Path:
    """Write seeds and knobs only. Refuses keys. A writing gate needs --force."""
    from ..run_config import check_profile_name

    check_profile_name(name)
    if cfg.config_path is None:
        raise SnowballError("No config.toml found. Pass --config so the profile is saved beside it.")
    _refuse_secrets(body)
    gate = str(body.get("gate") or "dry-run")
    if gate != "dry-run" and not force:
        raise SnowballError("Saving a writing gate needs --force after a dry-run of that job.")
    path = profile_path(cfg, name)
    if path.exists() and not force:
        raise SnowballError(f"{path} already exists. Pass --force to overwrite.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(name, body), encoding="utf-8")
    return path


def _refuse_secrets(body: dict[str, Any]) -> None:
    for key, value in body.items():
        lowered = key.lower().replace("-", "_")
        if any(token in lowered for token in _SECRET):
            raise SnowballError("Refusing to store a key.")
        if isinstance(value, str) and any(token in value.lower() for token in ("api_key", "openapi_key", "bearer ")):
            raise SnowballError("Refusing to store a key.")


def _render(name: str, body: dict[str, Any]) -> str:
    lines = [
        f"# paperful snowball profile. Select with: paperful snowball run --profile {name}",
        'kind = "snowball"',
    ]
    for key, value in body.items():
        if value is None or value == "" or value == [] or value == ():
            continue
        lines.append(f"{key} = {_toml(value)}")
    lines.append("")
    return "\n".join(lines)


def _toml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, (list, tuple)):
        inner = ", ".join(_toml(item) for item in value)
        return f"[{inner}]"
    return json_string(str(value))


def json_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
