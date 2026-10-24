"""Write the candidate queue under state/snowball/<run-id>/."""

from __future__ import annotations

import json
import os
import uuid
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
    write_rows(path, rows)
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
    if client.deferred:
        summary["deferred"] = True
        (dest / "deferred.json").write_text(
            json.dumps(client.deferred, indent=2) + "\n", encoding="utf-8"
        )
    if meta:
        summary.update(meta)
    (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    from .citation_graph import write_graph

    write_graph(
        dest,
        rows,
        run_id=run_id,
        map_categories=summary.get("map_categories"),
        map_category_defs=summary.get("map_category_defs"),
    )
    return dest


def write_report(dest: Path, report: dict[str, Any]) -> None:
    (dest / "write_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file and rename.

    A crash or a concurrent reader never sees a half-written queue.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_rows(path: Path, rows: list[Candidate]) -> None:
    """Replace a candidates.jsonl atomically."""
    atomic_write_text(
        path, "".join(json.dumps(row.to_dict(), ensure_ascii=False) + "\n" for row in rows)
    )


def load_queue_checked(state_dir: Path, run_id: str) -> tuple[Path, list[Candidate], int]:
    """Like ``load_queue``, plus how many damaged lines were skipped."""
    dest = state_dir / "snowball" / run_id
    path = dest / "candidates.jsonl"
    if not path.is_file():
        raise FileNotFoundError(str(path))
    rows: list[Candidate] = []
    skipped = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError("not an object")
                rows.append(Candidate.from_dict(data))
            except Exception:
                # One damaged line (an interrupted write, a hand edit) must not
                # take the whole queue down.
                skipped += 1
    return dest, rows, skipped


def load_queue(state_dir: Path, run_id: str) -> tuple[Path, list[Candidate]]:
    dest, rows, _skipped = load_queue_checked(state_dir, run_id)
    return dest, rows
