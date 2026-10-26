"""Discover desk row builders (no HTML)."""

from __future__ import annotations

import json
from typing import Any

from ..config import Config

_DISCOVER_TABS = ("explore", "topic", "grow", "people", "queue", "following")

DISCOVER_TABS = _DISCOVER_TABS


def resolve_discover_tab(
    tab: str | None,
    *,
    advanced: bool,
    has_candidates: bool,
    has_following: bool,
    explore_picks: bool,
    list_requested: bool,
) -> str:
    """Pick a Discover tab; honour an explicit ``tab`` when allowed."""
    allowed = {"explore", "topic", "people", "queue", "following"}
    if advanced:
        allowed.add("grow")
    if tab in allowed:
        return str(tab)
    if explore_picks:
        return "explore"
    if list_requested:
        return "people"
    if has_candidates:
        return "queue"
    if has_following:
        return "following"
    return "topic"


def candidate_title_doi(data: dict[str, Any]) -> tuple[str, str]:
    """Title and DOI from a snowball candidate row.

    Live queues store them under ``biblio`` / ``ids``. Older fixtures used
    top-level ``title`` and ``doi``.
    """
    biblio = data.get("biblio") if isinstance(data.get("biblio"), dict) else {}
    ids = data.get("ids") if isinstance(data.get("ids"), dict) else {}
    title = str(data.get("title") or biblio.get("title") or "").strip()
    doi = str(data.get("doi") or ids.get("doi") or "").strip()
    return title, doi


def newest_snowball_queue(cfg: Config) -> tuple[str, list[dict[str, Any]]]:
    root = cfg.state_dir / "snowball"
    if not root.is_dir():
        return "", []
    runs = sorted(
        [
            p
            for p in root.iterdir()
            if p.is_dir() and (p / "candidates.jsonl").is_file()
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not runs:
        return "", []
    run_id = runs[0].name
    rows: list[dict[str, Any]] = []
    with (runs[0] / "candidates.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            title, doi = candidate_title_doi(data)
            rows.append(
                {
                    "title": title,
                    "doi": doi,
                    "keep": data.get("keep"),
                    "why": str(data.get("why") or "").strip(),
                    "run_id": run_id,
                }
            )
    return run_id, rows


def snowball_stop_view(cfg: Config, run_id: str) -> tuple[bool, str]:
    """Whether the newest queue is waiting for Next hop, and any stop sentence."""
    if not run_id:
        return False, ""
    path = cfg.state_dir / "snowball" / run_id / "stop.json"
    if not path.is_file():
        return False, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, ""
    if not isinstance(data, dict):
        return False, ""
    note = str(data.get("rationale") or "").strip()
    pending = bool(data.get("awaiting_labels")) and not data.get("stopped_by")
    return pending, note


def authorwatch_inbox_rows(cfg: Config) -> list[dict[str, Any]]:
    root = cfg.state_dir / "authorwatch"
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for list_dir in sorted(root.iterdir()):
        if not list_dir.is_dir():
            continue
        inbox = list_dir / "inbox.jsonl"
        if not inbox.is_file():
            continue
        with inbox.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                title, doi = candidate_title_doi(data)
                out.append(
                    {
                        "list": list_dir.name,
                        "title": title,
                        "doi": doi,
                    }
                )
    return out


def snowball_deferred_run_id(cfg: Config) -> str:
    root = cfg.state_dir / "snowball"
    if not root.is_dir():
        return ""
    for path in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_dir() and (path / "deferred.json").is_file():
            return path.name
    return ""


def list_snowball_profiles(cfg: Config) -> list[str]:
    from ..run_config import profiles_dir

    names: list[str] = []
    folder = profiles_dir(cfg)
    if folder.is_dir():
        for path in sorted(folder.glob("*.toml")):
            try:
                import sys

                if sys.version_info >= (3, 11):
                    import tomllib as _toml
                else:
                    import tomli as _toml
                raw = _toml.loads(path.read_bytes())
            except Exception:
                continue
            if isinstance(raw, dict) and str(raw.get("kind") or "") == "snowball":
                names.append(path.stem)
    for name, table in (cfg.run_profiles or {}).items():
        if isinstance(table, dict) and str(table.get("kind") or "") == "snowball":
            if name not in names:
                names.append(name)
    return sorted(names)


def authorwatch_lists(cfg: Config) -> list[dict[str, Any]]:
    from ..authorwatch import inbox_count, load_people, load_watch

    root = cfg.state_dir / "authorwatch"
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not (path / "watch.json").is_file():
            continue
        name = path.name
        try:
            watch = load_watch(cfg, name)
        except Exception:
            watch = {}
        people = load_people(cfg, name)
        out.append(
            {
                "name": name,
                "people": len(people),
                "inbox": inbox_count(cfg, name),
                "baseline": bool(watch.get("baseline_at")),
            }
        )
    return out


def authorwatch_people_rows(cfg: Config, name: str) -> list[dict[str, Any]]:
    from ..authorwatch import load_people

    rows: list[dict[str, Any]] = []
    for person in load_people(cfg, name):
        rows.append(
            {
                "id": person.id,
                "display_name": person.display_name or person.id,
                "orcid": person.orcid,
                "status": person.status,
                "affiliation": person.affiliation_host,
                "identity": person.identity(),
            }
        )
    return rows


def authorwatch_suggestion_rows(cfg: Config, name: str) -> list[dict[str, Any]]:
    from ..authorwatch import load_suggestions

    rows: list[dict[str, Any]] = []
    for row in load_suggestions(cfg, name):
        if row.status != "pending":
            continue
        rows.append(
            {
                "id": row.id,
                "display_name": row.display_name,
                "orcid": row.orcid,
                "openalex": row.openalex,
                "method": row.method,
                "score": row.score,
                "why": row.why,
                "pollable": row.pollable,
            }
        )
    return rows


def following_lists(cfg: Config) -> list[dict[str, Any]]:
    """Snowball watches and authorwatch lists for Discover."""
    out: list[dict[str, Any]] = []
    watches = cfg.state_dir / "snowball" / "watches"
    if watches.is_dir():
        for p in sorted(watches.iterdir()):
            if p.is_dir():
                out.append({"kind": "topic", "name": p.name})
    aw = cfg.state_dir / "authorwatch"
    if aw.is_dir():
        for p in sorted(aw.iterdir()):
            if p.is_dir() and (p / "watch.json").is_file():
                out.append({"kind": "person", "name": p.name})
    return out
