"""On-disk GUI previews and content fingerprints for review tokens."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..config import Config


def previews_dir(cfg: Config) -> Path:
    path = cfg.state_dir / "gui" / "previews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def preview_path(cfg: Config, cmd_id: str, verb: str) -> Path:
    safe = verb.replace(" ", "-")
    return previews_dir(cfg) / f"{cmd_id}-{safe}.json"


def file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_preview(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def read_preview(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
