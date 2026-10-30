"""Read and write ``paperful.network.v1`` runs under ``state/network/<run-id>/``."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Config
from ..snowball.openalex import normalize_orcid

SCHEMA = "paperful.network.v1"
META_KEYS = frozenset(
    {
        "schema",
        "run_id",
        "orcid",
        "openalex",
        "display_name",
        "built_at",
        "phases",
        "partition",
        "max_works",
        "max_alters",
        "works",
        "nodes",
        "edges",
        "advanced",
        "advanced_error",
    }
)
GRAPH_KEYS = frozenset({"schema", "ego", "nodes", "edges"})
_SAFE_RUN = re.compile(r"^[A-Za-z0-9._-]{4,80}$")


class NetworkError(RuntimeError):
    """User-facing network verb failure."""

    def __init__(self, message: str, *, code: int = 1):
        super().__init__(message)
        self.code = code


def network_root(cfg: Config) -> Path:
    return cfg.state_dir / "network"


def run_dir(cfg: Config, run_id: str) -> Path:
    cleaned = (run_id or "").strip()
    if not _SAFE_RUN.match(cleaned):
        raise NetworkError("Run id must be 4–80 letters, digits, dots, underscores, or hyphens.")
    return network_root(cfg) / cleaned


def new_run_id(orcid: str = "") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tail = normalize_orcid(orcid).replace("-", "")[-8:] if orcid else "ego"
    return f"{stamp}-{tail or 'ego'}"


def write_run(
    dest: Path,
    *,
    meta: dict[str, Any],
    graph: dict[str, Any],
    phases: dict[str, dict[str, Any]],
    metrics: dict[str, Any],
    attributes: list[dict[str, str]] | None = None,
) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "phases").mkdir(parents=True, exist_ok=True)
    _write_json(dest / "meta.json", meta)
    _write_json(dest / "graph.json", graph)
    _write_json(dest / "metrics.json", metrics)
    for slug, payload in phases.items():
        _write_json(dest / "phases" / f"{slug}.json", payload)
    if attributes is not None:
        from .attributes import write_attributes_csv

        write_attributes_csv(dest / "attributes.csv", attributes)
    return dest


def load_run(cfg: Config, run_id: str) -> dict[str, Any]:
    dest = run_dir(cfg, run_id)
    meta_path = dest / "meta.json"
    if not meta_path.is_file():
        raise NetworkError(f"No network run at {dest}.", code=1)
    meta = _read_json(meta_path)
    graph = _read_json(dest / "graph.json") if (dest / "graph.json").is_file() else {}
    metrics = _read_json(dest / "metrics.json") if (dest / "metrics.json").is_file() else {}
    phases: dict[str, Any] = {}
    phase_dir = dest / "phases"
    if phase_dir.is_dir():
        for path in sorted(phase_dir.glob("*.json")):
            phases[path.stem] = _read_json(path)
    attributes: list[dict[str, str]] = []
    csv_path = dest / "attributes.csv"
    if csv_path.is_file():
        from .attributes import read_attributes_csv

        attributes = read_attributes_csv(csv_path)
    return {
        "schema": str(meta.get("schema") or SCHEMA),
        "run_id": run_id,
        "path": str(dest),
        "meta": meta,
        "graph": graph,
        "metrics": metrics,
        "phases": phases,
        "attributes": attributes,
    }


def list_runs(cfg: Config) -> list[dict[str, Any]]:
    root = network_root(cfg)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for dest in sorted(root.iterdir(), reverse=True):
        meta_path = dest / "meta.json"
        if not dest.is_dir() or not meta_path.is_file():
            continue
        try:
            meta = _read_json(meta_path)
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(
            {
                "run_id": dest.name,
                "orcid": str(meta.get("orcid") or ""),
                "display_name": str(meta.get("display_name") or ""),
                "built_at": str(meta.get("built_at") or ""),
                "phases": [str(p.get("id") or "") for p in (meta.get("phases") or [])],
                "partition": str(meta.get("partition") or "none"),
                "nodes": int(meta.get("nodes") or 0),
                "edges": int(meta.get("edges") or 0),
            }
        )
    rows.sort(key=lambda row: str(row.get("built_at") or ""), reverse=True)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise NetworkError(f"{path} is not a JSON object.")
    return data
