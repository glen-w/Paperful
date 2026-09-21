"""Parent witness that links one operator sequence of run reports.

`state/packs/<id>.json` lists child files under `state/runs/`. The item ledger
(`state/manifest.jsonl`) and `state/last-run.json` are unchanged.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config

SCHEMA = "paperful.pack.v1"


class PackError(Exception):
    """A pack is already open, or none is open when close needs one."""


def packs_dir(cfg: Config) -> Path:
    return cfg.state_dir / "packs"


def current_path(cfg: Config) -> Path:
    return packs_dir(cfg) / "current"


def pack_path(cfg: Config, pack_id: str) -> Path:
    return packs_dir(cfg) / f"{pack_id}.json"


def pack_join_disabled() -> bool:
    return os.environ.get("PAPERFUL_PACK", "").strip().lower() == "off"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or _now()).strftime("%Y%m%dT%H%M%SZ")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, pack: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def current_id(cfg: Config) -> str | None:
    path = current_path(cfg)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def open_pack(cfg: Config, label: str | None = None) -> dict[str, Any]:
    """Create `state/packs/<id>.json` and point `current` at it."""
    existing = current_id(cfg)
    if existing:
        raise PackError(f"Pack {existing} is still open. Close it first.")
    moment = _now()
    pack_id = _stamp(moment)
    pack: dict[str, Any] = {
        "schema": SCHEMA,
        "id": pack_id,
        "status": "open",
        "opened_at": moment.isoformat(),
        "closed_at": None,
        "scope": "",
        "steps": [],
    }
    if label and label.strip():
        pack["label"] = label.strip()
    _write(pack_path(cfg, pack_id), pack)
    current_path(cfg).write_text(pack_id + "\n", encoding="utf-8")
    return pack


def close_pack(cfg: Config) -> dict[str, Any]:
    """Mark the open pack closed and remove the `current` pointer."""
    pack_id = current_id(cfg)
    if not pack_id:
        raise PackError("No pack is open.")
    path = pack_path(cfg, pack_id)
    if not path.is_file():
        current_path(cfg).unlink(missing_ok=True)
        raise PackError(f"Pack {pack_id} is missing on disk.")
    pack = _read(path)
    pack["status"] = "closed"
    pack["closed_at"] = _now().isoformat()
    _write(path, pack)
    current_path(cfg).unlink(missing_ok=True)
    return pack


def note_pack_step(cfg: Config, report: dict[str, Any], report_path: Path) -> None:
    """Append this report to the open pack. No-op when none is open or opted out."""
    if pack_join_disabled():
        return
    pack_id = current_id(cfg)
    if not pack_id:
        return
    path = pack_path(cfg, pack_id)
    if not path.is_file():
        return
    try:
        pack = _read(path)
    except (OSError, ValueError):
        return
    if pack.get("status") != "open":
        return
    step = {
        "command": str(report.get("command") or ""),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "report": report_path.name,
    }
    pack.setdefault("steps", []).append(step)
    if not pack.get("scope") and report.get("scope"):
        pack["scope"] = report["scope"]
    try:
        _write(path, pack)
    except OSError:
        return


def latest_pack(cfg: Config) -> dict[str, Any] | None:
    """The open pack, or the newest closed pack by id stamp."""
    pack_id = current_id(cfg)
    if pack_id:
        path = pack_path(cfg, pack_id)
        if path.is_file():
            try:
                return _read(path)
            except (OSError, ValueError):
                return None
    folder = packs_dir(cfg)
    if not folder.is_dir():
        return None
    files = sorted(p for p in folder.glob("*.json") if p.is_file())
    if not files:
        return None
    try:
        return _read(files[-1])
    except (OSError, ValueError):
        return None


def show_payload(cfg: Config, pack: dict[str, Any]) -> dict[str, Any]:
    """Parent plus each step's summary. Child `items` arrays stay in the report file."""
    out = dict(pack)
    steps: list[dict[str, Any]] = []
    for step in pack.get("steps") or []:
        row = dict(step)
        name = str(step.get("report") or "")
        child = cfg.state_dir / "runs" / name if name else None
        summary: dict[str, Any] = {}
        duration = None
        if child is not None and child.is_file():
            try:
                data = json.loads(child.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            summary = dict(data.get("summary") or {})
            duration = data.get("duration_s")
        row["summary"] = summary
        row["duration_s"] = duration
        steps.append(row)
    out["steps"] = steps
    return out


def headline(command: str, summary: dict[str, Any]) -> str:
    """One line of counts for `pack show`."""
    if command == "gaps":
        return (
            f"items {summary.get('items', 0)}, "
            f"no PDF {summary.get('no_stored_pdf', 0)}, "
            f"linked URL {summary.get('linked_url_only', 0)}, "
            f"missing DOI {summary.get('missing_doi', 0)}"
        )
    if command == "lint":
        return f"findings {summary.get('findings', 0)}"
    if command == "summarize":
        return (
            f"summarized {summary.get('summarized', 0)}, "
            f"failed {summary.get('failed', 0)}"
        )
    if command == "fix-metadata":
        proposed = summary.get("patches_proposed", summary.get("fields_corrected", 0))
        applied = summary.get("patches_applied")
        if applied is None:
            return f"proposed {proposed}"
        return f"applied {applied}/{proposed}"
    if command in {"run", "recover"}:
        return (
            f"downloaded {summary.get('pdfs_downloaded', 0)}, "
            f"attached {summary.get('attached', 0)}, "
            f"not_found {summary.get('not_found', 0)}"
        )
    if command == "synthesize":
        return (
            f"included {summary.get('included', 0)}, "
            f"missing {summary.get('missing', 0)}"
        )
    parts: list[str] = []
    for key, value in summary.items():
        if isinstance(value, int) and not isinstance(value, bool):
            parts.append(f"{key} {value}")
        if len(parts) >= 4:
            break
    return ", ".join(parts)
