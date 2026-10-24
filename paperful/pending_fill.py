"""Read-only "pending fill" feed: Discover output waiting to become library items.

Wanted stays the one fill desk. Papers kept in a snowball queue, plus topic
watch, keepup, and authorwatch inboxes, appear here until they are in the
scoped collection; then they show up as ordinary Missing rows. This module only
reads ledger files under ``state/``; it never calls the manager or OpenAlex.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .config import Config
from .resolve import doi_key

SOURCE_LABELS: dict[str, str] = {
    "kept": "Kept in Discover queue",
    "watch": "Topic watch inbox",
    "keepup": "Keepup digest",
    "authorwatch": "Author watch inbox",
}


def _jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield data


def _title_doi(data: dict[str, Any]) -> tuple[str, str]:
    biblio = data.get("biblio") if isinstance(data.get("biblio"), dict) else {}
    ids = data.get("ids") if isinstance(data.get("ids"), dict) else {}
    title = str(data.get("title") or biblio.get("title") or "").strip()
    doi = str(data.get("doi") or ids.get("doi") or "").strip()
    return title, doi


def _muted(path: Path) -> set[str]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(i) for i in (body.get("identities") or []) if i}


def _children(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def _row(source: str, origin: str, data: dict[str, Any]) -> dict[str, Any]:
    title, doi = _title_doi(data)
    return {"source": source, "origin": origin, "title": title, "doi": doi}


def _rows(cfg: Config) -> Iterator[dict[str, Any]]:
    snow = cfg.state_dir / "snowball"
    for run in _children(snow):
        if run.name == "watches":
            continue
        for data in _jsonl(run / "candidates.jsonl"):
            if data.get("keep") is True and str(data.get("status") or "new") == "new":
                yield _row("kept", run.name, data)
    for watch in _children(snow / "watches"):
        for data in _jsonl(watch / "inbox.jsonl"):
            yield _row("watch", watch.name, data)
    for job in _children(cfg.state_dir / "keepup"):
        muted = _muted(job / "muted.json")
        for data in _jsonl(job / "inbox.jsonl"):
            row = _row("keepup", job.name, data)
            if f"doi:{doi_key(row['doi'])}" in muted:
                continue
            yield row
    for people in _children(cfg.state_dir / "authorwatch"):
        for data in _jsonl(people / "inbox.jsonl"):
            yield _row("authorwatch", people.name, data)


def pending_fill(
    cfg: Config, library_dois: set[str] | None = None
) -> dict[str, Any]:
    """Distinct pending papers (by DOI), minus anything already in the library.

    Rows without a DOI are kept (keyed by title) so nothing is silently hidden.
    """
    have = {k for d in (library_dois or set()) if (k := doi_key(d))}
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    by_source: dict[str, int] = {}
    for row in _rows(cfg):
        key = doi_key(row["doi"]) or f"title:{row['title'].lower()}"
        if not row["title"] and not row["doi"]:
            continue
        if key in seen or key in have:
            continue
        seen.add(key)
        row["source_plain"] = SOURCE_LABELS[row["source"]]
        rows.append(row)
        by_source[row["source"]] = by_source.get(row["source"], 0) + 1
    return {"rows": rows, "total": len(rows), "by_source": by_source}
