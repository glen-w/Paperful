"""Pull-only snowball watch: re-run a profile, remember seen works, propose new ones."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from ..config import Config
from ..run_config import RunConfigError, check_profile_name
from .candidate import Candidate
from .command import PathResult, SnowballError, SnowballRequest, run_collection, run_doi, run_orcid, run_search
from .profile import load_profile, request_from_profile
from .queue import load_queue

SCHEMA = "paperful.snowball.watch.v1"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass
class WatchResult:
    run_dir: Path
    exit_code: int
    baseline: bool
    proposed: int
    already_seen: int
    baseline_count: int = 0


def watches_root(cfg: Config) -> Path:
    return cfg.state_dir / "snowball" / "watches"


def watch_dir(cfg: Config, name: str) -> Path:
    return watches_root(cfg) / name


def _check_watch_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise SnowballError(
            f"Invalid watch name {name!r}. "
            "Use letters, digits, '.', '_' or '-', starting with a letter or digit."
        )


def save_watch(cfg: Config, name: str, profile: str) -> Path:
    """Point a watch at an existing kind=snowball profile. No API keys."""
    _check_watch_name(name)
    try:
        check_profile_name(profile)
    except RunConfigError as exc:
        raise SnowballError(str(exc)) from exc
    raw = load_profile(cfg, profile)
    if str(raw.get("kind") or "") != "snowball":
        raise SnowballError(f"Profile {profile!r} is not kind = snowball.")
    dest = watch_dir(cfg, name)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "watch.json"
    if path.is_file():
        body = json.loads(path.read_text(encoding="utf-8"))
        body["profile"] = profile
        body["schema"] = SCHEMA
    else:
        body = {
            "schema": SCHEMA,
            "profile": profile,
            "baseline_at": None,
            "last_run_at": None,
            "last_run_id": None,
        }
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    if not (dest / "seen.json").is_file():
        (dest / "seen.json").write_text(
            json.dumps({"identities": []}, indent=2) + "\n", encoding="utf-8"
        )
    if not (dest / "inbox.jsonl").is_file():
        (dest / "inbox.jsonl").write_text("", encoding="utf-8")
    return path


def load_watch(cfg: Config, name: str) -> dict[str, Any]:
    path = watch_dir(cfg, name) / "watch.json"
    if not path.is_file():
        raise SnowballError(f"Unknown watch {name!r}. Save one with snowball watch save.")
    body = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise SnowballError(f"Corrupt watch ledger at {path}.")
    return body


def load_seen(cfg: Config, name: str) -> set[str]:
    path = watch_dir(cfg, name) / "seen.json"
    if not path.is_file():
        return set()
    body = json.loads(path.read_text(encoding="utf-8"))
    return {str(item) for item in (body.get("identities") or []) if item}


def save_seen(cfg: Config, name: str, identities: set[str]) -> None:
    dest = watch_dir(cfg, name)
    dest.mkdir(parents=True, exist_ok=True)
    ordered = sorted(identities)
    (dest / "seen.json").write_text(
        json.dumps({"identities": ordered}, indent=2) + "\n", encoding="utf-8"
    )


def append_inbox(cfg: Config, name: str, rows: list[Candidate]) -> None:
    path = watch_dir(cfg, name) / "inbox.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")


def inbox_count(cfg: Config, name: str) -> int:
    path = watch_dir(cfg, name) / "inbox.jsonl"
    if not path.is_file():
        return 0
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def show_watch(cfg: Config, name: str, *, console: Console) -> None:
    body = load_watch(cfg, name)
    count = inbox_count(cfg, name)
    seen = len(load_seen(cfg, name))
    console.print(f"watch {name}")
    console.print(f"  profile · {body.get('profile')}")
    console.print(f"  inbox · {count}")
    console.print(f"  seen · {seen}")
    if body.get("last_run_id"):
        console.print(f"  last run · {body['last_run_id']}")
    if body.get("baseline_at"):
        console.print(f"  baseline · {body['baseline_at']}")
    else:
        console.print("  baseline · not yet")


def _cursor_date(iso: str | None) -> str | None:
    """OpenAlex from_created_date is YYYY-MM-DD."""
    if not iso:
        return None
    text = str(iso).strip()
    if not text:
        return None
    return text[:10]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _force_watch_request(request: SnowballRequest) -> SnowballRequest:
    request.gate = "dry-run"
    request.fetch_pdfs = "off"
    return request


def _dispatch(
    cfg: Config,
    raw: dict[str, Any],
    request: SnowballRequest,
    *,
    console: Console,
    client: Any,
    backend: Any,
    lookup: Any,
) -> PathResult:
    """Run the profile seed. Hybrid watches the keyword hit list only (depth 0)."""
    mode = str(raw.get("mode") or "")
    if mode == "hybrid" or mode == "search":
        query = str(raw.get("query") or "").strip()
        if not query:
            raise SnowballError("Profile needs query.")
        if mode == "hybrid":
            request.depth = 0
        return run_search(
            cfg,
            query,
            request,
            console=console,
            client=client,
            backend=backend,
            lookup=lookup,
        )
    if mode == "doi":
        dois = [str(item) for item in (raw.get("dois") or [])]
        if not dois:
            raise SnowballError("Profile needs dois.")
        return run_doi(
            cfg,
            dois,
            request,
            console=console,
            client=client,
            backend=backend,
            lookup=lookup,
        )
    if mode == "orcid":
        orcid = str(raw.get("orcid") or "").strip()
        if not orcid:
            raise SnowballError("Profile needs orcid.")
        return run_orcid(
            cfg,
            orcid,
            request,
            console=console,
            client=client,
            backend=backend,
            lookup=lookup,
        )
    if mode == "collection":
        seed = str(raw.get("seed_collection") or raw.get("collection") or "").strip()
        if not seed:
            raise SnowballError("Profile needs seed_collection.")
        if not request.collection.strip():
            request.collection = seed
        return run_collection(
            cfg,
            seed,
            request,
            console=console,
            client=client,
            backend=backend,
            lookup=lookup,
        )
    raise SnowballError(
        "Profile mode must be search, hybrid, doi, orcid, or collection."
    )


def _rewrite_candidates(
    run_dir: Path,
    rows: list[Candidate],
    *,
    meta: dict[str, Any],
) -> None:
    """Replace candidates.jsonl after a watch filter. Keep crawl request counts."""
    path = run_dir / "candidates.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
    summary_path = run_dir / "summary.json"
    summary: dict[str, Any] = {}
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {}
    if not isinstance(summary, dict):
        summary = {}
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
    summary["by_status"] = by_status
    summary.update(meta)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def run_watch(
    cfg: Config,
    name: str,
    *,
    console: Console,
    client: Any = None,
    backend: Any = None,
    lookup: Any = None,
) -> WatchResult:
    if not cfg.snowball_enabled:
        raise SnowballError("Snowball is off. Set [snowball] enabled = true in config.toml.")
    _check_watch_name(name)
    body = load_watch(cfg, name)
    profile = str(body.get("profile") or "").strip()
    if not profile:
        raise SnowballError(f"Watch {name!r} has no profile.")
    raw = load_profile(cfg, profile)
    request = _force_watch_request(request_from_profile(raw, cfg))
    is_baseline = not body.get("baseline_at")
    if not is_baseline:
        request.from_created_date = _cursor_date(body.get("last_run_at") or body.get("baseline_at"))
    else:
        request.from_created_date = None

    result = _dispatch(
        cfg,
        raw,
        request,
        console=console,
        client=client,
        backend=backend,
        lookup=lookup,
    )
    run_id = result.run_dir.name
    try:
        _, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError:
        rows = []

    seen = load_seen(cfg, name)
    if is_baseline:
        for row in rows:
            key = row.identity
            if key:
                seen.add(key)
        save_seen(cfg, name, seen)
        _rewrite_candidates(
            result.run_dir,
            [],
            meta={"watch": name, "baseline": True, "baseline_count": len(seen)},
        )
        now = _now()
        body.update(
            {
                "schema": SCHEMA,
                "baseline_at": now,
                "last_run_at": now,
                "last_run_id": run_id,
            }
        )
        (watch_dir(cfg, name) / "watch.json").write_text(
            json.dumps(body, indent=2) + "\n", encoding="utf-8"
        )
        console.print(f"baseline {len(seen)} · proposed 0")
        return WatchResult(
            run_dir=result.run_dir,
            exit_code=result.exit_code,
            baseline=True,
            proposed=0,
            already_seen=len(seen),
            baseline_count=len(seen),
        )

    proposed: list[Candidate] = []
    already = 0
    for row in rows:
        key = row.identity
        if not key:
            continue
        if key in seen:
            already += 1
            continue
        seen.add(key)
        if row.status == "new":
            row.keep = True
            proposed.append(row)
    save_seen(cfg, name, seen)
    if proposed:
        append_inbox(cfg, name, proposed)
    _rewrite_candidates(
        result.run_dir,
        proposed,
        meta={
            "watch": name,
            "baseline": False,
            "proposed": len(proposed),
            "already_seen": already,
        },
    )
    now = _now()
    body.update(
        {
            "schema": SCHEMA,
            "last_run_at": now,
            "last_run_id": run_id,
        }
    )
    (watch_dir(cfg, name) / "watch.json").write_text(
        json.dumps(body, indent=2) + "\n", encoding="utf-8"
    )
    console.print(f"proposed {len(proposed)} · already seen {already}")
    return WatchResult(
        run_dir=result.run_dir,
        exit_code=result.exit_code,
        baseline=False,
        proposed=len(proposed),
        already_seen=already,
    )
