"""Identification set for a review: one snowball run and/or one search run.

Reads packs already on disk. Does not query OpenAlex or SearXNG.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def work_identity(row: dict[str, Any]) -> str:
    doi = str(row.get("doi") or row.get("DOI") or "").strip()
    if doi:
        return doi.lower()
    for key in ("openalex_id", "id", "identity"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    url = str(row.get("url") or row.get("URL") or "").strip()
    return url


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def load_identification(
    state_dir: Path, protocol: dict[str, Any]
) -> list[dict[str, Any]]:
    """Candidate rows from the linked snowball and search packs."""
    rows: list[dict[str, Any]] = []
    snow = str(protocol.get("snowball_run") or "").strip()
    if snow:
        rows.extend(_read_jsonl(state_dir / "snowball" / snow / "candidates.jsonl"))
    search = str(protocol.get("search_run") or "").strip()
    if search:
        rows.extend(_read_jsonl(state_dir / "search" / search / "candidates.jsonl"))
    return rows


def identified_ids(rows: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    have: set[str] = set()
    for row in rows:
        ident = work_identity(row)
        if not ident or ident in have:
            continue
        have.add(ident)
        seen.append(ident)
    return seen
