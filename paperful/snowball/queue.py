"""Write the candidate queue under state/snowball/<run-id>/."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .candidate import Candidate
from .openalex import OpenAlexClient


def write_queue(
    state_dir: Path,
    run_id: str,
    rows: list[Candidate],
    client: OpenAlexClient,
    *,
    library_unread: bool,
    meta: dict[str, Any] | None = None,
) -> Path:
    dest = state_dir / "snowball" / run_id
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "candidates.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
    by_status = Counter(row.status for row in rows)
    by_hop = Counter(str(row.hop) for row in rows)
    by_backend = Counter(row.provenance.get("backend") or "" for row in rows)
    by_direction = Counter(row.direction for row in rows)
    summary: dict[str, Any] = {
        "run_id": run_id,
        "requests": client.requests,
        "status_429": client.status_429,
        "retries": client.retries,
        "by_status": dict(by_status),
        "by_hop": dict(by_hop),
        "by_backend": dict(by_backend),
        "by_direction": dict(by_direction),
        "library_unread": library_unread,
        "score": "cited_by_count",
    }
    if meta:
        summary.update(meta)
    (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return dest


def write_report(dest: Path, report: dict[str, Any]) -> None:
    (dest / "write_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )


def load_queue(state_dir: Path, run_id: str) -> tuple[Path, list[Candidate]]:
    dest = state_dir / "snowball" / run_id
    path = dest / "candidates.jsonl"
    if not path.is_file():
        raise FileNotFoundError(str(path))
    rows: list[Candidate] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(Candidate.from_dict(json.loads(line)))
    return dest, rows
