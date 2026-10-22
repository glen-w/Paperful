"""Optional ``witness`` block on ``paperful.run_report.v1`` (trust thicken).

Additive only — not part of ``RUN_REPORT_KEYS``. Answers which config, profile,
models, and scope produced a batch without needing git.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config

SCHEMA = "paperful.witness.v1"

# Never hash secrets into the witness (attrs on Config and TOML keys).
_SECRET_ATTRS = frozenset(
    {
        "core_api_key",
        "openalex_api_key",
        "serpapi_api_key",
        "twenty_api_key",
        "mendeley_client_secret",
        "mendeley_access_token",
        "mendeley_refresh_token",
        "client_secret",
        "access_token",
        "refresh_token",
        "api_key",
        "token",
        "password",
        "secret",
    }
)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _SECRET_ATTRS:
        return True
    return any(
        part in lowered
        for part in ("api_key", "token", "password", "secret", "client_secret")
    )


def _redact_mapping(data: Any) -> Any:
    """Drop secret-looking keys from nested TOML/JSON structures."""
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            name = str(key)
            if _is_secret_key(name):
                continue
            redacted = _redact_mapping(value)
            # Drop tables that only held secrets (e.g. ``[mendeley]`` with
            # ``client_secret`` alone) so digests stay stable.
            if isinstance(redacted, dict) and not redacted:
                continue
            out[name] = redacted
        return out
    if isinstance(data, list):
        return [_redact_mapping(item) for item in data]
    return data


def config_sha256(cfg: Config) -> str:
    """SHA-256 of a secret-redacted config fingerprint.

    Prefer hashing the on-disk TOML with secret keys stripped so shared run
    reports never fingerprint ``core_api_key`` / Mendeley secrets. Fall back to
    a redacted in-memory snapshot when no file is loaded.
    """
    path = cfg.config_path
    if path is not None and Path(path).is_file():
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover — py<3.11
            import tomli as tomllib  # type: ignore[no-redef]

        try:
            raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            raw = None
        if isinstance(raw, dict):
            payload = _redact_mapping(raw)
            blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
            return hashlib.sha256(blob.encode("utf-8")).hexdigest()
    payload = _effective_snapshot(cfg)
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _effective_snapshot(cfg: Config) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in sorted(cfg.__dict__.items()):
        if key in _SECRET_ATTRS or _is_secret_key(key):
            continue
        if key.startswith("_"):
            continue
        if isinstance(value, Path):
            out[key] = str(value)
        elif isinstance(value, (str, int, float, bool, type(None))):
            out[key] = value
        elif isinstance(value, (list, tuple)):
            out[key] = list(value)
        elif isinstance(value, dict):
            out[key] = _redact_mapping({str(k): v for k, v in value.items()})
    return out


def build_witness(
    cfg: Config,
    *,
    bound: Any | None = None,
    command: str = "",
    command_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a ``paperful.witness.v1`` block for a run report."""
    digest = config_sha256(cfg)
    scope: dict[str, Any] = {
        "collections": [],
        "library": False,
        "year_from": None,
        "year_to": None,
        "types": [],
    }
    profile = ""
    run_config_path: str | None = None
    preset: str | None = None
    sources: list[str] = list(cfg.sources or [])
    if bound is not None:
        profile = str(getattr(bound, "name", None) or "") or ""
        scope["collections"] = list(getattr(bound, "collections", None) or [])
        scope["library"] = bool(getattr(bound, "library", False))
        scope["year_from"] = getattr(bound, "year_from", None)
        scope["year_to"] = getattr(bound, "year_to", None)
        scope["types"] = list(getattr(bound, "types", None) or [])
        preset = getattr(bound, "preset", None)
        bound_sources = list(getattr(bound, "sources", None) or [])
        if bound_sources:
            sources = bound_sources
        origins = getattr(bound, "origins", ()) or ()
        for origin in origins:
            text = str(origin)
            if text.endswith(".toml") and "profiles" in text.replace("\\", "/"):
                run_config_path = text
                break

    witness: dict[str, Any] = {
        "schema": SCHEMA,
        "paperful_version": __version__,
        "config_path": str(cfg.config_path) if cfg.config_path else "",
        "config_sha256": digest,
        "profile": profile,
        "run_config_path": run_config_path,
        "scope": scope,
        "fetch": {
            "preset": preset,
            "sources": sources,
        },
        "llm": {
            "enabled": bool(cfg.llm_enabled),
            "provider": cfg.llm_provider if cfg.llm_enabled else "",
            "model": cfg.llm_model if cfg.llm_enabled else "",
            "browser_agent_model": (
                (cfg.browser_agent_model or cfg.llm_model) if cfg.llm_enabled else ""
            ),
            "rag_model": (
                (cfg.rag_model or cfg.llm_model)
                if cfg.llm_enabled and cfg.rag_enabled
                else ""
            ),
        },
        "rag_index": _rag_index_block(cfg),
        "mirror_sync": _mirror_sync_block(cfg),
    }
    if command:
        witness["command"] = command
    if command_extra:
        witness["command_extra"] = command_extra
    return witness


def attach_witness(
    report: dict[str, Any],
    cfg: Config,
    *,
    bound: Any | None = None,
    command_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach a witness block to ``report`` in place and return it."""
    if report.get("witness"):
        return report
    command = str(report.get("command") or "")
    report["witness"] = build_witness(
        cfg, bound=bound, command=command, command_extra=command_extra
    )
    return report


def _rag_index_block(cfg: Config) -> dict[str, Any]:
    block: dict[str, Any] = {
        "enabled": bool(cfg.rag_enabled),
        "items": None,
        "embed_model": cfg.rag_embed_model if cfg.rag_enabled else None,
    }
    if not cfg.rag_enabled:
        return block
    try:
        from .rag.status import index_status

        status = index_status(cfg)
        block["items"] = status.get("items")
        if status.get("embed_model"):
            block["embed_model"] = status.get("embed_model")
    except Exception:
        pass
    return block


def _mirror_sync_block(cfg: Config) -> dict[str, Any]:
    path = cfg.out_dir / "_sync.json"
    if not path.is_file():
        return {"last_refresh": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"last_refresh": None}
    return {
        "last_refresh": data.get("finished_at")
        or data.get("refreshed_at")
        or data.get("at")
    }
