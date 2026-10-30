"""Read and write ``paperful.search.v1`` runs under ``state/search/<run-id>/``."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Config

SCHEMA = "paperful.search.v1"
META_KEYS = frozenset(
    {
        "schema",
        "run_id",
        "query",
        "filetype",
        "hosts",
        "engine_host",
        "built_at",
        "max",
        "probe",
        "partial",
    }
)
HIT_KEYS = frozenset(
    {"url", "title", "score", "host", "playbook", "kind", "status", "year", "doi"}
)
SUMMARY_KEYS = frozenset({"hits", "kept", "exists", "blocked", "new", "dropped"})
_SAFE_RUN = re.compile(r"^[A-Za-z0-9._-]{4,80}$")


class SearchError(RuntimeError):
    """User-facing search verb failure."""

    def __init__(self, message: str, *, code: int = 1):
        super().__init__(message)
        self.code = code


def search_root(cfg: Config) -> Path:
    return cfg.state_dir / "search"


def cache_dir(cfg: Config) -> Path:
    return search_root(cfg) / "cache"


def run_dir(cfg: Config, run_id: str) -> Path:
    cleaned = (run_id or "").strip()
    if not _SAFE_RUN.match(cleaned):
        raise SearchError("Run id must be 4–80 letters, digits, dots, underscores, or hyphens.")
    return search_root(cfg) / cleaned


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-web"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if isinstance(data, dict):
                rows.append(data)
    return rows


def write_run(
    dest: Path,
    *,
    meta: dict[str, Any],
    hits: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    summary: dict[str, Any],
) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    _write_json(dest / "meta.json", meta)
    write_jsonl(dest / "hits.jsonl", hits)
    write_jsonl(dest / "candidates.jsonl", candidates)
    _write_json(dest / "summary.json", summary)
    return dest


def load_run(cfg: Config, run_id: str, *, dest: Path | None = None) -> dict[str, Any]:
    folder = dest if dest is not None else run_dir(cfg, run_id)
    meta_path = folder / "meta.json"
    if not meta_path.is_file():
        raise SearchError(f"No search run at {folder}.", code=1)
    meta = _read_json(meta_path)
    summary = _read_json(folder / "summary.json") if (folder / "summary.json").is_file() else {}
    return {
        "schema": str(meta.get("schema") or SCHEMA),
        "run_id": str(meta.get("run_id") or run_id),
        "path": str(folder),
        "meta": meta,
        "hits": read_jsonl(folder / "hits.jsonl"),
        "candidates": read_jsonl(folder / "candidates.jsonl"),
        "summary": summary,
        "partial": bool(meta.get("partial")),
    }


def list_runs(cfg: Config) -> list[dict[str, Any]]:
    root = search_root(cfg)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for dest in sorted(root.iterdir(), reverse=True):
        if dest.name == "cache" or not dest.is_dir():
            continue
        meta_path = dest / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = _read_json(meta_path)
        except (OSError, json.JSONDecodeError):
            continue
        summary = {}
        summary_path = dest / "summary.json"
        if summary_path.is_file():
            try:
                summary = _read_json(summary_path)
            except (OSError, json.JSONDecodeError):
                summary = {}
        rows.append(
            {
                "run_id": dest.name,
                "query": str(meta.get("query") or ""),
                "built_at": str(meta.get("built_at") or ""),
                "hosts": list(meta.get("hosts") or []),
                "kept": int(summary.get("kept") or 0),
                "new": int(summary.get("new") or 0),
            }
        )
    rows.sort(key=lambda row: str(row.get("built_at") or ""), reverse=True)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SearchError(f"{path} is not a JSON object.")
    return data
