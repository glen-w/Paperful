"""Named run configs (SCOPE + policy), distinct from grey playbooks and packs.

Files live beside ``config.toml`` (``profiles/<name>.toml`` or ``[profiles.<name>]``).
They are not stored under ``state/``.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import SOURCE_PRESETS, Config
from .zot import resolve_item_types

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

# Default `paperful all` chain. Optional steps are allowed in a profile, not here.
DEFAULT_ALL_STEPS: tuple[str, ...] = (
    "gaps",
    "run",
    "lint",
    "fix-metadata",
    "summarize",
)
OPTIONAL_STEPS: tuple[str, ...] = ("snapshot", "synthesize", "dedupe")
KNOWN_STEPS: tuple[str, ...] = DEFAULT_ALL_STEPS + OPTIONAL_STEPS

# Filled in only for `paperful all` / `profile show`, and only when the profile omits them.
ALL_POLICY: dict[str, Any] = {
    "steps": list(DEFAULT_ALL_STEPS),
    "try_all": True,
    "retry_failed": True,
    "upgrade_linked": True,
    "apply": True,
    "require_summarize": False,
}

PROFILE_KEYS = frozenset(
    {
        "name",
        "description",
        "collections",
        "library",
        "types",
        "year_from",
        "year_to",
        "try_all",
        "retry_failed",
        "upgrade_linked",
        "no_attach",
        "scihub",
        "preset",
        "sources",
        "limit",
        "steps",
        "apply",
        "overwrite",
        "require_summarize",
    }
)
SCOPE_KEYS = frozenset(
    {"collections", "library", "types", "year_from", "year_to", "description", "limit"}
)
RUN_KEYS = frozenset(
    {
        "try_all",
        "retry_failed",
        "upgrade_linked",
        "no_attach",
        "scihub",
        "preset",
        "sources",
    }
)
APPLY_KEYS = frozenset({"apply", "overwrite"})
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DUMP_ORDER = (
    "description",
    "collections",
    "library",
    "types",
    "year_from",
    "year_to",
    "try_all",
    "retry_failed",
    "upgrade_linked",
    "no_attach",
    "scihub",
    "preset",
    "sources",
    "limit",
    "steps",
    "apply",
    "overwrite",
    "require_summarize",
)


class RunConfigError(ValueError):
    """A run config is missing, malformed, or conflicts with the flags."""


@dataclass
class ProfileListing:
    name: str
    source: str
    description: str
    path: Path | None = None


@dataclass
class ResolvedRunConfig:
    """Effective SCOPE and policy after builtin, profile, file, and CLI merge."""

    name: str | None = None
    description: str = ""
    collections: list[str] = field(default_factory=list)
    library: bool = False
    types: list[str] = field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    try_all: bool = False
    retry_failed: bool = False
    upgrade_linked: bool = False
    no_attach: bool = False
    scihub: bool = False
    preset: str | None = None
    sources: list[str] = field(default_factory=list)
    limit: int | None = None
    steps: list[str] = field(default_factory=list)
    apply: bool = False
    overwrite: bool = False
    require_summarize: bool = False
    origins: tuple[str, ...] = ()

    @property
    def sources_csv(self) -> str | None:
        if not self.sources:
            return None
        return ",".join(self.sources)


def profiles_dir(cfg: Config) -> Path:
    """Directory of ``*.toml`` run configs beside the loaded config file."""
    if cfg.config_path is not None:
        return cfg.config_path.parent / "profiles"
    return Path.cwd() / "profiles"


def list_profiles(cfg: Config) -> list[ProfileListing]:
    """Saved profiles only. The builtin ``all`` policy is not a named profile."""
    names = set(cfg.run_profiles)
    folder = profiles_dir(cfg)
    files: dict[str, Path] = {}
    if folder.is_dir():
        for path in sorted(folder.glob("*.toml")):
            if path.is_file() and _NAME_RE.match(path.stem):
                names.add(path.stem)
                files[path.stem] = path
    listings: list[ProfileListing] = []
    for name in sorted(names):
        in_table = name in cfg.run_profiles
        path = files.get(name)
        if in_table and path is not None:
            source = "config.toml+file"
        elif path is not None:
            source = "file"
        else:
            source = "config.toml"
        description = ""
        try:
            layer = _named_layer(cfg, name)
            description = str(layer.get("description") or "")
        except RunConfigError as exc:
            description = f"invalid: {exc}"
        listings.append(
            ProfileListing(name=name, source=source, description=description, path=path)
        )
    return listings


def resolve_run_config(
    cfg: Config,
    *,
    for_all: bool = False,
    use_run_policy: bool = False,
    use_apply: bool = False,
    profile: str | None = None,
    run_config: Path | None = None,
    collection: list[str] | None = None,
    library: bool | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    item_type: list[str] | None = None,
    try_all: bool | None = None,
    retry_failed: bool | None = None,
    upgrade_linked: bool | None = None,
    no_attach: bool | None = None,
    scihub: bool | None = None,
    apply: bool | None = None,
    overwrite: bool | None = None,
    limit: int | None = None,
    sources: str | None = None,
    preset: str | None = None,
    steps: str | list[str] | None = None,
    skip: list[str] | None = None,
    require_summarize: bool | None = None,
) -> ResolvedRunConfig:
    """Merge builtin ``all`` policy, named profile, file, then explicit CLI flags.

    ``for_all`` fills steps and the default run flags (try-all, retry-failed,
    upgrade-linked, apply) when the profile omits them. A bare ``run --profile``
    does not get those defaults.
    """
    body: dict[str, Any] = {}
    origins: list[str] = []
    if for_all:
        body.update(ALL_POLICY)
        body["steps"] = list(DEFAULT_ALL_STEPS)
        origins.append("builtin all")

    if profile:
        body.update(
            _filter_layer(
                _named_layer(cfg, profile),
                for_all=for_all,
                use_run_policy=use_run_policy,
                use_apply=use_apply,
            )
        )
        origins.append(f"profile {profile}")
    if run_config is not None:
        _file_name, file_body = _load_explicit_file(run_config)
        body.update(
            _filter_layer(
                file_body,
                for_all=for_all,
                use_run_policy=use_run_policy,
                use_apply=use_apply,
            )
        )
        origins.append(str(run_config))

    _apply_cli(
        body,
        for_all=for_all,
        use_run_policy=use_run_policy,
        use_apply=use_apply,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        try_all=try_all,
        retry_failed=retry_failed,
        upgrade_linked=upgrade_linked,
        no_attach=no_attach,
        scihub=scihub,
        apply=apply,
        overwrite=overwrite,
        limit=limit,
        sources=sources,
        preset=preset,
        steps=steps,
        skip=skip,
        require_summarize=require_summarize,
    )
    if collection or library is not None or (item_type or []) or year_from is not None or year_to is not None or any(
        flag is not None
        for flag in (
            try_all,
            retry_failed,
            upgrade_linked,
            no_attach,
            scihub,
            apply,
            overwrite,
            limit,
            sources,
            preset,
            steps,
            require_summarize,
        )
    ) or (skip or []):
        origins.append("cli")

    resolved = _finalize(body, for_all=for_all)
    resolved.name = profile or _name_from_file(run_config)
    resolved.origins = tuple(origins)
    return resolved


def collect_save_body(
    cfg: Config,
    *,
    profile: str | None = None,
    run_config: Path | None = None,
    collection: list[str] | None = None,
    library: bool | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    item_type: list[str] | None = None,
    try_all: bool | None = None,
    retry_failed: bool | None = None,
    upgrade_linked: bool | None = None,
    no_attach: bool | None = None,
    scihub: bool | None = None,
    apply: bool | None = None,
    overwrite: bool | None = None,
    limit: int | None = None,
    sources: str | None = None,
    preset: str | None = None,
    steps: str | list[str] | None = None,
    skip: list[str] | None = None,
    require_summarize: bool | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Profile + explicit flags, without builtin ``all`` defaults."""
    body: dict[str, Any] = {}
    if profile:
        body.update(_named_layer(cfg, profile))
    if run_config is not None:
        _file_name, file_body = _load_explicit_file(run_config)
        body.update(file_body)
    body.pop("name", None)
    _apply_cli(
        body,
        for_all=True,
        use_run_policy=True,
        use_apply=True,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        try_all=try_all,
        retry_failed=retry_failed,
        upgrade_linked=upgrade_linked,
        no_attach=no_attach,
        scihub=scihub,
        apply=apply,
        overwrite=overwrite,
        limit=limit,
        sources=sources,
        preset=preset,
        steps=steps,
        skip=skip,
        require_summarize=require_summarize,
    )
    if description is not None and description.strip():
        body["description"] = description.strip()
    body.pop("name", None)
    if not body:
        raise RunConfigError(
            "Nothing to save. Pass scope flags, --profile, or --run-config."
        )
    _finalize(dict(body), for_all=False)
    return body


def save_profile(cfg: Config, name: str, body: dict[str, Any], *, force: bool) -> Path:
    """Write ``profiles/<name>.toml`` beside the active config. Does not edit config.toml."""
    check_profile_name(name)
    if cfg.config_path is None:
        raise RunConfigError(
            "No config.toml found. Pass --config so the profile is saved beside it."
        )
    path = profiles_dir(cfg) / f"{name}.toml"
    if path.exists() and not force:
        raise RunConfigError(f"{path} already exists. Pass --force to overwrite.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_profile_toml(name, body), encoding="utf-8")
    return path


def render_profile_toml(name: str, body: dict[str, Any]) -> str:
    lines = [
        f"# paperful run config. Select with: paperful all --profile {name}",
        f"name = {_toml_str(name)}",
    ]
    for key in _DUMP_ORDER:
        if key not in body:
            continue
        value = body[key]
        if value is None:
            continue
        if isinstance(value, str) and not value:
            continue
        if isinstance(value, list) and not value and key != "steps":
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    lines.append("")
    return "\n".join(lines)


def format_effective(resolved: ResolvedRunConfig) -> str:
    """TOML view of what ``paperful all`` would use, defaults included."""
    body: dict[str, Any] = {
        "try_all": resolved.try_all,
        "retry_failed": resolved.retry_failed,
        "upgrade_linked": resolved.upgrade_linked,
        "apply": resolved.apply,
        "require_summarize": resolved.require_summarize,
        "steps": list(resolved.steps),
    }
    if resolved.description:
        body["description"] = resolved.description
    if resolved.collections:
        body["collections"] = list(resolved.collections)
    if resolved.library:
        body["library"] = True
    if resolved.types:
        body["types"] = list(resolved.types)
    if resolved.year_from is not None:
        body["year_from"] = resolved.year_from
    if resolved.year_to is not None:
        body["year_to"] = resolved.year_to
    if resolved.no_attach:
        body["no_attach"] = True
    if resolved.scihub:
        body["scihub"] = True
    if resolved.preset:
        body["preset"] = resolved.preset
    if resolved.sources:
        body["sources"] = list(resolved.sources)
    if resolved.limit is not None:
        body["limit"] = resolved.limit
    if resolved.overwrite:
        body["overwrite"] = True
    title = resolved.name or "all"
    return render_profile_toml(title, body)


def check_profile_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise RunConfigError(
            f"Invalid profile name {name!r}. "
            "Use letters, digits, '.', '_' or '-', starting with a letter or digit."
        )


def _named_layer(cfg: Config, name: str) -> dict[str, Any]:
    check_profile_name(name)
    table = cfg.run_profiles.get(name)
    path = profiles_dir(cfg) / f"{name}.toml"
    file_body: dict[str, Any] | None = None
    if path.is_file():
        file_body = _normalize(_load_toml(path), expect_name=name)
        file_body.pop("name", None)
    if table is None and file_body is None:
        known = ", ".join(item.name for item in list_profiles(cfg)) or "(none)"
        raise RunConfigError(f"Unknown run profile {name!r}. Known: {known}")
    merged: dict[str, Any] = {}
    if table is not None:
        normalized = _normalize(dict(table), expect_name=name)
        normalized.pop("name", None)
        merged.update(normalized)
    if file_body:
        merged.update(file_body)
    return merged


def _load_explicit_file(path: Path) -> tuple[str, dict[str, Any]]:
    raw = _load_toml(path)
    body = _normalize(raw, expect_name=None)
    name = str(body.pop("name", "") or path.stem)
    check_profile_name(name)
    return name, body


def _name_from_file(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        name, _body = _load_explicit_file(path)
    except RunConfigError:
        return path.stem
    return name


def _filter_layer(
    layer: dict[str, Any],
    *,
    for_all: bool,
    use_run_policy: bool,
    use_apply: bool,
) -> dict[str, Any]:
    """Keep keys this command actually consumes. ``all`` keeps the full profile."""
    if for_all:
        return dict(layer)
    kept: dict[str, Any] = {}
    for key, value in layer.items():
        if key in SCOPE_KEYS or key in {"name", "description", "steps"}:
            kept[key] = value
        elif key in RUN_KEYS and use_run_policy:
            kept[key] = value
        elif key in APPLY_KEYS and use_apply:
            kept[key] = value
    return kept


def _apply_cli(body: dict[str, Any], **flags: Any) -> None:
    collection = flags["collection"] or []
    library = flags["library"]
    if collection:
        body["collections"] = [str(item) for item in collection]
        if library is not True:
            body["library"] = False
    elif library is True:
        body["library"] = True
        body["collections"] = []
    elif library is False:
        body["library"] = False
    if flags["year_from"] is not None:
        body["year_from"] = flags["year_from"]
    if flags["year_to"] is not None:
        body["year_to"] = flags["year_to"]
    item_type = flags["item_type"] or []
    if item_type:
        body["types"] = [str(item) for item in item_type]
    if flags["limit"] is not None:
        body["limit"] = flags["limit"]
    for key in ("try_all", "retry_failed", "upgrade_linked", "no_attach", "scihub"):
        if flags[key] is not None:
            body[key] = flags[key]
    if flags["sources"] is not None:
        body["sources"] = [
            part.strip() for part in str(flags["sources"]).split(",") if part.strip()
        ]
    if flags["preset"] is not None and str(flags["preset"]).strip():
        body["preset"] = str(flags["preset"]).strip()
    if flags["apply"] is not None:
        body["apply"] = flags["apply"]
    if flags["overwrite"] is not None:
        body["overwrite"] = flags["overwrite"]
    if flags["require_summarize"] is not None:
        body["require_summarize"] = flags["require_summarize"]
    parsed_steps = _coerce_steps(flags["steps"])
    if parsed_steps is not None:
        body["steps"] = parsed_steps
    skip = _coerce_steps(flags["skip"]) or []
    if skip and (parsed_steps is not None or "steps" in body):
        dropping = set(skip)
        body["steps"] = [step for step in body.get("steps") or [] if step not in dropping]


def _finalize(body: dict[str, Any], *, for_all: bool) -> ResolvedRunConfig:
    if body.get("library") and body.get("collections"):
        raise RunConfigError(
            "Run config sets both collections and library = true. Use one scope."
        )
    year_from = _optional_int(body, "year_from")
    year_to = _optional_int(body, "year_to")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise RunConfigError("--year-from must be ≤ --year-to.")
    limit = _optional_int(body, "limit")
    if limit is not None and limit < 1:
        raise RunConfigError("limit must be ≥ 1.")
    types_raw = [str(item) for item in body.get("types") or []]
    try:
        canon = resolve_item_types(types_raw)
    except ValueError as exc:
        raise RunConfigError(str(exc)) from exc
    steps = [str(step) for step in body.get("steps") or []]
    if for_all and not steps:
        raise RunConfigError("No steps left to run.")
    unknown = [step for step in steps if step not in KNOWN_STEPS]
    if unknown:
        known = ", ".join(KNOWN_STEPS)
        raise RunConfigError(
            f"Unknown step(s): {', '.join(unknown)}. Known: {known}"
        )
    if len(steps) != len(set(steps)):
        raise RunConfigError("Duplicate steps in the run config.")
    preset = body.get("preset")
    if preset is not None and str(preset) not in SOURCE_PRESETS:
        known = ", ".join(sorted(SOURCE_PRESETS))
        raise RunConfigError(f"Unknown preset {preset!r}. Known: {known}")
    sources = [str(item) for item in body.get("sources") or []]
    return ResolvedRunConfig(
        description=str(body.get("description") or ""),
        collections=[str(item) for item in body.get("collections") or []],
        library=bool(body.get("library")),
        types=sorted(canon) if canon else [],
        year_from=year_from,
        year_to=year_to,
        try_all=bool(body.get("try_all")),
        retry_failed=bool(body.get("retry_failed")),
        upgrade_linked=bool(body.get("upgrade_linked")),
        no_attach=bool(body.get("no_attach")),
        scihub=bool(body.get("scihub")),
        preset=str(preset) if preset else None,
        sources=sources,
        limit=limit,
        steps=steps,
        apply=bool(body.get("apply")),
        overwrite=bool(body.get("overwrite")),
        require_summarize=bool(body.get("require_summarize")),
    )


def _optional_int(body: dict[str, Any], key: str) -> int | None:
    if key not in body or body[key] is None:
        return None
    return _as_int(key, body[key])


def _normalize(raw: dict[str, Any], *, expect_name: str | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RunConfigError("Run config must be a TOML table.")
    unknown = sorted(set(raw) - PROFILE_KEYS)
    if unknown:
        known = ", ".join(sorted(PROFILE_KEYS))
        raise RunConfigError(
            f"Unknown run-config key(s): {', '.join(unknown)}. Known: {known}"
        )
    out: dict[str, Any] = {}
    if "name" in raw:
        name = _as_str("name", raw["name"])
        check_profile_name(name)
        if expect_name is not None and name != expect_name:
            raise RunConfigError(
                f"Profile declares name {name!r}; expected {expect_name!r}."
            )
        out["name"] = name
    if "description" in raw:
        out["description"] = _as_str("description", raw["description"])
    if "collections" in raw:
        out["collections"] = _as_str_list("collections", raw["collections"])
    if "types" in raw:
        out["types"] = _as_str_list("types", raw["types"])
    if "sources" in raw:
        out["sources"] = _as_str_list("sources", raw["sources"])
    if "steps" in raw:
        out["steps"] = _as_str_list("steps", raw["steps"])
    if "library" in raw:
        out["library"] = _as_bool("library", raw["library"])
    for key in (
        "try_all",
        "retry_failed",
        "upgrade_linked",
        "no_attach",
        "scihub",
        "apply",
        "overwrite",
        "require_summarize",
    ):
        if key in raw:
            out[key] = _as_bool(key, raw[key])
    for key in ("year_from", "year_to", "limit"):
        if key in raw and raw[key] is not None:
            out[key] = _as_int(key, raw[key])
    if "preset" in raw and raw["preset"] is not None:
        out["preset"] = _as_str("preset", raw["preset"])
    return out


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        raw = tomllib.loads(text)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RunConfigError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RunConfigError(f"{path} must be a TOML table.")
    return raw


def _coerce_steps(value: str | list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
        return parts
    out: list[str] = []
    for item in value:
        out.extend(_coerce_steps(str(item)) or [])
    if not out and not value:
        return None
    return out


def _as_str(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise RunConfigError(f"{key} must be a string.")
    return value.strip()


def _as_bool(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise RunConfigError(f"{key} must be true or false.")
    return value


def _as_int(key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunConfigError(f"{key} must be an integer.")
    return value


def _as_str_list(key: str, value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RunConfigError(f"{key} must be an array of strings.")
    return [item.strip() for item in value if item.strip()]


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _toml_str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_str(str(item)) for item in value) + "]"
    raise RunConfigError(f"Cannot write run-config value {value!r}.")
