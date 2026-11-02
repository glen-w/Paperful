"""Review protocol on disk: ``state/sr/<slug>/protocol.json``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..fsio import atomic_write_json

SCHEMA = "paperful.sr.protocol.v1"


def review_dir(state_dir: Path, slug: str) -> Path:
    safe = slug.strip().replace("/", "-").replace("\\", "-") or "default"
    return state_dir / "sr" / safe


def _protocol_path(state_dir: Path, slug: str) -> Path:
    return review_dir(state_dir, slug) / "protocol.json"


def load_protocol(state_dir: Path, slug: str) -> dict[str, Any]:
    from ..store import load_json

    path = _protocol_path(state_dir, slug)
    data = load_json(path)
    if not data:
        return {"schema": SCHEMA, "slug": slug, "title": "", "question": ""}
    data.setdefault("schema", SCHEMA)
    return data


def save_protocol(state_dir: Path, slug: str, body: dict[str, Any]) -> Path:
    dest = review_dir(state_dir, slug)
    dest.mkdir(parents=True, exist_ok=True)
    path = _protocol_path(state_dir, slug)
    payload = {
        "schema": SCHEMA,
        "slug": slug,
        "title": str(body.get("title") or ""),
        "question": str(body.get("question") or ""),
        "exclude_reasons": list(body.get("exclude_reasons") or []),
    }
    atomic_write_json(path, payload)
    return path
