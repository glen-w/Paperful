"""Load in-corpus cite counts from the newest refs-gap pack."""

from __future__ import annotations

import json
from pathlib import Path

from .handoff import MissingPdf

# Higher weight = spend browser time first.
_SEVERITY = {
    "paywalled": 4,
    "fetch_failed": 3,
    "no_oa": 2,
    "license_blocked": 2,
    "no_doi": 1,
    "import_ok": 0,
}


def latest_refs_gap_pack(state_dir: Path) -> Path | None:
    root = state_dir / "refs-gaps"
    if not root.is_dir():
        return None
    dirs = sorted(
        (p for p in root.iterdir() if p.is_dir() and (p / "pack.json").is_file()),
        key=lambda p: p.name,
        reverse=True,
    )
    return dirs[0] / "pack.json" if dirs else None


def cite_index(state_dir: Path) -> dict[str, int]:
    """``item_key`` and normalised DOI → in-scope citing count."""
    path = latest_refs_gap_pack(state_dir)
    if path is None:
        return {}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, int] = {}
    for row in body.get("rows") or []:
        if not isinstance(row, dict):
            continue
        n = int(row.get("cited_by_count_in_scope") or 0)
        if n < 1:
            n = len(row.get("citing_keys") or [])
        key = str(row.get("exists_key") or "").strip()
        doi = str(row.get("doi") or "").strip().lower()
        if key:
            out[key] = max(out.get(key, 0), n)
        if doi:
            out[f"doi:{doi}"] = max(out.get(f"doi:{doi}", 0), n)
        if not row.get("already_exists"):
            for citing in row.get("citing_keys") or []:
                ck = str(citing or "").strip()
                if ck:
                    out[ck] = out.get(ck, 0) + 1
    return out


def cites_for(row: MissingPdf, index: dict[str, int]) -> int:
    n = index.get(row.key, 0)
    doi = (row.doi or "").strip().lower()
    if doi:
        n = max(n, index.get(f"doi:{doi}", 0))
    return n


def severity(miss_surface: str) -> int:
    return _SEVERITY.get((miss_surface or "").strip().lower(), 1)


def latest_url_health(state_dir: Path) -> dict[str, str]:
    """Item key → worst code from the newest ``state/runs/*-urls.json``."""
    runs = state_dir / "runs"
    if not runs.is_dir():
        return {}
    files = sorted(runs.glob("*-urls.json"), key=lambda p: p.name, reverse=True)
    if not files:
        return {}
    try:
        body = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rank = {"hard_dead": 2, "paywall_html": 2, "soft_404": 1}
    out: dict[str, str] = {}
    for row in body.get("items") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "")
        key = str(row.get("item_key") or "")
        if not key or code not in rank:
            continue
        prev = out.get(key)
        if prev is None or rank[code] > rank.get(prev, 0):
            out[key] = code
    return out


def rank_key(
    row: MissingPdf,
    index: dict[str, int],
    url_health: dict[str, str] | None = None,
) -> tuple:
    """Highest score first, then dead/paywall URLs, then openable URLs, then title."""
    score = cites_for(row, index) * severity(row.miss_surface)
    health = (url_health or {}).get(row.key, "")
    dead = 0 if health in {"hard_dead", "paywall_html"} else 1
    openable = 0 if row.hint == "openable_url" else 1
    return (-score, dead, openable, (row.title or "").lower())


def rank_missing(rows: list[MissingPdf], state_dir: Path) -> list[MissingPdf]:
    index = cite_index(state_dir)
    health = latest_url_health(state_dir)
    return sorted(rows, key=lambda row: rank_key(row, index, health))
